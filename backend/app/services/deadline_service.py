"""
Deadline Service — Hybrid deterministic & AI deadline parsing, timezone awareness,
multiple deadline extraction, and thread-level deadline change detection.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo


MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Regex for dates like "Sep 15", "September 15, 2026", "15/09/2026", "2026-09-15"
DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),  # YYYY-MM-DD
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),  # DD/MM/YYYY
    re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.IGNORECASE),
]

TIME_PATTERNS = [
    re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2}):(\d{2})\b"),
    re.compile(r"\b(eod|cob)\b", re.IGNORECASE),
]
WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6
}

RELATIVE_DATE_PATTERNS = [
    (re.compile(r"\btomorrow\b", re.IGNORECASE), lambda ref, m: ref.date() + timedelta(days=1)),
    (re.compile(r"\b(?:this\s+|next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE), lambda ref, m: ref.date() + timedelta(days=(WEEKDAY_MAP[m.group(1).lower()] - ref.weekday() + 7) % 7 or 7)),
    (re.compile(r"\bwithin\s+48\s+hours\b", re.IGNORECASE), lambda ref, m: (ref + timedelta(hours=48)).date()),
    (re.compile(r"\b(?:by\s+)?end\s+of\s+week\b", re.IGNORECASE), lambda ref, m: ref.date() + timedelta(days=(4 - ref.weekday() + 7) % 7 or 7)),
]

DEADLINE_LABEL_PATTERNS = [
    re.compile(r"(?:due|deadline|submit|send|review|complete|approve|pay|confirm|finish|signoff)\s+([^\n.,;:]{3,50})", re.IGNORECASE),
]

AMBIGUOUS_PATTERNS = [
    (re.compile(r"\b(?:asap|as\s+soon\s+as\s+possible)\b", re.IGNORECASE), "ASAP (Unscheduled)"),
    (re.compile(r"\bsometime\s+early\s+next\s+week\b", re.IGNORECASE), "Early Next Week (Unscheduled)"),
    (re.compile(r"\blater\s+this\s+month\b", re.IGNORECASE), "Later This Month (Unscheduled)"),
    (re.compile(r"\bbefore\s+the\s+end\s+of\s+(?:the\s+)?quarter\b", re.IGNORECASE), "End of Quarter (Unscheduled)"),
]


def _get_user_tz(user_timezone: str | None) -> ZoneInfo:
    """Safely get ZoneInfo or fallback to UTC."""
    if not user_timezone:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(user_timezone)
    except Exception:
        return ZoneInfo("UTC")


def extract_deadlines_from_text(
    text: str | None,
    reference_dt: datetime | None = None,
    user_timezone: str = "UTC"
) -> list[dict[str, Any]]:
    """Hybrid deterministic & rule-based deadline extraction."""
    if not text:
        return []

    tz = _get_user_tz(user_timezone)
    ref = reference_dt or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    ref_local = ref.astimezone(tz)

    deadlines: list[dict[str, Any]] = []
    seen_datetimes = set()

    # Determine default time if EOD/COB mentioned
    hour = 17
    minute = 0
    time_match = None
    for tp in TIME_PATTERNS:
        m = tp.search(text)
        if m:
            time_match = m
            break

    if time_match:
        raw_val = time_match.group(0).lower()
        if "eod" in raw_val or "cob" in raw_val:
            hour = 17
            minute = 0
        elif len(time_match.groups()) >= 3 and time_match.group(3):
            h = int(time_match.group(1))
            min_val = int(time_match.group(2)) if time_match.group(2) else 0
            meridiem = time_match.group(3).lower()
            if meridiem == "pm" and h < 12:
                h += 12
            elif meridiem == "am" and h == 12:
                h = 0
            hour, minute = h, min_val
        elif len(time_match.groups()) >= 2 and time_match.group(2):
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))

    # 1. Check relative date expressions
    for pattern, calc_fn in RELATIVE_DATE_PATTERNS:
        for match in pattern.finditer(text):
            calc_date = calc_fn(ref_local, match)
            deadline_dt = datetime(
                calc_date.year, calc_date.month, calc_date.day,
                hour, minute, 0, tzinfo=tz
            ).astimezone(timezone.utc)

            iso = deadline_dt.isoformat()
            if iso not in seen_datetimes:
                seen_datetimes.add(iso)
                snippet = match.group(0)
                deadlines.append({
                    "label": f"Due {snippet}",
                    "datetime": iso,
                    "deadline": iso,
                    "confidence": 0.88,
                    "source_text": snippet,
                    "status": "OPEN",
                })

    # 2. Check absolute date expressions
    # YYYY-MM-DD
    for match in DATE_PATTERNS[0].finditer(text):
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            dt = datetime(y, m, d, hour, minute, 0, tzinfo=tz).astimezone(timezone.utc)
            iso = dt.isoformat()
            if iso not in seen_datetimes:
                seen_datetimes.add(iso)
                deadlines.append({
                    "label": f"Due {match.group(0)}",
                    "datetime": iso,
                    "deadline": iso,
                    "confidence": 0.95,
                    "source_text": match.group(0),
                    "status": "OPEN",
                })
        except ValueError:
            continue

    # DD/MM/YYYY
    for match in DATE_PATTERNS[1].finditer(text):
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            dt = datetime(y, m, d, hour, minute, 0, tzinfo=tz).astimezone(timezone.utc)
            iso = dt.isoformat()
            if iso not in seen_datetimes:
                seen_datetimes.add(iso)
                deadlines.append({
                    "label": f"Due {match.group(0)}",
                    "datetime": iso,
                    "deadline": iso,
                    "confidence": 0.90,
                    "source_text": match.group(0),
                    "status": "OPEN",
                })
        except ValueError:
            continue

    # Month Day, Year
    for match in DATE_PATTERNS[2].finditer(text):
        month_name = match.group(1).lower()
        m = MONTH_MAP.get(month_name)
        d = int(match.group(2))
        y = int(match.group(3)) if match.group(3) else ref_local.year
        if m:
            try:
                dt = datetime(y, m, d, hour, minute, 0, tzinfo=tz).astimezone(timezone.utc)
                # If date without year is in past, advance to next year
                if not match.group(3) and dt < ref:
                    dt = datetime(y + 1, m, d, hour, minute, 0, tzinfo=tz).astimezone(timezone.utc)
                iso = dt.isoformat()
                if iso not in seen_datetimes:
                    seen_datetimes.add(iso)
                    deadlines.append({
                        "label": f"Due {match.group(0)}",
                        "datetime": iso,
                        "deadline": iso,
                        "confidence": 0.92,
                        "source_text": match.group(0),
                        "status": "OPEN",
                    })
            except ValueError:
                continue

    # 3. Ambiguous semantic expressions without concrete dates (insufficient confidence to invent a date)
    for pattern, desc in AMBIGUOUS_PATTERNS:
        for match in pattern.finditer(text):
            deadlines.append({
                "label": desc,
                "datetime": None,
                "deadline": None,
                "is_ambiguous": True,
                "confidence": 0.40,
                "source_text": match.group(0),
                "status": "UNSCHEDULED",
            })

    # Try to refine labels if a specific verb is found
    for match in DEADLINE_LABEL_PATTERNS[0].finditer(text):
        clean_label = match.group(1).strip()
        if clean_label and deadlines:
            deadlines[0]["label"] = clean_label.capitalize()
            break

    return deadlines


def detect_thread_deadline_changes(
    thread_input: str | list[Any],
    user_id: str | None = None
) -> Any:
    """Compare deadlines chronologically across messages in the same thread.
    Accepts either a thread_id string + optional user_id, or a list of message objects.
    Detects if a later email changed the earlier deadline.
    Does NOT modify user tasks or calendar.
    """
    is_id_call = isinstance(thread_input, str)
    if is_id_call:
        from app.models.email_message import EmailMessage
        q = EmailMessage.query.filter_by(thread_id=thread_input)
        if user_id:
            q = q.filter_by(user_id=user_id)
        thread_messages = q.order_by(EmailMessage.received_at.asc()).all()
    else:
        thread_messages = thread_input or []

    if len(thread_messages) < 2:
        return [] if is_id_call else None

    # Sort chronological by received_at
    sorted_msgs = sorted(thread_messages, key=lambda m: m.received_at or datetime.min.replace(tzinfo=timezone.utc))

    import json
    timeline_deadlines = []
    for m in sorted_msgs:
        dl = getattr(m, "ai_deadline", None)
        if not dl and getattr(m, "ai_deadlines", None):
            raw_dls = m.ai_deadlines
            if isinstance(raw_dls, str):
                try:
                    raw_dls = json.loads(raw_dls)
                except Exception:
                    raw_dls = []
            if raw_dls and isinstance(raw_dls, list):
                first_dl_val = raw_dls[0].get("deadline") or raw_dls[0].get("datetime")
                if first_dl_val:
                    try:
                        dl = datetime.fromisoformat(first_dl_val.replace("Z", "+00:00"))
                    except Exception:
                        dl = None
        if dl:
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=timezone.utc)
            timeline_deadlines.append((m, dl))

    if len(timeline_deadlines) < 2:
        return [] if is_id_call else None

    first_m, first_dl = timeline_deadlines[0]
    last_m, last_dl = timeline_deadlines[-1]

    # If the deadline shifted by more than 1 hour
    delta_seconds = (last_dl - first_dl).total_seconds()
    if abs(delta_seconds) > 3600:
        direction = "extended" if delta_seconds > 0 else "advanced"
        result = {
            "old_deadline": first_dl.isoformat().replace("+00:00", "Z"),
            "previous_deadline": first_dl.isoformat().replace("+00:00", "Z"),
            "new_deadline": last_dl.isoformat().replace("+00:00", "Z"),
            "direction": direction,
            "status": "shifted",
            "confidence": 0.88,
            "message_id": last_m.id,
            "subject": getattr(last_m, "subject", None),
        }
        return [result] if is_id_call else result

    return [] if is_id_call else None
