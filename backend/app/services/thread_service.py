"""
Thread service — conversation aggregation, status calculation, and stale detection.
"""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import func, or_, and_
from sqlalchemy.orm import defer

from app.extensions import db
from app.models import EmailMessage, User


def _clean_subject(subject: Optional[str]) -> str:
    """Normalize email subjects by stripping Re:, Fwd:, etc."""
    if not subject:
        return "(No Subject)"
    sub = subject.strip()
    while True:
        lower = sub.lower()
        if lower.startswith("re:") or lower.startswith("fwd:") or lower.startswith("fw:"):
            sub = sub.split(":", 1)[1].strip()
        else:
            break
    return sub or "(No Subject)"


def _extract_participant(raw_addr: Optional[str]) -> Optional[dict[str, str]]:
    """Parse name and email address cleanly."""
    if not raw_addr:
        return None
    name, addr = email.utils.parseaddr(raw_addr)
    clean_addr = addr.lower().strip() if addr else raw_addr.lower().strip()
    if not clean_addr:
        return None
    return {
        "name": name.strip() or clean_addr,
        "email": clean_addr,
    }


def aggregate_thread(messages: list[EmailMessage], current_user_email: str = "") -> dict[str, Any]:
    """Aggregate a sequence of EmailMessages belonging to the same conversation.

    Messages should be sorted by received_at ascending.
    """
    if not messages:
        return {}

    sorted_msgs = sorted(
        messages,
        key=lambda m: (m.received_at or datetime.min.replace(tzinfo=timezone.utc)),
    )

    first_msg = sorted_msgs[0]
    last_msg = sorted_msgs[-1]
    thread_id = first_msg.thread_id or first_msg.id

    # Participants
    participants_map: dict[str, dict[str, str]] = {}
    for m in sorted_msgs:
        for addr_str in (m.from_address, m.to_address):
            p = _extract_participant(addr_str)
            if p and p["email"] not in participants_map:
                participants_map[p["email"]] = p

    participants = list(participants_map.values())

    # Latest sender
    latest_p = _extract_participant(last_msg.from_address)
    latest_sender = latest_p["email"] if latest_p else (last_msg.from_address or "Unknown")

    now = datetime.now(timezone.utc)
    last_dt = last_msg.received_at
    if last_dt and last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    days_since_last = (now - last_dt).total_seconds() / 86400.0 if last_dt else 0.0

    # Actions and deadlines
    requires_action = any(bool(m.ai_action_required) for m in sorted_msgs)
    waiting_for_items = [m.ai_waiting_for for m in sorted_msgs if m.ai_waiting_for]
    
    deadlines = [m.ai_deadline for m in sorted_msgs if m.ai_deadline]
    earliest_deadline = min(deadlines).isoformat() if deadlines else None

    # Importance
    importance_scores = [m.ai_importance_score for m in sorted_msgs if m.ai_importance_score is not None]
    highest_importance = max(importance_scores) if importance_scores else 50

    # Determine status & explainable reason
    is_last_from_me = False
    if current_user_email and latest_p:
        is_last_from_me = (latest_p["email"].lower() == current_user_email.lower())

    status = "ACTIVE"
    status_reason = "Recent activity in conversation"

    if days_since_last >= 7.0 and requires_action:
        status = "STALE"
        status_reason = f"No activity for {int(days_since_last)} days with unresolved action item"
    elif is_last_from_me:
        status = "WAITING_FOR_OTHER"
        status_reason = "You sent the last message; waiting for participant reply"
    elif last_msg.ai_action_required:
        status = "WAITING_FOR_USER"
        status_reason = "Latest message requires your action or response"
    elif waiting_for_items:
        status = "WAITING_FOR_OTHER"
        status_reason = "Open follow-up or waiting item in conversation"
    elif days_since_last > 14.0:
        status = "RESOLVED"
        status_reason = "No open actions and conversation is dormant"
    else:
        status = "ACTIVE"
        status_reason = "Active conversation within normal response window"

    return {
        "thread_id": thread_id,
        "subject": _clean_subject(first_msg.subject or last_msg.subject),
        "message_count": len(sorted_msgs),
        "participants": participants,
        "first_message_at": first_msg.received_at.isoformat() if first_msg.received_at else None,
        "last_message_at": last_msg.received_at.isoformat() if last_msg.received_at else None,
        "days_inactive": round(days_since_last, 1),
        "latest_sender": latest_sender,
        "requires_action": requires_action,
        "waiting_for_reply": bool(waiting_for_items) or (status == "WAITING_FOR_OTHER"),
        "highest_importance_score": highest_importance,
        "thread_summary": last_msg.ai_summary or first_msg.ai_summary or last_msg.summary or "",
        "status": status,
        "status_reason": status_reason,
        "earliest_deadline": earliest_deadline,
        "latest_message_id": last_msg.id,
    }


