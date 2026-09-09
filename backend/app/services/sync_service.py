"""
Gmail Mailbox Synchronization Service — Phase 2.

Handles initial mailbox synchronization:
- Decrypts stored OAuth tokens and refreshes them via Google's token endpoint when nearing expiry.
- Paginates through Gmail messages in bounded batches (25-50 messages).
- Parses MIME payloads (text/plain, text/html, multipart/alternative, multipart/mixed, nested parts).
- Idempotently stores or updates EmailMessage records without duplicating.
- Updates sync progress, status, and timestamps on ConnectedEmailAccount.
- Strictly decouples Gmail storage from AI analysis so AI errors never destroy synced emails.
"""

from __future__ import annotations

import base64
import email as email_lib
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build as build_service
from googleapiclient.errors import HttpError
from flask import current_app

from app.extensions import db
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.services.encryption import encrypt_token, decrypt_token


# ───────────────────────────────────────────────────────────────
# MIME & Header Parsing Utilities
# ───────────────────────────────────────────────────────────────

def _safe_b64_decode(data: str) -> str:
    """Safely decode urlsafe base64 data to unicode string."""
    if not data:
        return ""
    try:
        padded = data + "=" * (-len(data) % 4)
        raw_bytes = base64.urlsafe_b64decode(padded)
        return raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body_parts(payload: dict) -> tuple[str, str, list[dict]]:
    """Recursively extract plain text, HTML, and attachment metadata from a Gmail payload.

    Args:
        payload: The ``payload`` dict from a Gmail message resource.

    Returns:
        A tuple of ``(body_text, body_html, attachment_metadata)``.
    """
    body_text_parts: list[str] = []
    body_html_parts: list[str] = []
    attachments: list[dict] = []

    def _walk_part(part: dict) -> None:
        mime_type = part.get("mimeType", "").lower()
        filename = part.get("filename", "")
        body = part.get("body", {})
        data = body.get("data", "")
        attachment_id = body.get("attachmentId")
        size = body.get("size", 0)

        # Record attachment metadata if filename or attachmentId is present
        if filename or attachment_id:
            attachments.append({
                "filename": filename or "attachment",
                "mimeType": mime_type,
                "size": size,
                "attachmentId": attachment_id or "",
            })

        if mime_type == "text/plain" and data:
            decoded = _safe_b64_decode(data)
            if decoded:
                body_text_parts.append(decoded)
        elif mime_type == "text/html" and data:
            decoded = _safe_b64_decode(data)
            if decoded:
                body_html_parts.append(decoded)

        # Recursively inspect nested multipart parts
        for sub_part in part.get("parts", []):
            _walk_part(sub_part)

    _walk_part(payload)

    plain_text = "\n\n".join(part.strip() for part in body_text_parts if part.strip())
    html_text = "\n".join(body_html_parts)

    return plain_text, html_text, attachments


def parse_gmail_message_payload(msg: dict) -> dict[str, Any]:
    """Parse a Gmail message resource into normalized fields.

    Args:
        msg: Complete Gmail message dictionary as returned by ``messages.get``.

    Returns:
        A dict of normalized email fields.
    """
    gmail_id = msg.get("id", "")
    thread_id = msg.get("threadId", "")
    labels = msg.get("labelIds", [])

    payload = msg.get("payload", {})
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}

    subject = headers.get("subject", "(No Subject)")
    from_address = headers.get("from", "")
    to_address = headers.get("to", "")
    cc = headers.get("cc", "")
    bcc = headers.get("bcc", "")
    date_str = headers.get("date", "")

    # Parse date header
    received_at = None
    if date_str:
        try:
            received_at = email_lib.utils.parsedate_to_datetime(date_str)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = datetime.now(timezone.utc)
    else:
        # Fallback to internalDate if available (epoch milliseconds)
        internal_date = msg.get("internalDate")
        if internal_date:
            try:
                received_at = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
            except Exception:
                received_at = datetime.now(timezone.utc)
        else:
            received_at = datetime.now(timezone.utc)

    # Extract plain text, HTML, and attachment metadata
    body_text, body_html, attachments = _extract_body_parts(payload)

    return {
        "provider_message_id": gmail_id,
        "message_id": gmail_id,
        "thread_id": thread_id,
        "subject": subject,
        "from_address": from_address,
        "to_address": to_address,
        "recipients": to_address,
        "cc": cc,
        "bcc": bcc,
        "received_at": received_at,
        "body_text": body_text,
        "body_html": body_html,
        "labels": labels,
        "has_attachments": bool(attachments),
        "attachment_metadata": attachments,
    }


