"""
Digest Service — Generates daily personal productivity briefings.
Operates deterministically from existing structured database entities.
Does NOT fail if Gemini is disabled.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import and_, or_

from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.services.follow_up_service import get_follow_up_recommendations
from app.services.thread_service import get_stale_threads
from app.services.contact_service import get_all_contacts_for_user


def generate_daily_digest(user_id: str, target_date: datetime | None = None, user_timezone: str = "UTC") -> dict[str, Any]:
    """Generate daily AI digest purely from structured DB state.
    Provides complete morning briefing without requiring Gemini calls.
    """
    ref_dt = target_date or datetime.now(timezone.utc)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=timezone.utc)

    # 1. Important emails today
    day_start = datetime(ref_dt.year, ref_dt.month, ref_dt.day, 0, 0, 0, tzinfo=timezone.utc)
    important_emails = EmailMessage.query.filter(
        EmailMessage.user_id == user_id,
        or_(
            EmailMessage.ai_priority.in_(["high", "urgent"]),
            EmailMessage.ai_importance_score >= 70
        )
    ).order_by(EmailMessage.ai_importance_score.desc().nullslast()).limit(5).all()

    # 2. Needs action
    action_emails = EmailMessage.query.filter(
        EmailMessage.user_id == user_id,
        EmailMessage.ai_action_required == True
    ).order_by(EmailMessage.received_at.desc()).limit(6).all()

    # 3. Deadlines approaching (within 48 hours)
    upcoming_limit = ref_dt + timedelta(hours=48)
    deadlines = EmailMessage.query.filter(
        EmailMessage.user_id == user_id,
        EmailMessage.ai_deadline.isnot(None),
        EmailMessage.ai_deadline >= ref_dt - timedelta(hours=12),
        EmailMessage.ai_deadline <= upcoming_limit
    ).order_by(EmailMessage.ai_deadline.asc()).limit(5).all()

    # 4. Follow-up recommendations
    follow_ups = get_follow_up_recommendations(user_id)

    # 5. Waiting for replies
    waiting_for_items = []
    for em in action_emails:
        if em.ai_waiting_for:
            try:
                import json
                wf = json.loads(em.ai_waiting_for)
                if wf and wf.get("person"):
                    waiting_for_items.append({
                        "email_id": em.id,
                        "subject": em.subject,
                        "person": wf.get("person"),
                        "for_what": wf.get("for_what"),
                        "suggested_followup": wf.get("suggested_followup"),
                    })
            except Exception:
                pass

    # 6. Today's meetings
    day_end = day_start + timedelta(days=1)
    meetings = CalendarEvent.query.filter(
        CalendarEvent.user_id == user_id,
        CalendarEvent.start_date_time >= day_start,
        CalendarEvent.start_date_time < day_end
    ).order_by(CalendarEvent.start_date_time.asc()).all()

    # 7. Stale conversations
    stale = get_stale_threads(user_id)

    # 8. Important people (top 5 contacts by frequency/recency)
    contacts = get_all_contacts_for_user(user_id)
    sorted_contacts = sorted(
        contacts,
        key=lambda c: (c.get("open_actions_count", 0) * 10 + c.get("message_count", 0)),
        reverse=True
    )[:5]

    important_list = [
        {
            "id": m.id,
            "subject": m.subject,
            "sender": m.from_address,
            "priority": m.ai_priority,
            "importance_score": m.ai_importance_score,
            "summary": m.ai_summary or m.summary,
        }
        for m in important_emails
    ]

    summary_dict = {
        "urgent_count": len(important_emails),
        "important_count": len(important_emails),
        "action_count": len(action_emails),
        "deadlines_count": len(deadlines),
        "follow_ups_count": len(follow_ups),
        "meetings_count": len(meetings),
        "stale_count": len(stale),
    }

    return {
        "user_id": user_id,
        "date": ref_dt.strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary_dict,
        "summary_counts": summary_dict,
        "urgent_emails": important_list,
        "important": important_list,
        "needs_action": [
            {
                "id": m.id,
                "subject": m.subject,
                "sender": m.from_address,
                "next_action": m.ai_next_action,
                "deadline": m.ai_deadline.isoformat() if m.ai_deadline else None,
            }
            for m in action_emails
        ],
        "deadlines": [
            {
                "id": m.id,
                "subject": m.subject,
                "deadline": m.ai_deadline.isoformat() if m.ai_deadline else None,
                "priority": m.ai_priority,
            }
            for m in deadlines
        ],
        "follow_ups": follow_ups[:5],
        "waiting_for": waiting_for_items[:5],
        "meetings": [
            {
                "id": ev.id,
                "title": ev.title,
                "start": ev.start_date_time.isoformat() if ev.start_date_time else None,
                "end": ev.end_date_time.isoformat() if ev.end_date_time else None,
                "location": ev.location,
                "meeting_link": ev.meeting_link,
            }
            for ev in meetings
        ],
        "stale": stale[:5],
        "people": [
            {
                "email": c.get("email"),
                "name": c.get("name"),
                "message_count": c.get("message_count", 0),
                "action_count": c.get("open_actions_count", 0),
            }
            for c in sorted_contacts
        ],
    }
