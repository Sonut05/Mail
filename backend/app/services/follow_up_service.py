"""
Follow-up service — detects conversations requiring follow-up and provides advisory recommendations.
"""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.models import EmailMessage, User, UserFeedbackSignal
from app.services.personalization_service import get_or_create_user_preferences
from app.services.thread_service import get_threads_for_user


def get_dismissed_follow_up_keys(user_id: str) -> set[str]:
    """Retrieve set of thread/email IDs where follow-up was dismissed."""
    signals = UserFeedbackSignal.query.filter_by(
        user_id=user_id,
        signal_type="dismiss_follow_up",
    ).all()
    return {s.target_value for s in signals}


def get_follow_up_recommendations(
    user_id: str,
    waiting_threads: Optional[list[dict[str, Any]]] = None,
    emails: Optional[list[EmailMessage]] = None,
    pref: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Compute follow-up recommendations based on waiting conversations and user preferences."""
    if pref is None:
        pref = get_or_create_user_preferences(user_id)
    if not pref.follow_up_detection_enabled:
        return []

    threshold_days = pref.follow_up_threshold_days or 3
    dismissed = get_dismissed_follow_up_keys(user_id)

    now = datetime.now(timezone.utc)
    threshold_date = now - timedelta(days=threshold_days)

    # 1. Threads where status is WAITING_FOR_OTHER
    if waiting_threads is None:
        thread_data = get_threads_for_user(user_id, status_filter="WAITING_FOR_OTHER", per_page=50)
        threads_to_check = thread_data.get("threads", [])
    else:
        threads_to_check = waiting_threads

    recommendations: list[dict[str, Any]] = []

    for th in threads_to_check:
        tid = th["thread_id"]
        if tid in dismissed:
            continue

        days_inactive = th.get("days_inactive", 0.0)
        if days_inactive >= float(threshold_days):
            suggested_date = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0).isoformat()
            recommendations.append({
                "type": "waiting_on_reply",
                "thread_id": tid,
                "email_id": th.get("latest_message_id"),
                "subject": th.get("subject"),
                "counterparty": th.get("participants", [{}])[0].get("name", "Participant") if th.get("participants") else "Participant",
                "last_message_at": th.get("last_message_at"),
                "days_waiting": int(days_inactive),
                "threshold_days": threshold_days,
                "suggested_follow_up_date": suggested_date,
                "reason": f"No reply received for {int(days_inactive)} days (threshold: {threshold_days} days).",
                "importance_score": th.get("highest_importance_score", 50),
            })

    # 2. Individual emails with ai_waiting_for aged past threshold
    if emails is not None:
        waiting_emails = [
            em for em in emails
            if em.ai_waiting_for and em.received_at and (
                (em.received_at if em.received_at.tzinfo else em.received_at.replace(tzinfo=timezone.utc)) <= threshold_date
            )
        ][:20]
    else:
        waiting_emails = (
            EmailMessage.query.filter(
                EmailMessage.user_id == user_id,
                EmailMessage.ai_waiting_for.isnot(None),
                EmailMessage.ai_waiting_for != "",
                EmailMessage.received_at <= threshold_date,
            )
            .order_by(EmailMessage.received_at.desc())
            .limit(20)
            .all()
        )

    seen_threads = {r["thread_id"] for r in recommendations}

    for em in waiting_emails:
        tid = em.thread_id or em.id
        if tid in seen_threads or em.id in dismissed or tid in dismissed:
            continue

        rx = em.received_at
        if rx.tzinfo is None:
            rx = rx.replace(tzinfo=timezone.utc)
        days_waiting = int((now - rx).total_seconds() / 86400.0)

        sender_name, sender_email = email.utils.parseaddr(em.from_address or "")
        counterparty = sender_name or sender_email or "Sender"

        recommendations.append({
            "type": "unresolved_waiting_item",
            "thread_id": tid,
            "email_id": em.id,
            "subject": em.subject or "(No Subject)",
            "counterparty": counterparty,
            "last_message_at": rx.isoformat(),
            "days_waiting": days_waiting,
            "threshold_days": threshold_days,
            "suggested_follow_up_date": (now + timedelta(days=1)).replace(hour=9, minute=0, second=0).isoformat(),
            "reason": f"Waiting item '{em.ai_waiting_for[:80]}' has been open for {days_waiting} days.",
            "importance_score": em.ai_importance_score or 50,
        })
        seen_threads.add(tid)

    # Sort by importance descending
    recommendations.sort(key=lambda r: r.get("importance_score", 0), reverse=True)
    return recommendations