def get_threads_for_user(
    user_id: str,
    status_filter: Optional[str] = None,
    query_str: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    all_msgs: Optional[list[EmailMessage]] = None,
    user_email: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve grouped and paginated conversation threads for the user."""
    if user_email is None:
        user = db.session.get(User, user_id)
        user_email = user.email if user else ""

    if all_msgs is None:
        # Fetch messages for user
        q = EmailMessage.query.filter_by(user_id=user_id).options(
            defer(EmailMessage.body_text), defer(EmailMessage.body_html)
        )
        if query_str:
            term = f"%{query_str}%"
            q = q.filter(or_(EmailMessage.subject.ilike(term), EmailMessage.from_address.ilike(term)))

        # Order by received_at desc so we group recent ones first
        all_msgs = q.order_by(EmailMessage.received_at.desc()).all()

    # Group by thread_id (fallback to id if null)
    threads_dict: dict[str, list[EmailMessage]] = {}
    for msg in all_msgs:
        tid = msg.thread_id or msg.id
        if tid not in threads_dict:
            threads_dict[tid] = []
        threads_dict[tid].append(msg)

    # Aggregate each thread
    aggregated_threads: list[dict[str, Any]] = []
    for tid, msgs in threads_dict.items():
        thread_data = aggregate_thread(msgs, current_user_email=user_email)
        if status_filter:
            if thread_data.get("status", "").upper() != status_filter.upper():
                continue
        aggregated_threads.append(thread_data)

    # Sort by last_message_at desc
    aggregated_threads.sort(
        key=lambda t: t.get("last_message_at") or "",
        reverse=True,
    )

    # Pagination in memory over grouped threads
    total = len(aggregated_threads)
    start = (page - 1) * per_page
    end = start + per_page
    items = aggregated_threads[start:end]

    return {
        "threads": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_next": end < total,
    }


def get_thread_detail(user_id: str, thread_id: str) -> Optional[dict[str, Any]]:
    """Retrieve full chronological conversation thread with individual messages."""
    user = db.session.get(User, user_id)
    user_email = user.email if user else ""

    # Look up by thread_id, or if none match, by email_message.id
    msgs = (
        EmailMessage.query.filter(
            EmailMessage.user_id == user_id,
            or_(EmailMessage.thread_id == thread_id, EmailMessage.id == thread_id),
        )
        .order_by(EmailMessage.received_at.asc())
        .all()
    )

    if not msgs:
        return None

    summary = aggregate_thread(msgs, current_user_email=user_email)
    summary["messages"] = [m.to_dict() for m in msgs]

    from app.services.deadline_service import detect_thread_deadline_changes
    deadline_change = detect_thread_deadline_changes(msgs)
    summary["deadline_change"] = deadline_change

    return summary


def get_stale_threads(user_id: str, days_threshold: int = 7) -> list[dict[str, Any]]:
    """Find stale conversations with unresolved actions."""
    res = get_threads_for_user(user_id, status_filter="STALE", per_page=50)
    return res.get("threads", [])