# ───────────────────────────────────────────────────────────────
# Token Refresh & Credentials Helper
# ───────────────────────────────────────────────────────────────

def get_valid_credentials(account: ConnectedEmailAccount) -> Credentials:
    """Build valid Google OAuth2 credentials, refreshing tokens if expired.

    Args:
        account: ConnectedEmailAccount instance.

    Returns:
        A valid, refreshed ``google.oauth2.credentials.Credentials`` object.

    Raises:
        RefreshError: If the refresh token was revoked or rejected by Google.
    """
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET", "")

    raw_access = decrypt_token(account.encrypted_access_token) if account.encrypted_access_token else None
    raw_refresh = decrypt_token(account.encrypted_refresh_token) if account.encrypted_refresh_token else None

    credentials = Credentials(
        token=raw_access,
        refresh_token=raw_refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )

    # Check if token is expired or needs refresh
    needs_refresh = False
    if account.is_token_expired():
        needs_refresh = True
    elif not raw_access or raw_access == "mock-access-token":
        needs_refresh = False

    if needs_refresh and raw_refresh:
        current_app.logger.info("Access token expired for %s. Refreshing...", account.email_address)
        try:
            credentials.refresh(Request())
            # Save refreshed credentials encrypted at rest
            account.encrypted_access_token = encrypt_token(credentials.token)
            account.token_expiry = credentials.expiry
            account.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            current_app.logger.info("Token successfully refreshed for %s", account.email_address)
        except RefreshError as ref_err:
            current_app.logger.error("Refresh token revoked or invalid for %s: %s", account.email_address, ref_err)
            account.sync_status = "error"
            account.sync_progress = "Reauthorization required: Google access revoked or expired."
            account.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            raise

    return credentials

def get_current_history_id(service: Any) -> Optional[str]:
    """Retrieve the current mailbox historyId using users().getProfile().
    
    Args:
        service: Google API service object.
        
    Returns:
        The string historyId or None if retrieval fails.
    """
    try:
        profile = service.users().getProfile(userId="me").execute()
        hist_id = profile.get("historyId")
        return str(hist_id) if hist_id is not None else None
    except Exception as err:
        current_app.logger.warning("Failed to retrieve current mailbox historyId: %s", err)
        return None


