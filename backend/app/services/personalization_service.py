"""
Personalization service — deterministic scoring, user preferences, and feedback signals.
"""

from __future__ import annotations

import json
from email.utils import parseaddr
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import func

from app.extensions import db
from app.models import UserPreference, UserFeedbackSignal, EmailMessage


VALID_BEHAVIORS = {
    "balanced",
    "aggressive",
    "relaxed",
    "strict_action_required",
    "people_first",
    "urgent_only",
}
VALID_THRESHOLDS = {1, 2, 3, 5, 7, 10, 14, 30}


def get_or_create_user_preferences(user_id: str) -> UserPreference:
    """Retrieve or create user preferences with safe enterprise defaults."""
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if not pref:
        pref = UserPreference(
            user_id=user_id,
            preferred_priority_behavior="balanced",
            default_inbox_view="needs_action",
            show_low_priority=True,
            smart_inbox_enabled=True,
            follow_up_detection_enabled=True,
            follow_up_threshold_days=3,
            ai_summary_enabled=True,
            ai_contact_insights_enabled=True,
            ai_analysis_enabled=True,
            auto_ai_analysis=True,
        )
        db.session.add(pref)
        db.session.commit()
    return pref


def update_user_preferences(user_id: str, updates: dict[str, Any]) -> tuple[Optional[UserPreference], Optional[str]]:
    """Update user preferences after strict validation.

    Returns:
        (updated_pref, None) on success, or (None, error_message) on failure.
    """
    pref = get_or_create_user_preferences(user_id)

    # Validate preferred_priority_behavior
    if "preferred_priority_behavior" in updates:
        val = str(updates["preferred_priority_behavior"]).strip().lower()
        if val not in VALID_BEHAVIORS:
            return None, f"Invalid priority behavior. Must be one of: {', '.join(sorted(VALID_BEHAVIORS))}."
        pref.preferred_priority_behavior = val

    # Validate follow_up_threshold_days
    if "follow_up_threshold_days" in updates:
        try:
            days = int(updates["follow_up_threshold_days"])
            if days not in VALID_THRESHOLDS and not (1 <= days <= 30):
                return None, "Follow-up threshold must be between 1 and 30 days."
            pref.follow_up_threshold_days = days
        except (ValueError, TypeError):
            return None, "Invalid follow_up_threshold_days."

    # Validate string lists
    if "important_senders" in updates:
        senders = updates["important_senders"]
        if not isinstance(senders, list):
            return None, "important_senders must be a list of email strings."
        cleaned = [str(s).strip().lower() for s in senders if isinstance(s, str) and "@" in str(s)]
        pref.important_senders = json.dumps(list(set(cleaned)))

    if "ignored_senders" in updates:
        senders = updates["ignored_senders"]
        if not isinstance(senders, list):
            return None, "ignored_senders must be a list of email strings."
        cleaned = [str(s).strip().lower() for s in senders if isinstance(s, str) and "@" in str(s)]
        pref.ignored_senders = json.dumps(list(set(cleaned)))

    if "preferred_categories" in updates:
        categories = updates["preferred_categories"]
        if not isinstance(categories, list):
            return None, "preferred_categories must be a list of category strings."
        cleaned = [str(c).strip().lower() for c in categories if isinstance(c, str) and c.strip()]
        pref.preferred_categories = json.dumps(list(set(cleaned)))

    # Boolean toggles
    bool_fields = [
        "show_low_priority",
        "smart_inbox_enabled",
        "follow_up_detection_enabled",
        "ai_summary_enabled",
        "ai_contact_insights_enabled",
        "ai_analysis_enabled",
        "auto_ai_analysis",
    ]
    for field in bool_fields:
        if field in updates:
            setattr(pref, field, bool(updates[field]))

    if "default_inbox_view" in updates:
        view = str(updates["default_inbox_view"]).strip().lower()
        pref.default_inbox_view = view[:50]

    pref.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return pref, None


