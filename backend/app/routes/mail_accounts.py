"""
Mail accounts routes — management of connected third-party email accounts.
"""

from __future__ import annotations

import urllib.request
import urllib.parse
from flask import Blueprint, jsonify, request, session, current_app

from app.extensions import db
from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.services.encryption import decrypt_token
from app.services.sync_service import (
    sync_gmail_mailbox,
    start_background_sync,
    sync_gmail_incremental,
    start_background_incremental_sync,
)

mail_bp = Blueprint("mail", __name__, url_prefix="/api/mail")


def _get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


@mail_bp.route("/accounts", methods=["GET"])
def get_connected_accounts():
    """Retrieve all connected email accounts for the authenticated MailMild user.
    
    Returns safe account metadata only (NO tokens).
    """
    user = _get_current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    try:
        accounts = (
            ConnectedEmailAccount.query.filter_by(user_id=user.id)
            .order_by(ConnectedEmailAccount.created_at.desc())
            .all()
        )
        return jsonify({"accounts": [acc.to_safe_dict() for acc in accounts]}), 200
    except Exception as exc:
        current_app.logger.error("Error retrieving connected accounts: %s", exc)
        return jsonify({"error": "Failed to fetch connected accounts."}), 500


@mail_bp.route("/disconnect", methods=["POST"])
def disconnect_account():
    """Disconnect a connected email account.
    
    Revokes the provider OAuth token if possible and removes the connected account.
    Does NOT delete the MailMild user account.
    """
    user = _get_current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get("account_id")

        if account_id:
            account = ConnectedEmailAccount.query.filter_by(
                id=account_id, user_id=user.id
            ).first()
        else:
            # Default to first connected account
            account = ConnectedEmailAccount.query.filter_by(
                user_id=user.id
            ).first()

        if not account:
            return jsonify({"message": "No connected account found to disconnect."}), 200

        # Attempt to revoke OAuth token with Google
        try:
            if account.encrypted_access_token:
                access_token = decrypt_token(account.encrypted_access_token)
                if access_token and access_token != "mock-access-token":
                    revoke_url = f"https://oauth2.googleapis.com/revoke?token={urllib.parse.quote(access_token)}"
                    req = urllib.request.Request(revoke_url, method="POST")
                    try:
                        urllib.request.urlopen(req, timeout=5)
                    except Exception as revoke_err:
                        current_app.logger.info("Google token revocation response: %s", revoke_err)
        except Exception as decrypt_err:
            current_app.logger.warning("Could not decrypt token for revocation: %s", decrypt_err)

        # Delete the connected account record (or mark disconnected)
        db.session.delete(account)
        db.session.commit()

        return jsonify({
            "message": f"Account {account.email_address} disconnected successfully.",
            "disconnected_account_id": account.id
        }), 200

    except Exception as exc:
        current_app.logger.error("Error disconnecting account: %s", exc)
        db.session.rollback()
        return jsonify({"error": "Failed to disconnect account."}), 500


@mail_bp.route("/sync", methods=["POST"])
def trigger_sync():
    """Trigger synchronization for a connected Gmail account.

    Body (optional JSON):
        account_id: The UUID of the connected account to sync.

    Query params:
        sync_now: If "true" or during testing, runs synchronously instead of spawning a thread.

    Returns:
        202 Accepted if queued, or 200 OK if executed synchronously.
    """
    user = _get_current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")

    if account_id:
        account = ConnectedEmailAccount.query.filter_by(id=account_id).first()
        if not account:
            return jsonify({"error": "Connected account not found."}), 404
        # Multi-user isolation
        if account.user_id != user.id:
            return jsonify({"error": "Unauthorized: account belongs to another user."}), 403
    else:
        account = ConnectedEmailAccount.query.filter_by(user_id=user.id).first()
        if not account:
            return jsonify({"error": "No connected email account found for this user."}), 404

    # Concurrency guard: prevent duplicate concurrent sync jobs
    if account.sync_status == "syncing":
        return jsonify({
            "message": "Synchronization is already in progress for this account.",
            "status": "syncing",
            "account_id": account.id,
            "email_address": account.email_address,
        }), 200

    # Determine if synchronous run is requested (e.g. for unit testing)
    sync_now = request.args.get("sync_now", "").lower() == "true" or current_app.config.get("TESTING", False)

    if sync_now:
        result = sync_gmail_mailbox(account.id)
        status_code = 200 if result.get("status") == "completed" else 500
        return jsonify({
            "message": "Synchronization finished.",
            "account_id": account.id,
            "email_address": account.email_address,
            **result,
        }), status_code

    # Run in background worker thread within Flask app context
    start_background_sync(account.id, current_app._get_current_object())

    return jsonify({
        "message": "Mailbox synchronization started.",
        "status": "syncing",
        "sync_type": "full",
        "account_id": account.id,
        "email_address": account.email_address,
    }), 202