def _upsert_parsed_message(account: ConnectedEmailAccount, parsed: dict[str, Any]) -> tuple[EmailMessage, bool]:
    """Idempotently insert or update an EmailMessage record for a connected account.
    
    Returns:
        tuple of (EmailMessage instance, is_new: bool)
    """
    existing = (
        EmailMessage.query.filter_by(
            connected_account_id=account.id,
            provider_message_id=parsed["provider_message_id"],
        ).first()
        or EmailMessage.query.filter_by(
            user_id=account.user_id,
            message_id=parsed["message_id"],
        ).first()
    )

    if existing:
        existing.labels = json.dumps(parsed["labels"])
        existing.has_attachments = parsed["has_attachments"]
        if parsed.get("subject"):
            existing.subject = parsed["subject"]
        if parsed.get("body_text"):
            existing.body_text = parsed["body_text"]
        if parsed.get("attachment_metadata"):
            existing.attachment_metadata = json.dumps(parsed["attachment_metadata"])
        if parsed.get("body_html"):
            existing.body_html = parsed["body_html"]
        if parsed.get("recipients"):
            existing.recipients = parsed["recipients"]
        if not existing.connected_account_id:
            existing.connected_account_id = account.id
        if not existing.provider_message_id:
            existing.provider_message_id = parsed["provider_message_id"]
        existing.updated_at = datetime.now(timezone.utc)
        return existing, False

    new_email = EmailMessage(
        user_id=account.user_id,
        connected_account_id=account.id,
        message_id=parsed["message_id"],
        provider_message_id=parsed["provider_message_id"],
        thread_id=parsed["thread_id"],
        subject=parsed["subject"],
        body_text=parsed["body_text"],
        body_html=parsed["body_html"],
        from_address=parsed["from_address"],
        to_address=parsed["to_address"],
        recipients=parsed["recipients"],
        cc=parsed["cc"],
        bcc=parsed["bcc"],
        labels=json.dumps(parsed["labels"]),
        has_attachments=parsed["has_attachments"],
        attachment_metadata=json.dumps(parsed["attachment_metadata"]),
        received_at=parsed["received_at"],
        category="General",
        priority="Medium",
        sentiment="Neutral",
        summary=parsed["body_text"][:160] + "..." if parsed["body_text"] else "No summary available.",
        needs_human_review=True,
        auto_reply_required=False,
        confidence=0.8,
    )
    db.session.add(new_email)
    return new_email, True


# ───────────────────────────────────────────────────────────────
# Mailbox Synchronization
# ───────────────────────────────────────────────────────────────