def record_user_feedback_signal(
    user_id: str,
    signal_type: str,
    target_type: str,
    target_value: str,
    weight: float = 1.0,
) -> UserFeedbackSignal:
    """Record a user action as a lightweight personalization signal with bounded weight."""
    target_val = str(target_value).strip().lower()[:255]
    sig_type = str(signal_type).strip().lower()[:50]
    tgt_type = str(target_type).strip().lower()[:50]
    bounded_weight = max(min(float(weight), 2.0), -2.0)

    # Deduplicate / aggregate high frequency signals within last hour
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    recent = UserFeedbackSignal.query.filter(
        UserFeedbackSignal.user_id == user_id,
        UserFeedbackSignal.signal_type == sig_type,
        UserFeedbackSignal.target_type == tgt_type,
        UserFeedbackSignal.target_value == target_val,
        UserFeedbackSignal.created_at >= one_hour_ago,
    ).first()

    if recent:
        # Avoid flood; slightly amplify existing recent signal up to bound
        recent.weight = max(min(recent.weight + (bounded_weight * 0.5), 2.0), -2.0)
        db.session.commit()
        return recent

    signal = UserFeedbackSignal(
        user_id=user_id,
        signal_type=sig_type,
        target_type=tgt_type,
        target_value=target_val,
        weight=bounded_weight,
    )
    db.session.add(signal)
    db.session.commit()
    return signal


def get_user_signals_map(user_id: str) -> dict[str, dict[str, float]]:
    """Aggregate bounded user feedback signals for fast in-memory ranking."""
    signals = UserFeedbackSignal.query.filter_by(user_id=user_id).all()
    result: dict[str, dict[str, float]] = {
        "sender": {},
        "category": {},
        "email": {},
    }
    for s in signals:
        t_type = s.target_type
        if t_type not in result:
            result[t_type] = {}
        val = s.target_value
        result[t_type][val] = result[t_type].get(val, 0.0) + s.weight

    # Clamp aggregate weights so single sender/category cannot permanently distort
    for t_type in result:
        for val in result[t_type]:
            result[t_type][val] = max(min(result[t_type][val], 15.0), -15.0)

    return result


