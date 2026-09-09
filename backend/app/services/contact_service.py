"""
Contact service — people intelligence derived strictly from email metadata.
"""

from __future__ import annotations

import email.utils
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import defer

from app.extensions import db
from app.models import EmailMessage, User
from app.services.personalization_service import get_or_create_user_preferences


def _extract_topics_from_subjects(subjects: list[str]) -> list[str]:
    """Extract representative, non-trivial topic keywords from subjects."""
    stop_words = {
        "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with",
        "by", "is", "re", "fwd", "fw", "your", "my", "our", "from", "update", "new",
        "please", "thanks", "thank", "you", "regarding", "meeting", "call",
    }
    word_counts: dict[str, int] = {}
    for sub in subjects:
        words = re.findall(r"\b[A-Za-z]{3,}\b", sub.lower())
        for w in words:
            if w not in stop_words:
                word_counts[w] = word_counts.get(w, 0) + 1

    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    return [w[0].capitalize() for w in sorted_words[:5]]


def get_all_contacts_for_user(
    user_id: str,
    emails: Optional[list[EmailMessage]] = None,
    user_email: Optional[str] = None,
    pref: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Aggregate all observable contacts from email interactions for the authenticated user."""
    if user_email is None:
        user = db.session.get(User, user_id)
        user_email = user.email.lower().strip() if user else ""
    else:
        user_email = user_email.lower().strip()

    if pref is None:
        pref = get_or_create_user_preferences(user_id)
    important_set = set(pref.get_important_senders_list())
    ignored_set = set(pref.get_ignored_senders_list())

    if emails is None:
        emails = (
            EmailMessage.query.filter_by(user_id=user_id)
            .options(defer(EmailMessage.body_text), defer(EmailMessage.body_html))
            .order_by(EmailMessage.received_at.desc())
            .all()
        )

    contacts_map: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)

    for em in emails:
        raw_from = em.from_address or ""
        p_name, p_email = email.utils.parseaddr(raw_from)
        clean_email = p_email.lower().strip() if p_email else raw_from.lower().strip()

        # Skip self-emails for contact listing
        if clean_email == user_email or not clean_email or "@" not in clean_email:
            continue

        if clean_email not in contacts_map:
            contacts_map[clean_email] = {
                "id": clean_email,
                "email": clean_email,
                "name": p_name.strip() or clean_email.split("@")[0].replace(".", " ").title(),
                "message_count": 0,
                "sent_count": 0,
                "received_count": 0,
                "last_contact": None,
                "first_contact": None,
                "open_actions_count": 0,
                "waiting_threads_count": 0,
                "subjects": [],
                "is_important": clean_email in important_set,
                "is_ignored": clean_email in ignored_set,
            }

        c = contacts_map[clean_email]
        c["message_count"] += 1
        c["received_count"] += 1

        if em.ai_action_required:
            c["open_actions_count"] += 1
        if em.ai_waiting_for:
            c["waiting_threads_count"] += 1

        rx_dt = em.received_at
        if rx_dt:
            rx_iso = rx_dt.isoformat()
            if not c["last_contact"] or rx_iso > c["last_contact"]:
                c["last_contact"] = rx_iso
            if not c["first_contact"] or rx_iso < c["first_contact"]:
                c["first_contact"] = rx_iso

        if em.subject and len(c["subjects"]) < 20:
            c["subjects"].append(em.subject)

    # Compute deterministic importance scores
    result = []
    for c in contacts_map.values():
        score = 40.0
        # Volume boost
        score += min(c["message_count"] * 2.0, 30.0)
        # Action boost
        score += min(c["open_actions_count"] * 5.0, 15.0)
        # Recency boost
        if c["last_contact"]:
            try:
                last_dt = datetime.fromisoformat(c["last_contact"])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age_days = (now - last_dt).total_seconds() / 86400.0
                if age_days <= 3:
                    score += 15.0
                elif age_days <= 14:
                    score += 5.0
            except Exception:
                pass

        if c["is_important"]:
            score += 20.0
        if c["is_ignored"]:
            score -= 30.0

        c["importance_score"] = int(round(max(min(score, 100.0), 10.0)))
        c["recent_topics"] = _extract_topics_from_subjects(c.pop("subjects"))
        c["action_items_count"] = c["open_actions_count"]
        result.append(c)

    return result


def get_contacts_list(
    user_id: str,
    query_str: Optional[str] = None,
    sort_by: str = "importance",
    page: int = 1,
    per_page: int = 20,
) -> dict[str, Any]:
    """Retrieve paginated, sortable contacts for user."""
    contacts = get_all_contacts_for_user(user_id)

    if query_str:
        q_lower = query_str.lower().strip()
        contacts = [
            c for c in contacts
            if q_lower in c["name"].lower() or q_lower in c["email"].lower()
        ]

    if sort_by == "activity":
        contacts.sort(key=lambda c: c["last_contact"] or "", reverse=True)
    elif sort_by == "volume":
        contacts.sort(key=lambda c: c["message_count"], reverse=True)
    elif sort_by == "alphabetical":
        contacts.sort(key=lambda c: c["name"].lower())
    else:  # importance
        contacts.sort(key=lambda c: c["importance_score"], reverse=True)

    total = len(contacts)
    start = (page - 1) * per_page
    end = start + per_page
    items = contacts[start:end]

    return {
        "contacts": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_next": end < total,
    }


def get_contact_detail(user_id: str, contact_email: str) -> Optional[dict[str, Any]]:
    """Retrieve deep intelligence overview and recent messages for a specific contact."""
    clean_target = contact_email.lower().strip()
    all_contacts = get_all_contacts_for_user(user_id)
    contact = next((c for c in all_contacts if c["email"] == clean_target), None)
    if not contact:
        return None

    # Fetch recent emails from this contact
    recent_emails = (
        EmailMessage.query.filter(
            EmailMessage.user_id == user_id,
            EmailMessage.from_address.ilike(f"%{clean_target}%"),
        )
        .order_by(EmailMessage.received_at.desc())
        .limit(10)
        .all()
    )

    contact_copy = dict(contact)
    contact_copy["recent_emails"] = [e.to_dict() for e in recent_emails]

    from app.services.relationship_service import get_relationship_profile
    rel_profile = get_relationship_profile(user_id, clean_target)
    contact_copy["relationship"] = rel_profile
    contact_copy["relationship_score"] = rel_profile.get("score", 50)
    contact_copy["relationship_health"] = rel_profile.get("health", "ACTIVE")
    contact_copy["relationship_reasons"] = rel_profile.get("reasons", [])
    contact_copy["response_time_stats"] = rel_profile.get("response_time", {})

    return contact_copy