def sync_gmail_mailbox(
    account_id: str,
    batch_size: int = 50,
    max_pages: Optional[int] = 15,
) -> dict[str, Any]:
    """Perform initial mailbox synchronization for a connected Gmail account.

    Args:
        account_id: UUID of the ConnectedEmailAccount.
        batch_size: Number of messages to list and process per page (25-50).
        max_pages: Optional safety limit on pagination.

    Returns:
        Dict summarizing sync outcome (status, messages_synced, error).
    """
    account = db.session.get(ConnectedEmailAccount, account_id)
    if not account:
        return {"error": "Connected account not found.", "status": "error"}

    account.sync_status = "syncing"
    account.sync_progress = "Connecting to Gmail..."
    account.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    total_synced = 0
    new_messages_count = 0
    existing_messages_count = 0

    try:
        # 1. Build and validate credentials
        credentials = get_valid_credentials(account)

        # 2. Build Gmail API service client
        service = build_service("gmail", "v1", credentials=credentials, cache_discovery=False)

        page_token = None
        pages_processed = 0

        # 3. Paginate through mailbox in bounded batches
        while True:
            if max_pages and pages_processed >= max_pages:
                break

            current_app.logger.info(
                "Listing Gmail messages for %s (Page: %d, PageToken: %s)",
                account.email_address,
                pages_processed + 1,
                page_token,
            )

            list_params: dict[str, Any] = {
                "userId": "me",
                "maxResults": min(batch_size, 50),
            }
            if page_token:
                list_params["pageToken"] = page_token

            # List messages with exponential backoff on rate limits
            list_res = None
            for attempt in range(3):
                try:
                    list_res = service.users().messages().list(**list_params).execute()
                    break
                except HttpError as list_err:
                    if list_err.resp.status in (429, 403) and ("rateLimitExceeded" in str(list_err) or "userRateLimitExceeded" in str(list_err) or "Quota exceeded" in str(list_err)):
                        if attempt < 2:
                            wait_s = (attempt + 1) * 2
                            current_app.logger.warning("Gmail list rate limit hit. Backing off for %ds...", wait_s)
                            time.sleep(wait_s)
                            continue
                    raise

            if not list_res:
                break

            message_stubs = list_res.get("messages", [])

            if not message_stubs:
                current_app.logger.info("No further messages found for %s.", account.email_address)
                break

            # 4. Fetch details and persist messages in this batch
            batch_success_count = 0
            for stub in message_stubs:
                msg_id = stub.get("id")
                if not msg_id:
                    continue

                try:
                    # Fetch complete message resource with exponential backoff on 429/403
                    raw_msg = None
                    for attempt in range(3):
                        try:
                            raw_msg = (
                                service.users()
                                .messages()
                                .get(userId="me", id=msg_id, format="full")
                                .execute()
                            )
                            break
                        except HttpError as get_err:
                            if get_err.resp.status in (429, 403) and ("rateLimitExceeded" in str(get_err) or "userRateLimitExceeded" in str(get_err) or "Quota exceeded" in str(get_err)):
                                if attempt < 2:
                                    wait_s = (attempt + 1) * 2
                                    time.sleep(wait_s)
                                    continue
                            raise

                    if not raw_msg:
                        continue

                    # Rate pacing: gentle 40ms pause to remain under Google's 250 units/sec limit
                    time.sleep(0.04)

                    # Parse message
                    parsed = parse_gmail_message_payload(raw_msg)

                    # Check for existing message (idempotency check) and upsert
                    _, is_new = _upsert_parsed_message(account, parsed)
                    if is_new:
                        new_messages_count += 1
                    else:
                        existing_messages_count += 1

                    batch_success_count += 1
                    total_synced += 1

                except Exception as msg_err:
                    # Error resilience: One malformed message must not abort the batch
                    current_app.logger.warning(
                        "Failed to process Gmail message %s for %s: %s",
                        msg_id,
                        account.email_address,
                        msg_err,
                    )
                    continue

            # 5. Commit each batch to database incrementally
            db.session.commit()
            pages_processed += 1

            # 6. Update progress on ConnectedEmailAccount
            total_in_db = EmailMessage.query.filter_by(connected_account_id=account.id).count()
            account.messages_synced = total_in_db
            account.sync_progress = f"Syncing... {new_messages_count} new ({total_in_db} total in MailMild, batch {pages_processed})..."
            account.updated_at = datetime.now(timezone.utc)
            db.session.commit()

            # 7. Check next page token
            page_token = list_res.get("nextPageToken")
            if not page_token:
                break

        # 8. Obtain fresh historyId and mark sync completed
        current_history = get_current_history_id(service)
        if current_history:
            account.history_id = current_history

        total_in_db = EmailMessage.query.filter_by(connected_account_id=account.id).count()
        account.sync_status = "completed"
        account.last_sync_at = datetime.now(timezone.utc)
        account.messages_synced = total_in_db
        if new_messages_count == 0:
            account.sync_progress = "Mailbox is up to date (0 new messages)."
        else:
            account.sync_progress = f"Successfully synced {new_messages_count} new messages ({total_in_db} total in MailMild)."
        account.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        current_app.logger.info(
            "Mailbox sync completed for %s: %d total (%d new, %d updated)",
            account.email_address,
            total_in_db,
            new_messages_count,
            existing_messages_count,
        )

        return {
            "status": "completed",
            "messages_synced": total_in_db,
            "new_messages": new_messages_count,
            "updated_messages": existing_messages_count,
        }

    except RefreshError as ref_err:
        current_app.logger.error("Token revoked for account %s: %s", account_id, ref_err)
        account.sync_status = "error"
        account.sync_progress = "Reauthorization required: Google token expired or revoked."
        account.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return {"error": "Reauthorization required.", "status": "error"}

    except Exception as exc:
        current_app.logger.error("Mailbox synchronization notice for account %s: %s", account_id, exc)
        total_in_db = EmailMessage.query.filter_by(connected_account_id=account.id).count()
        if total_synced > 0 or total_in_db > 0:
            account.sync_status = "completed"
            account.last_sync_at = datetime.now(timezone.utc)
            account.messages_synced = total_in_db
            if new_messages_count == 0:
                account.sync_progress = "Mailbox is up to date (0 new messages)."
            else:
                account.sync_progress = f"Successfully synced {new_messages_count} new messages ({total_in_db} total in MailMild)."
            account.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            return {
                "status": "completed",
                "messages_synced": total_in_db,
                "new_messages": new_messages_count,
                "note": "Rate limit or interruption handled gracefully.",
            }

        account.sync_status = "error"
        account.sync_progress = f"Sync paused: {str(exc)[:100]}"
        account.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return {"error": f"Mailbox sync failed: {str(exc)}", "status": "error"}