def calculate_personalized_score(
    email: EmailMessage,
    pref: UserPreference,
    signals_map: Optional[dict[str, dict[str, float]]] = None,
    now: Optional[datetime] = None,
) -> tuple[int, list[str]]:
    """Compute an explainable, deterministic personalized ranking score (0–100).

    Returns:
        (score: int, reasons: list[str])
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 1. Base AI importance (defaults to 50 if unanalyzed or missing)
    base_importance = email.ai_importance_score if email.ai_importance_score is not None else 50
    score = float(base_importance)
    reasons: list[str] = []

    # Sender extraction
    raw_sender = email.from_address or ""
    _, parsed_sender = parseaddr(raw_sender)
    sender_clean = parsed_sender.lower().strip() if parsed_sender else raw_sender.lower().strip()

    important_senders = pref.get_important_senders_list()
    ignored_senders = pref.get_ignored_senders_list()

    # 2. Sender Importance
    if sender_clean in important_senders:
        score += 15.0
        reasons.append("Sender marked as important contact (+15)")
    elif sender_clean in ignored_senders:
        score -= 25.0
        reasons.append("Sender marked as low priority / ignored (-25)")

    # User feedback signals on sender
    if signals_map and sender_clean in signals_map.get("sender", {}):
        sig_w = signals_map["sender"][sender_clean]
        score += sig_w
        if abs(sig_w) >= 2.0:
            direction = "+" if sig_w > 0 else ""
            reasons.append(f"Adjusted based on your past actions with this sender ({direction}{sig_w:0.0f})")

    # 3. Action Required
    if email.ai_action_required:
        score += 15.0
        reasons.append("Action required detected (+15)")

    # 4. Deadline Urgency
    if email.ai_deadline:
        dl = email.ai_deadline
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        diff_hours = (dl - now).total_seconds() / 3600.0
        if 0 <= diff_hours <= 24:
            score += 20.0
            reasons.append("Approaching deadline within 24 hours (+20)")
        elif 24 < diff_hours <= 72:
            score += 10.0
            reasons.append("Deadline within next 3 days (+10)")
        elif diff_hours < 0:
            score += 5.0
            reasons.append("Overdue deadline requiring follow-up (+5)")

    # 5. Waiting on Reply
    if email.ai_waiting_for and str(email.ai_waiting_for).strip():
        score += 10.0
        reasons.append("Awaiting reply or response (+10)")

    # 6. Recency
    if email.received_at:
        rx = email.received_at
        if rx.tzinfo is None:
            rx = rx.replace(tzinfo=timezone.utc)
        age_hours = (now - rx).total_seconds() / 3600.0
        if age_hours <= 24:
            score += 10.0
            reasons.append("Received within the last 24 hours (+10)")
        elif age_hours <= 72:
            score += 5.0
            reasons.append("Recent email received within 3 days (+5)")
        elif age_hours > 168:  # 7 days
            score -= 5.0
            reasons.append("Older conversation (> 7 days) (-5)")

    # 7. Category and User Preferences
    cat = (email.ai_category or email.category or "").lower().strip()
    preferred_categories = pref.get_preferred_categories_list()
    if cat in preferred_categories:
        score += 10.0
        reasons.append(f"Matches preferred category '{cat}' (+10)")
    elif cat in ("newsletter", "promotion", "spam"):
        score -= 20.0
        reasons.append("Classified as promotional or newsletter (-20)")

    # Category signals from user feedback
    if signals_map and cat in signals_map.get("category", {}):
        cat_w = signals_map["category"][cat]
        score += cat_w
        if abs(cat_w) >= 2.0:
            direction = "+" if cat_w > 0 else ""
            reasons.append(f"Adjusted by category preference signal ({direction}{cat_w:0.0f})")

    # 8. User Priority Behavior Multiplier
    behavior = pref.preferred_priority_behavior
    if behavior in ("aggressive", "strict_action_required"):
        if email.ai_action_required or (email.ai_priority or "").lower() in ("high", "urgent"):
            score += 10.0
            reasons.append("Priority amplified by action-required preference (+10)")
    elif behavior == "people_first":
        if sender_clean in important_senders or (signals_map and sender_clean in signals_map.get("sender", {})):
            score += 10.0
            reasons.append("Priority amplified by 'people_first' preference (+10)")
    elif behavior == "urgent_only":
        if (email.ai_priority or "").lower() == "urgent" or (email.ai_importance_score and email.ai_importance_score >= 80):
            score += 15.0
            reasons.append("Priority amplified by 'urgent_only' preference (+15)")
        else:
            score -= 10.0
            reasons.append("Non-urgent deprioritized by 'urgent_only' preference (-10)")
    elif behavior == "relaxed":
        if (email.ai_priority or "").lower() in ("high", "urgent"):
            score -= 5.0
            reasons.append("Priority softened by 'relaxed' preference (-5)")

    # Bounded clamping
    final_score = int(round(max(min(score, 100.0), 0.0)))
    if not reasons:
        reasons.append(f"Based on baseline AI assessment (score: {final_score})")

    return final_score, reasons


def clear_user_ai_data(user_id: str) -> dict[str, int]:
    """Controlled privacy mechanism: clears only AI-derived data for the specified user.

    Does NOT delete raw email messages, user-confirmed tasks, or calendar events.
    Cancels/deletes AIAnalysisJob rows and resets all email_messages AI columns.
    """
    from app.models.ai_analysis_job import AIAnalysisJob

    # 1. Delete user's analysis jobs
    deleted_jobs = AIAnalysisJob.query.filter_by(user_id=user_id).delete()

    # 2. Reset AI analysis fields on user's EmailMessage records
    user_emails = EmailMessage.query.filter_by(user_id=user_id).all()
    cleared_emails_count = len(user_emails)

    for em in user_emails:
        em.ai_status = "pending"
        em.ai_summary = None
        em.ai_category = None
        em.ai_priority = "medium"
        em.ai_sentiment = None
        em.ai_action_required = False
        em.ai_deadline = None
        em.ai_processed_at = None
        em.ai_model = None
        em.ai_error = None
        em.ai_suggested_tasks = None
        em.ai_suggested_event = None
        em.ai_importance_score = None
        em.ai_confidence_score = None
        em.ai_key_points = None
        em.ai_waiting_for = None
        em.ai_next_action = None
        em.ai_reasons = None
        em.ai_retry_count = 0
        em.ai_last_error = None

    db.session.commit()

    return {
        "emails_cleared": cleared_emails_count,
        "jobs_removed": deleted_jobs,
    }

