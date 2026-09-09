"""
Relationship Service — Observable relationship scoring, response-time intelligence,
relationship health states, and privacy safeguards.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone, timedelta
from typing import Any

from app.models.email_message import EmailMessage
from app.services.contact_service import get_all_contacts_for_user


def compute_relationship_score(
    interaction_frequency: int,
    recency_days: float,
    response_rate: float,
    thread_count: int,
    open_actions: int,
    avg_importance: float
) -> tuple[int, list[str]]:
    """Compute transparent relationship score bounded in [0, 100].
    Strictly uses observable email statistics.
    Never infers psychological or personal attributes.
    """
    reasons = []
    score = 0.0

    # Interaction volume (max 30 pts)
    if interaction_frequency >= 20:
        score += 30
        reasons.append("High interaction volume (20+ exchanges)")
    elif interaction_frequency >= 8:
        score += 20
        reasons.append("Frequent communication (8+ exchanges)")
    elif interaction_frequency >= 3:
        score += 10
        reasons.append("Regular contact (3+ exchanges)")
    else:
        score += 5

    # Recency (max 25 pts)
    if recency_days <= 2:
        score += 25
        reasons.append("Active interaction within last 48 hours")
    elif recency_days <= 7:
        score += 18
        reasons.append("Recent interaction within past week")
    elif recency_days <= 30:
        score += 10
        reasons.append("Contacted within past month")
    else:
        score += 2

    # Thread breadth (max 15 pts)
    if thread_count >= 5:
        score += 15
        reasons.append("Spans multiple distinct conversation threads (5+)")
    elif thread_count >= 2:
        score += 10
    else:
        score += 5

    # Action items & importance (max 20 pts)
    if open_actions > 0:
        score += 10
        reasons.append(f"{open_actions} pending action item(s) associated")
    if avg_importance >= 70:
        score += 10
        reasons.append("Consistently high email priority/importance")
    elif avg_importance >= 40:
        score += 5

    # Response rate bonus (max 10 pts)
    if response_rate >= 0.7:
        score += 10
        reasons.append("High bidirectional response rate")

    final_score = max(0, min(100, int(round(score))))
    return final_score, reasons


def calculate_response_time_stats(
    user_id: str,
    contact_email: str
) -> dict[str, Any]:
    """Calculate response time intelligence for a contact.
    If response_count < 3, returns 'Insufficient history' rather than misleading conclusions.
    """
    # Fetch all messages in threads involving contact and user
    emails = EmailMessage.query.filter(
        EmailMessage.user_id == user_id,
        (EmailMessage.from_address.ilike(f"%{contact_email}%")) | (EmailMessage.to_address.ilike(f"%{contact_email}%"))
    ).order_by(EmailMessage.received_at.asc()).all()

    # Group by thread_id
    threads_map = {}
    for em in emails:
        th_id = em.thread_id or em.id
        threads_map.setdefault(th_id, []).append(em)

    turnaround_hours: list[float] = []

    for th_id, msgs in threads_map.items():
        if len(msgs) < 2:
            continue
        for i in range(len(msgs) - 1):
            m1 = msgs[i]
            m2 = msgs[i + 1]
            if not m1.received_at or not m2.received_at:
                continue

            # Check if direction reversed (one from contact, next from someone else or user)
            m1_from = (m1.from_address or "").lower()
            m2_from = (m2.from_address or "").lower()
            contact_lower = contact_email.lower()

            if (contact_lower in m1_from and contact_lower not in m2_from) or \
               (contact_lower not in m1_from and contact_lower in m2_from):
                diff_sec = (m2.received_at - m1.received_at).total_seconds()
                if 0 < diff_sec <= (14 * 86400):  # Cap at 14 days for realistic turnarounds
                    turnaround_hours.append(diff_sec / 3600.0)

    count = len(turnaround_hours)
    if count < 3:
        return {
            "response_count": count,
            "status": "Insufficient history",
            "message": "Insufficient history (< 3 response samples)",
            "average_hours": None,
            "median_hours": None,
            "last_hours": None,
        }

    avg_h = round(statistics.mean(turnaround_hours), 1)
    med_h = round(statistics.median(turnaround_hours), 1)
    last_h = round(turnaround_hours[-1], 1)

    return {
        "response_count": count,
        "status": "Adequate history",
        "average_hours": avg_h,
        "median_hours": med_h,
        "last_hours": last_h,
    }


def determine_relationship_health(
    interaction_count: int,
    recency_days: float,
    open_actions: int,
    is_waiting_for_them: bool
) -> str:
    """Determine relationship health state based on observable activity:
    ACTIVE, ENGAGED, DORMANT, WAITING, NEEDS_ATTENTION.
    """
    if open_actions > 0:
        return "NEEDS_ATTENTION"
    if is_waiting_for_them:
        return "WAITING"
    if recency_days <= 5 and interaction_count >= 5:
        return "ENGAGED"
    if recency_days <= 14:
        return "ACTIVE"
    return "DORMANT"


def get_relationship_profile(user_id: str, contact_email: str) -> dict[str, Any]:
    """Get complete relationship intelligence profile for a contact."""
    clean_target = contact_email.lower().strip()
    contacts = get_all_contacts_for_user(user_id)
    c_data = next((c for c in contacts if (c.get("email") or "").lower().strip() == clean_target), None)
    if not c_data:
        return {
            "email": contact_email,
            "score": 0,
            "reasons": ["No observable email history"],
            "health": "DORMANT",
            "response_time": {
                "response_count": 0,
                "status": "Insufficient history",
            }
        }

    now = datetime.now(timezone.utc)
    recency_days = 999.0
    if c_data.get("last_contact"):
        try:
            last_dt = datetime.fromisoformat(c_data["last_contact"])
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            recency_days = max(0.0, (now - last_dt).total_seconds() / 86400.0)
        except Exception:
            pass

    score, reasons = compute_relationship_score(
        interaction_frequency=c_data.get("message_count", 1),
        recency_days=recency_days,
        response_rate=0.8 if c_data.get("sent_count", 0) > 0 else 0.4,
        thread_count=len(c_data.get("recent_topics", [1])),
        open_actions=c_data.get("open_actions_count", 0),
        avg_importance=float(c_data.get("importance_score", 50.0)),
    )

    rt_stats = calculate_response_time_stats(user_id, contact_email)
    health = determine_relationship_health(
        interaction_count=c_data.get("message_count", 1),
        recency_days=recency_days,
        open_actions=c_data.get("open_actions_count", 0),
        is_waiting_for_them=False
    )

    return {
        "email": contact_email,
        "name": c_data.get("name") or contact_email.split("@")[0],
        "score": score,
        "reasons": reasons,
        "health": health,
        "response_time": rt_stats,
        "message_count": c_data.get("message_count", 0),
        "sent_count": c_data.get("sent_count", 0),
        "received_count": c_data.get("received_count", 0),
        "open_actions": c_data.get("open_actions_count", 0),
    }
