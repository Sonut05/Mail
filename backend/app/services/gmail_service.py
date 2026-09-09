"""
Gmail API service helpers.

Provides functions to build a Gmail API client, fetch / list emails,
and send reply messages using the authenticated user's access token.
"""

from __future__ import annotations

import base64
import email as email_lib
from email.mime.text import MIMEText
from datetime import datetime, timezone
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


GMAIL_API_VERSION = "v1"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_gmail_service(access_token: str) -> Any:
    """Build an authenticated Gmail API service object.

    Args:
        access_token: A valid OAuth2 access token for Gmail.

    Returns:
        A googleapiclient Resource for the Gmail API.
    """
    credentials = Credentials(token=access_token)
    service = build("gmail", GMAIL_API_VERSION, credentials=credentials, cache_discovery=False)
    return service


def list_recent_emails(service: Any, max_results: int = 20) -> list[dict]:
    """List recent message stubs from the user's inbox.

    Args:
        service: An authenticated Gmail API service resource.
        max_results: Maximum number of message stubs to return.

    Returns:
        A list of dicts with keys ``id`` and ``threadId``.
    """
    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], maxResults=max_results)
        .execute()
    )
    return results.get("messages", [])


def fetch_email(service: Any, message_id: str) -> dict:
    """Fetch and parse a single email message.

    Args:
        service: An authenticated Gmail API service resource.
        message_id: The Gmail message ID.

    Returns:
        A dict with keys: message_id, thread_id, subject, body_text,
        from_address, to_address, received_at.
    """
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject = headers.get("subject", "(no subject)")
    from_address = headers.get("from", "")
    to_address = headers.get("to", "")
    date_str = headers.get("date", "")

    # Parse received date
    received_at = None
    if date_str:
        try:
            received_at = email_lib.utils.parsedate_to_datetime(date_str)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = datetime.now(timezone.utc)

    # Extract body text
    body_text = _extract_body(msg.get("payload", {}))

    return {
        "message_id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": subject,
        "body_text": body_text,
        "from_address": from_address,
        "to_address": to_address,
        "received_at": received_at,
    }


def send_reply(
    service: Any,
    to: str,
    subject: str,
    body: str,
    thread_id: str,
    message_id: str,
) -> str:
    """Send a reply email within an existing thread.

    Args:
        service: Authenticated Gmail API service.
        to: Recipient email address.
        subject: Email subject (usually prefixed with "Re:").
        body: Plain-text reply body.
        thread_id: Gmail thread ID to keep the reply threaded.
        message_id: The original message ID for the In-Reply-To header.

    Returns:
        The sent message's Gmail ID.
    """
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    message["In-Reply-To"] = message_id
    message["References"] = message_id

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": thread_id})
        .execute()
    )
    return sent["id"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload.

    Args:
        payload: The ``payload`` dict from a Gmail message resource.

    Returns:
        The decoded plain-text body, or an empty string.
    """
    mime_type = payload.get("mimeType", "")

    # Simple single-part message
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Multipart — recurse into parts
    parts = payload.get("parts", [])
    for part in parts:
        # Prefer text/plain
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Fallback: try text/html
    for part in parts:
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Nested multipart
    for part in parts:
        nested = _extract_body(part)
        if nested:
            return nested

    return ""