@mail_bp.route("/sync/incremental", methods=["POST"])
def trigger_incremental_sync():
    """Trigger incremental mailbox synchronization using Gmail historyId.

    Body (optional JSON):
        account_id: The UUID of the connected account to sync.

    Query params:
        sync_now: If "true" or during testing, runs synchronously instead of spawning a thread.

    Returns:
        202 Accepted if queued, or 200 OK / 400 / 404 / 409 / 500 if executed synchronously.
    """
    user = _get_current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")

    if account_id:
        account = ConnectedEmailAccount.query.filter_by(id=account_id).first()
        if not account:
            return jsonify({"error": "Connected account not found."}), 404
        # Multi-user isolation
        if account.user_id != user.id:
            return jsonify({"error": "Unauthorized: account belongs to another user."}), 403
    else:
        account = ConnectedEmailAccount.query.filter_by(user_id=user.id).first()
        if not account:
            return jsonify({"error": "No connected email account found for this user."}), 404

    # Concurrency guard: prevent duplicate concurrent sync jobs
    if account.sync_status == "syncing":
        return jsonify({
            "error": "Synchronization is already in progress for this account.",
            "message": "Synchronization is already in progress for this account.",
            "status": "syncing",
            "account_id": account.id,
            "email_address": account.email_address,
        }), 409

    sync_now = request.args.get("sync_now", "").lower() == "true" or current_app.config.get("TESTING", False)

    if sync_now:
        result = sync_gmail_incremental(account.id)
        if result.get("status") == "completed":
            status_code = 200
        elif result.get("status") == "resync_required":
            status_code = 400
        else:
            status_code = 500
        return jsonify({
            "message": "Incremental synchronization finished.",
            "account_id": account.id,
            "email_address": account.email_address,
            **result,
        }), status_code

    start_background_incremental_sync(account.id, current_app._get_current_object())

    return jsonify({
        "message": "Incremental mailbox synchronization started.",
        "status": "syncing",
        "sync_type": "incremental",
        "account_id": account.id,
        "email_address": account.email_address,
    }), 202


@mail_bp.route("/sync-status", methods=["GET"])
def get_sync_status():
    """Retrieve synchronization progress and status for a connected email account.

    Query params:
        account_id: UUID of connected account (optional).

    Returns:
        Safe sync metadata (NEVER tokens).
    """
    user = _get_current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    account_id = request.args.get("account_id")
    if account_id:
        account = ConnectedEmailAccount.query.filter_by(id=account_id).first()
        if not account:
            return jsonify({"error": "Connected account not found."}), 404
        # Multi-user isolation
        if account.user_id != user.id:
            return jsonify({"error": "Unauthorized: account belongs to another user."}), 403
    else:
        account = ConnectedEmailAccount.query.filter_by(user_id=user.id).first()
        if not account:
            return jsonify({"error": "No connected email account found."}), 404

    total_in_db = EmailMessage.query.filter_by(connected_account_id=account.id).count()
    return jsonify({
        "account_id": account.id,
        "email_address": account.email_address,
        "provider": account.provider,
        "status": account.sync_status,
        "progress": account.sync_progress,
        "history_id": account.history_id,
        "messages_synced": total_in_db or account.messages_synced or 0,
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
    }), 200
