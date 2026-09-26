"""
Contacts routes — people intelligence derived strictly from email interactions.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session, current_app

from app.extensions import db
from app.models import User
from app.services.contact_service import (
    get_contacts_list,
    get_contact_detail,
)
from app.utils.auth import login_required, validate_session

contacts_bp = Blueprint("contacts", __name__, url_prefix="/api/contacts")


def _require_auth():
    """Verify session authentication and return User or 401 response."""
    return validate_session()


@contacts_bp.route("", methods=["GET"])
@login_required
def list_contacts():
    """List paginated, sortable contacts for the authenticated user."""
    user, err = _require_auth()
    if err:
        return err

    try:
        query_str = request.args.get("q")
        sort_by = request.args.get("sort", "importance")
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 20, type=int), 100)

        data = get_contacts_list(
            user_id=user.id,
            query_str=query_str,
            sort_by=sort_by,
            page=page,
            per_page=per_page,
        )
        return jsonify(data), 200
    except Exception as exc:
        current_app.logger.error("Error listing contacts for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to list contacts."}), 500


@contacts_bp.route("/<contact_email>", methods=["GET"])
@login_required
def contact_detail(contact_email: str):
    """Retrieve detailed contact overview, conversation statistics, and recent interactions."""
    user, err = _require_auth()
    if err:
        return err

    try:
        detail = get_contact_detail(user_id=user.id, contact_email=contact_email)
        if not detail:
            return jsonify({"error": "Contact not found."}), 404
        return jsonify({"contact": detail}), 200
    except Exception as exc:
        current_app.logger.error("Error retrieving contact %s for %s: %s", contact_email, user.id, exc)
        return jsonify({"error": "Failed to retrieve contact details."}), 500