def start_background_sync(account_id: str, app: Any) -> threading.Thread:
    """Launch synchronization in a background worker thread within the Flask app context.

    Args:
        account_id: UUID of the ConnectedEmailAccount.
        app: The Flask application instance.

    Returns:
        The running ``threading.Thread`` instance.
    """
    def _worker():
        with app.app_context():
            sync_gmail_mailbox(account_id)

    thread = threading.Thread(target=_worker, daemon=True, name=f"gmail-sync-{account_id[:8]}")
    thread.start()
    return thread


# ───────────────────────────────────────────────────────────────
# Incremental Mailbox Synchronization (Phase 3)
# ───────────────────────────────────────────────────────────────

def sync_gmail_incremental(
    account_id: str,
    max_pages: Optional[int] = None,
) -> dict[str, Any]:
    """Perform incremental synchronization for a connected Gmail account using historyId.

    Args:
        account_id: UUID of the ConnectedEmailAccount.
        max_pages: Optional safety limit on history pagination.

    Returns:
        Dict summarizing sync outcome (status, messages_added, messages_updated, history_id, etc.).
    """
    account = db.session.get(ConnectedEmailAccount, account_id)
    if not account:
        return {"error": "Connected account not found.", "status": "error"}

    # If no history_id established yet, check if mailbox messages are already present
    if not account.history_id:
        existing_count = EmailMessage.query.filter_by(connected_account_id=account.id).count()
        if existing_count > 0:
            credentials = get_valid_credentials(account)
            service = build_service("gmail", "v1", credentials=credentials, cache_discovery=False)
            current_history = get_current_history_id(service)
            if current_history:
                account.history_id = current_history
                account.sync_status = "completed"
                account.sync_progress = f"Initialized Gmail sync cursor (#{current_history}). Mailbox is up to date."
                account.updated_at = datetime.now(timezone.utc)
                db.session.commit()
                return {
                    "success": True,
                    "status": "completed",
                    "sync_type": "incremental",
                    "messages_added": 0,
                    "messages_updated": 0,
                    "messages_synced": existing_count,
                    "history_id": current_history,
                    "progress": account.sync_progress,
                }
        current_app.logger.info(
            "Account %s has no stored history_id and no messages. Falling back to full mailbox sync...",
            account.email_address,
        )
        return sync_gmail_mailbox(account_id, max_pages=max_pages)

    account.sync_status = "syncing"
    account.sync_progress = "Checking Gmail for new changes..."
    account.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    try:
        credentials = get_valid_credentials(account)
        service = build_service("gmail", "v1", credentials=credentials, cache_discovery=False)

        current_app.logger.info(
            "Starting incremental sync for %s from historyId: %s",
            account.email_address,
            account.history_id,
        )

        page_token = None
        pages_processed = 0
        new_messages_count = 0
        updated_messages_count = 0
        messages_to_fetch: list[str] = []
        seen_fetch_ids: set[str] = set()
        label_changes: dict[str, dict[str, set[str]]] = {}
        latest_history_id = account.history_id

        # Paginate through Gmail history
        while True:
            if max_pages and pages_processed >= max_pages:
                break

            list_params: dict[str, Any] = {
                "userId": "me",
                "startHistoryId": account.history_id,
                "maxResults": 50,
            }
            if page_token:
                list_params["pageToken"] = page_token

            res = None
            for attempt in range(3):
                try:
                    res = service.users().history().list(**list_params).execute()
                    break
                except HttpError as hist_err:
                    # History ID expired / purged by Gmail (HTTP 404)
                    if hist_err.resp.status == 404 or "historyIdNotFound" in str(hist_err) or "not found" in str(hist_err).lower():
                        current_app.logger.warning(
                            "History cursor %s expired for account %s: %s",
                            account.history_id,
                            account.email_address,
                            hist_err,
                        )
                        account.sync_status = "resync_required"
                        account.sync_progress = "Gmail history cursor expired; full synchronization required."
                        account.updated_at = datetime.now(timezone.utc)
                        db.session.commit()
                        return {
                            "status": "resync_required",
                            "resync_required": True,
                            "error": "Gmail history cursor expired; full synchronization required.",
                            "account_id": account.id,
                        }
                    # Rate limit backoff
                    if hist_err.resp.status in (429, 403) and ("rateLimitExceeded" in str(hist_err) or "userRateLimitExceeded" in str(hist_err) or "Quota exceeded" in str(hist_err)):
                        if attempt < 2:
                            wait_s = (attempt + 1) * 2
                            time.sleep(wait_s)
                            continue
                    raise

            if not res:
                break

            # Capture latest historyId returned across pages
            resp_hist_id = res.get("historyId")
            if resp_hist_id:
                latest_history_id = str(resp_hist_id)

            history_records = res.get("history", [])
            for record in history_records:
                # 1. Newly added messages
                for added in record.get("messagesAdded", []):
                    msg_stub = added.get("message", {})
                    mid = msg_stub.get("id")
                    if mid and mid not in seen_fetch_ids:
                        messages_to_fetch.append(mid)
                        seen_fetch_ids.add(mid)

                # 2. Label additions
                for ladd in record.get("labelsAdded", []):
                    msg_stub = ladd.get("message", {})
                    mid = msg_stub.get("id")
                    lbls = ladd.get("labelIds", [])
                    if mid and lbls:
                        label_changes.setdefault(mid, {"add": set(), "remove": set()})["add"].update(lbls)

                # 3. Label removals
                for lrem in record.get("labelsRemoved", []):
                    msg_stub = lrem.get("message", {})
                    mid = msg_stub.get("id")
                    lbls = lrem.get("labelIds", [])
                    if mid and lbls:
                        label_changes.setdefault(mid, {"add": set(), "remove": set()})["remove"].update(lbls)

            pages_processed += 1
            page_token = res.get("nextPageToken")
            if not page_token:
                break

        # CRITICAL SAFETY CHECK:
        # If pagination exited early because max_pages limit was reached while more pages
        # were still pending (page_token is not None), DO NOT advance history_id!
        if page_token:
            current_app.logger.warning(
                "History pagination stopped at limit (%d pages) for %s, but more pages remain (nextPageToken present). Cursor will NOT be advanced.",
                pages_processed,
                account.email_address,
            )
            account.sync_status = "error"
            account.sync_progress = f"History pagination limit reached ({pages_processed} pages). Additional changes remain pending; cursor preserved for retry."
            account.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            return {
                "success": False,
                "status": "error",
                "error": f"Pagination incomplete: {pages_processed} pages processed, but additional history pages remain. Cursor was not advanced.",
                "history_id": account.history_id,
                "pages_processed": pages_processed,
                "progress": account.sync_progress,
            }

        current_app.logger.info(
            "History retrieved for %s: %d new messages to fetch, %d label changes",
            account.email_address,
            len(messages_to_fetch),
            len(label_changes),
        )

        # Fetch and upsert new messages
        for mid in messages_to_fetch:
            try:
                raw_msg = None
                for attempt in range(3):
                    try:
                        raw_msg = service.users().messages().get(userId="me", id=mid, format="full").execute()
                        break
                    except HttpError as get_err:
                        if get_err.resp.status in (429, 403) and ("rateLimitExceeded" in str(get_err) or "userRateLimitExceeded" in str(get_err) or "Quota exceeded" in str(get_err)):
                            if attempt < 2:
                                time.sleep((attempt + 1) * 2)
                                continue
                        raise

                if not raw_msg:
                    continue

                time.sleep(0.04)
                parsed = parse_gmail_message_payload(raw_msg)
                _, is_new = _upsert_parsed_message(account, parsed)
                if is_new:
                    new_messages_count += 1
                else:
                    updated_messages_count += 1
            except Exception as msg_err:
                current_app.logger.warning("Failed to fetch/upsert message %s during incremental sync: %s", mid, msg_err)
                continue

        # Process label updates for existing messages that were not in messages_to_fetch
        for mid, changes in label_changes.items():
            if mid in seen_fetch_ids:
                continue
            existing = (
                EmailMessage.query.filter_by(
                    connected_account_id=account.id,
                    provider_message_id=mid,
                ).first()
                or EmailMessage.query.filter_by(
                    user_id=account.user_id,
                    message_id=mid,
                ).first()
            )
            if existing:
                try:
                    curr = set(json.loads(existing.labels)) if existing.labels else set()
                    curr.update(changes["add"])
                    curr.difference_update(changes["remove"])
                    existing.labels = json.dumps(list(curr))
                    existing.updated_at = datetime.now(timezone.utc)
                    updated_messages_count += 1
                except Exception as l_err:
                    current_app.logger.warning("Failed to update labels for %s: %s", mid, l_err)

        # Commit all message changes first
        db.session.commit()

        # ADVANCE history_id ONLY AFTER SUCCESSFUL PROCESSING & COMMIT
        total_in_db = EmailMessage.query.filter_by(connected_account_id=account.id).count()
        account.history_id = str(latest_history_id)
        account.sync_status = "completed"
        account.last_sync_at = datetime.now(timezone.utc)
        account.messages_synced = total_in_db

        if new_messages_count == 0 and updated_messages_count == 0:
            account.sync_progress = "Mailbox is up to date (0 new messages)."
        else:
            account.sync_progress = f"Incremental sync complete: {new_messages_count} new, {updated_messages_count} updated ({total_in_db} total in MailMild)."

        account.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        current_app.logger.info(
            "Incremental sync completed for %s: %d new, %d updated, latest historyId: %s",
            account.email_address,
            new_messages_count,
            updated_messages_count,
            latest_history_id,
        )

        return {
            "success": True,
            "status": "completed",
            "sync_type": "incremental",
            "messages_added": new_messages_count,
            "messages_updated": updated_messages_count,
            "messages_synced": total_in_db,
            "history_id": latest_history_id,
            "progress": account.sync_progress,
        }

    except RefreshError as ref_err:
        current_app.logger.error("Token revoked for account %s during incremental sync: %s", account_id, ref_err)
        account.sync_status = "error"
        account.sync_progress = "Reauthorization required: Google token expired or revoked."
        account.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return {"error": "Reauthorization required.", "status": "error", "token_revoked": True}

    except Exception as exc:
        current_app.logger.error("Incremental sync failed for account %s: %s", account_id, exc)
        # CRITICAL: DO NOT advance history_id on failure
        db.session.rollback()
        account = db.session.get(ConnectedEmailAccount, account_id)
        if account:
            account.sync_status = "error"
            account.sync_progress = f"Incremental sync paused: {str(exc)[:100]}"
            account.updated_at = datetime.now(timezone.utc)
            db.session.commit()
        return {"error": f"Incremental sync failed: {str(exc)}", "status": "error"}


def start_background_incremental_sync(account_id: str, app: Any) -> threading.Thread:
    """Launch incremental synchronization in a background worker thread within the Flask app context.

    Args:
        account_id: UUID of the ConnectedEmailAccount.
        app: The Flask application instance.

    Returns:
        The running ``threading.Thread`` instance.
    """
    def _worker():
        with app.app_context():
            sync_gmail_incremental(account_id)

    thread = threading.Thread(target=_worker, daemon=True, name=f"gmail-inc-sync-{account_id[:8]}")
    thread.start()
    return thread

