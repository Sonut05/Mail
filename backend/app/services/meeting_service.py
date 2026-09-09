"""
Meeting Service — Extracts meeting proposals, performs conflict detection against CalendarEvent,
and provides preview/confirmation helpers for internal calendar creation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import and_

from app.extensions import db
from app.models.calendar_event import CalendarEvent


MEETING_INDICATOR_PATTERNS = [
    re.compile(r"\b(let'?s\s+meet|schedule\s+a\s+meeting|set\s+up\s+a\s+call|catch\s+up|discuss|interview|sync)\b", re.IGNORECASE),
    re.compile(r"\b(zoom|google\s+meet|teams\s+meeting|webex)\b", re.IGNORECASE),
    re.compile(r"\b(available\s+at|how\s+about|does\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+work)\b", re.IGNORECASE),
]

MEETING_LINK_PATTERNS = [
    re.compile(r"(https?://[^\s<>\"']*(?:zoom\.us|meet\.google\.com|teams\.microsoft\.com|webex\.com)[^\s<>\"']*)", re.IGNORECASE),
]


def extract_meeting_proposal(
    subject: str | None = None,
    body_text: str | None = None,
    received_at: datetime | None = None,
    user_timezone: str = "UTC"
) -> dict[str, Any] | None:
    """Detect and extract meeting proposal metadata from email content.
    Returns None if no convincing meeting proposal is present.
    """
    text = f"{subject or ''}\n{body_text or ''}"
    if not any(pattern.search(text) for pattern in MEETING_INDICATOR_PATTERNS):
        return None

    # Find meeting url if present
    meeting_url = None
    for pattern in MEETING_LINK_PATTERNS:
        match = pattern.search(text)
        if match:
            meeting_url = match.group(1).rstrip(".,;)")
            break

    # Extract title
    title = (subject or "Discussion / Meeting").strip()
    if title.lower().startswith("re:"):
        title = title[3:].strip()
    if title.lower().startswith("fwd:"):
        title = title[4:].strip()

    # Time detection (e.g. "at 3 PM", "at 15:00", "tomorrow at 10:30 am")
    time_match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text, re.IGNORECASE)
    hour = 10
    minute = 0
    if time_match:
        h = int(time_match.group(1))
        m = int(time_match.group(2)) if time_match.group(2) else 0
        meridiem = (time_match.group(3) or "").lower()
        if meridiem == "pm" and h < 12:
            h += 12
        elif meridiem == "am" and h == 12:
            h = 0
        hour = h
        minute = m

    # Explicit date detection (YYYY-MM-DD or Month Day)
    explicit_date_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    ref_date = received_at or datetime.now(timezone.utc)
    target_date = None

    if explicit_date_match:
        try:
            target_date = datetime(
                int(explicit_date_match.group(1)),
                int(explicit_date_match.group(2)),
                int(explicit_date_match.group(3)),
            ).date()
        except ValueError:
            target_date = None

    if not target_date:
        month_match = re.search(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", text, re.IGNORECASE)
        if month_match:
            from app.services.deadline_service import MONTH_MAP
            m = MONTH_MAP.get(month_match.group(1).lower(), 1)
            d = int(month_match.group(2))
            y = int(month_match.group(3)) if month_match.group(3) else ref_date.year
            try:
                target_date = datetime(y, m, d).date()
            except ValueError:
                target_date = None

    if not target_date:
        target_date = ref_date.date()
        if re.search(r"\btomorrow\b", text, re.IGNORECASE):
            target_date = target_date + timedelta(days=1)
        elif re.search(r"\bnext\s+monday\b", text, re.IGNORECASE):
            days_ahead = (0 - target_date.weekday() + 7) % 7 or 7
            target_date = target_date + timedelta(days=days_ahead)
        elif re.search(r"\bthis\s+friday\b", text, re.IGNORECASE):
            days_ahead = (4 - target_date.weekday() + 7) % 7 or 7
            target_date = target_date + timedelta(days=days_ahead)

    # Duration detection (e.g. "for 60 minutes", "for 1 hour", "for 30 mins")
    duration_minutes = 45
    dur_match = re.search(r"\bfor\s+(\d{1,3})\s*(min|minute|minutes|hour|hours|hr|hrs)\b", text, re.IGNORECASE)
    if dur_match:
        num = int(dur_match.group(1))
        unit = dur_match.group(2).lower()
        if "hour" in unit or "hr" in unit:
            duration_minutes = num * 60
        else:
            duration_minutes = num

    start_dt = datetime(
        target_date.year, target_date.month, target_date.day,
        hour, minute, 0, tzinfo=timezone.utc
    )
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    return {
        "title": title[:200],
        "date": target_date.isoformat(),
        "start_time": start_dt.strftime("%H:%M:%S"),
        "end_time": end_dt.strftime("%H:%M:%S"),
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat(),
        "duration_minutes": duration_minutes,
        "timezone": user_timezone,
        "meeting_url": meeting_url,
        "confidence": 0.88 if meeting_url else 0.75,
    }


def check_meeting_conflict(
    user_id: str,
    start_dt: datetime | str,
    end_dt: datetime | str | None = None,
    exclude_id: str | None = None,
    duration_minutes: int | None = None,
) -> dict[str, Any]:
    """Check whether a proposed meeting conflicts with existing internal CalendarEvents.
    Uses canonical overlap condition:
        new_start < existing_end AND new_end > existing_start
    Returns:
        {
            "status": "CONFLICT" | "POSSIBLE_CONFLICT" | "NO_CONFLICT",
            "conflicting_events": [ ... ]
        }
    """
    if isinstance(start_dt, str):
        try:
            start_dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
        except Exception:
            return {"status": "POSSIBLE_CONFLICT", "conflicting_events": []}

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)

    if end_dt is None:
        if duration_minutes:
            end_dt = start_dt + timedelta(minutes=duration_minutes)
        else:
            end_dt = start_dt + timedelta(hours=1)
    elif isinstance(end_dt, str):
        try:
            end_dt = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))
        except Exception:
            end_dt = start_dt + timedelta(hours=1)

    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    query = CalendarEvent.query.filter(CalendarEvent.user_id == user_id)
    if exclude_id:
        query = query.filter(CalendarEvent.id != exclude_id)

    candidates = query.all()
    conflicting = []

    for ev in candidates:
        ev_start = ev.start_date_time
        if ev_start.tzinfo is None:
            ev_start = ev_start.replace(tzinfo=timezone.utc)

        ev_end = ev.end_date_time or (ev_start + timedelta(hours=1))
        if ev_end.tzinfo is None:
            ev_end = ev_end.replace(tzinfo=timezone.utc)

        # Canonical overlap condition:
        # new_start < existing_end AND new_end > existing_start
        if start_dt < ev_end and end_dt > ev_start:
            conflicting.append(ev.to_dict())

    status = "CONFLICT" if conflicting else "NO_CONFLICT"
    return {
        "status": status,
        "has_conflict": bool(conflicting),
        "conflicts": conflicting,
        "conflicting_events": conflicting,
    }


def confirm_and_create_calendar_event(
    user_id: str,
    event_data: dict[str, Any],
    email_id: str | None = None,
    confirmed: bool = True,
) -> CalendarEvent:
    """Creates an internal CalendarEvent only upon explicit user confirmation.
    NEVER interacts with external Google Calendar (read-only scope invariant).
    """
    if not confirmed:
        raise ValueError("User confirmation required to create calendar event.")

    title = str(event_data.get("title") or "Meeting").strip()
    start_str = (
        event_data.get("start_datetime")
        or event_data.get("start_date_time")
        or event_data.get("start")
        or (f"{event_data.get('date')}T{event_data.get('start_time')}" if event_data.get("date") and event_data.get("start_time") else event_data.get("start_time"))
    )
    if not start_str:
        raise ValueError("Start date/time is required to create a calendar event.")

    start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)

    end_str = (
        event_data.get("end_datetime")
        or event_data.get("end_date_time")
        or event_data.get("end")
        or (f"{event_data.get('date')}T{event_data.get('end_time')}" if event_data.get("date") and event_data.get("end_time") else event_data.get("end_time"))
    )
    end_dt = None
    if end_str:
        end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    else:
        end_dt = start_dt + timedelta(hours=1)

    event = CalendarEvent(
        user_id=user_id,
        email_id=email_id,
        title=title[:500],
        description=event_data.get("description"),
        start_date_time=start_dt,
        end_date_time=end_dt,
        timezone=event_data.get("timezone") or "UTC",
        location=event_data.get("location"),
        meeting_link=event_data.get("meeting_link") or event_data.get("meeting_url"),
    )
    db.session.add(event)
    db.session.commit()
    return event
