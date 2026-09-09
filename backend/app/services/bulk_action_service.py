"""
Bulk Action Service — Executes user-confirmed bulk operations on selected MailMind items.
Strict multi-user ownership check: if ANY item belongs to another user, REJECTS THE ENTIRE REQUEST.
Two-layer confirmation safeguard: selection alone NEVER creates tasks.
"""

from __future__ import annotations

import hmac
import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from app.extensions import db
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.action_item import ActionItem, ActionStatus
from app.services.action_center_service import snooze_action, dismiss_action


def execute_bulk_action(
    user_id: str,
    action: str,
    item_ids: list[str],
    item_type: str = "email",  # "email" or "action"
    options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute bulk operations with strict multi-user ownership enforcement.
    Supported actions:
        - "snooze"
        - "dismiss"
        - "mark_important"
        - "create_tasks" (requires confirmed=True payload)
    """
    if not item_ids:
        raise ValueError("No item IDs provided for bulk operation.")

    if len(item_ids) > 100:
        raise ValueError("Bulk action exceeds maximum limit of 100 items.")

    options = options or {}
    action_clean = action.lower()

    # 1. Ownership & existence validation
    if item_type == "action":
        items = ActionItem.query.filter(ActionItem.id.in_(item_ids)).all()
        found_ids = {i.id for i in items}
        for i in items:
            if i.user_id != user_id:
                raise PermissionError("Access denied: One or more selected actions belong to another user.")
        if len(found_ids) != len(item_ids):
            raise ValueError("One or more action item IDs could not be found.")

        # Process action item actions
        affected_count = 0
        if action_clean == "snooze":
            duration = options.get("duration", "tomorrow")
            for item in items:
                snooze_action(user_id, item.id, duration=duration)
                affected_count += 1
        elif action_clean == "dismiss":
            for item in items:
                dismiss_action(user_id, item.id)
                affected_count += 1
        elif action_clean == "complete":
            for item in items:
                item.status = ActionStatus.COMPLETED.value
                item.completed_at = datetime.now(timezone.utc)
                affected_count += 1
            db.session.commit()
        else:
            raise ValueError(f"Unsupported action '{action}' for action items.")

        return {
            "success": True,
            "action": action_clean,
            "affected_count": affected_count,
        }

    # Otherwise default item_type == "email"
    emails = EmailMessage.query.filter(EmailMessage.id.in_(item_ids)).all()
    found_ids = {e.id for e in emails}
    for e in emails:
        if e.user_id != user_id:
            raise PermissionError("Access denied: One or more selected emails belong to another user.")

    if len(found_ids) != len(item_ids):
        raise ValueError("One or more email IDs could not be found.")

    affected_count = 0

    if action_clean == "mark_important":
        for e in emails:
            e.ai_importance_score = 90
            e.ai_priority = "high"
            affected_count += 1
        db.session.commit()

    elif action_clean == "mark_unimportant":
        for e in emails:
            e.ai_importance_score = 20
            e.ai_priority = "low"
            affected_count += 1
        db.session.commit()

    elif action_clean == "create_tasks":
        # Two-layer confirmation check
        if not options.get("confirmed"):
            raise ValueError("Explicit user confirmation is mandatory to create tasks from bulk emails.")

        for e in emails:
            # Check if task already exists for this email
            existing = Task.query.filter_by(user_id=user_id, email_id=e.id).first()
            if not existing:
                title = f"Action: {e.subject or 'Review email'}"[:255]
                t = Task(
                    user_id=user_id,
                    email_id=e.id,
                    task_title=title,
                    description=e.ai_next_action or e.summary or e.body_text[:200] if e.body_text else None,
                    due_date=e.ai_deadline,
                    priority=e.ai_priority or "medium",
                    status="pending"
                )
                db.session.add(t)
                affected_count += 1
        db.session.commit()

    elif action_clean == "mark_read":
        for e in emails:
            cur_labels = [l.strip() for l in (e.labels or "").split(",") if l.strip()]
            cur_labels = [l for l in cur_labels if l.upper() != "UNREAD"]
            e.labels = ",".join(cur_labels)
            affected_count += 1
        db.session.commit()

    elif action_clean == "mark_unread":
        for e in emails:
            cur_labels = [l.strip() for l in (e.labels or "").split(",") if l.strip()]
            if "UNREAD" not in [l.upper() for l in cur_labels]:
                cur_labels.append("UNREAD")
            e.labels = ",".join(cur_labels)
            affected_count += 1
        db.session.commit()

    elif action_clean == "star":
        for e in emails:
            cur_labels = [l.strip() for l in (e.labels or "").split(",") if l.strip()]
            if "STARRED" not in [l.upper() for l in cur_labels]:
                cur_labels.append("STARRED")
            e.labels = ",".join(cur_labels)
            affected_count += 1
        db.session.commit()

    elif action_clean == "dismiss_action":
        for e in emails:
            e.ai_action_required = False
            affected_count += 1
        db.session.commit()

    else:
        raise ValueError(f"Unsupported bulk action '{action}' for emails.")

    return {
        "success": True,
        "action": action_clean,
        "affected_count": affected_count,
        "affected": affected_count,
    }
