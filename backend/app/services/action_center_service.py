"""
Action Center Service — Centralized action management, deterministic scoring [0, 100],
smart snooze, idempotent synchronization, and explainability.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import and_, or_

_sync_lock = threading.Lock()

from app.extensions import db
from app.models.action_item import ActionItem, ActionType, ActionStatus
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.services.follow_up_service import get_follow_up_recommendations


def compute_action_score(
    urgency: int,
    deadline_proximity: int,
    importance: int,
    waiting_duration: int,
    relationship_importance: int
) -> tuple[int, list[str]]:
    """Calculate deterministic action priority score bounded strictly in [0, 100].
    Returns (score, reasons).
    """
    reasons = []
    total = 0

    # Urgency (max 30)
    urg_capped = max(0, min(30, urgency))
    total += urg_capped
    if urg_capped >= 20:
        reasons.append("High immediacy / requires prompt attention")

    # Deadline proximity (max 30)
    dl_capped = max(0, min(30, deadline_proximity))
    total += dl_capped
    if dl_capped >= 25:
        reasons.append("Deadline imminent (< 24 hours)")
    elif dl_capped >= 15:
        reasons.append("Approaching deadline (< 48 hours)")

    # Importance (max 20)
    imp_capped = max(0, min(20, importance))
    total += imp_capped
    if imp_capped >= 15:
        reasons.append("High importance email / critical task")

    # Waiting duration (max 10)
    wait_capped = max(0, min(10, waiting_duration))
    total += wait_capped
    if wait_capped >= 8:
        reasons.append("Awaiting reply beyond normal turnaround")

    # Relationship importance (max 10)
    rel_capped = max(0, min(10, relationship_importance))
    total += rel_capped
    if rel_capped >= 8:
        reasons.append("Key contact / VIP sender")

    final_score = max(0, min(100, total))
    if not reasons:
        reasons.append("Standard priority action item")

    return final_score, reasons


def sync_actions(user_id: str) -> list[ActionItem]:
    """Idempotently discover and sync action items across MailMind domain models.
    Repeated runs NEVER create duplicate logical ActionItems.
    """
    with _sync_lock:
        return _sync_actions_locked(user_id)


def _sync_actions_locked(user_id: str) -> list[ActionItem]:
    now = datetime.now(timezone.utc)
    synced_items = []

    # 1. Emails requiring action
    action_emails = EmailMessage.query.filter(
        EmailMessage.user_id == user_id,
        EmailMessage.ai_action_required == True
    ).all()

    for em in action_emails:
        # Check if action already exists for this email
        existing_list = ActionItem.query.filter_by(
            user_id=user_id,
            action_type=ActionType.EMAIL_RESPONSE.value,
            source_email_id=em.id
        ).all()
        if existing_list:
            existing = existing_list[0]
            for dup in existing_list[1:]:
                db.session.delete(dup)
        else:
            existing = None

        # Calculate score inputs
        urg = 25 if em.ai_priority == "urgent" else (15 if em.ai_priority == "high" else 5)
        dl_prox = 0
        if em.ai_deadline:
            dl_aware = em.ai_deadline.replace(tzinfo=timezone.utc) if em.ai_deadline.tzinfo is None else em.ai_deadline
            diff_h = (dl_aware - now).total_seconds() / 3600.0
            if diff_h <= 24:
                dl_prox = 30
            elif diff_h <= 48:
                dl_prox = 20
            elif diff_h <= 96:
                dl_prox = 10

        imp = min(20, int((em.ai_importance_score or 50) * 0.2))
        score, reasons = compute_action_score(urg, dl_prox, imp, 0, 5)

        priority = "urgent" if score >= 80 else ("high" if score >= 60 else ("medium" if score >= 35 else "low"))

        if existing:
            # Update score, priority, and reasons if not completed or dismissed
            if existing.status in (ActionStatus.OPEN.value, ActionStatus.SNOOZED.value):
                existing.score = score
                existing.priority = priority
                existing.reasons = json.dumps(reasons)
                existing.due_at = em.ai_deadline
            synced_items.append(existing)
        else:
            new_item = ActionItem(
                user_id=user_id,
                action_type=ActionType.EMAIL_RESPONSE.value,
                title=f"Respond to: {em.subject or 'Email'}"[:255],
                description=em.ai_next_action or em.summary or em.subject,
                priority=priority,
                score=score,
                reasons=json.dumps(reasons),
                source_email_id=em.id,
                source_thread_id=em.thread_id or em.id,
                due_at=em.ai_deadline,
                status=ActionStatus.OPEN.value,
            )
            db.session.add(new_item)
            synced_items.append(new_item)

    # 2. Overdue / Due Soon Tasks
    pending_tasks = Task.query.filter(
        Task.user_id == user_id,
        Task.status.in_(["pending", "in_progress"])
    ).all()

    for task in pending_tasks:
        existing_list = ActionItem.query.filter_by(
            user_id=user_id,
            action_type=ActionType.TASK_DUE.value,
            source_email_id=task.email_id,
            title=f"Task: {task.task_title}"[:255]
        ).all()
        if existing_list:
            existing = existing_list[0]
            for dup in existing_list[1:]:
                db.session.delete(dup)
        else:
            existing = None

        urg = 20
        dl_prox = 0
        if task.due_date:
            t_due = task.due_date.replace(tzinfo=timezone.utc) if task.due_date.tzinfo is None else task.due_date
            diff_h = (t_due - now).total_seconds() / 3600.0
            if diff_h < 0:
                dl_prox = 30  # Overdue
                urg = 30
            elif diff_h <= 24:
                dl_prox = 25
            elif diff_h <= 48:
                dl_prox = 15

        score, reasons = compute_action_score(urg, dl_prox, 15, 0, 0)
        priority = "urgent" if score >= 80 else ("high" if score >= 60 else "medium")

        if existing:
            if existing.status in (ActionStatus.OPEN.value, ActionStatus.SNOOZED.value):
                existing.score = score
                existing.priority = priority
                existing.reasons = json.dumps(reasons)
                existing.due_at = task.due_date
            synced_items.append(existing)
        else:
            new_item = ActionItem(
                user_id=user_id,
                action_type=ActionType.TASK_DUE.value,
                title=f"Task: {task.task_title}"[:255],
                description=task.description or "User action task",
                priority=priority,
                score=score,
                reasons=json.dumps(reasons),
                source_email_id=task.email_id,
                due_at=task.due_date,
                status=ActionStatus.OPEN.value,
            )
            db.session.add(new_item)
            synced_items.append(new_item)

    # 3. Follow-up recommendations
    follow_ups = get_follow_up_recommendations(user_id)
    for fu in follow_ups:
        thread_id = fu.get("thread_id")
        existing_list = ActionItem.query.filter_by(
            user_id=user_id,
            action_type=ActionType.FOLLOW_UP.value,
            source_thread_id=thread_id
        ).all()
        if existing_list:
            existing = existing_list[0]
            for dup in existing_list[1:]:
                db.session.delete(dup)
        else:
            existing = None

        days_waiting = fu.get("days_waiting", 3)
        score, reasons = compute_action_score(15, 0, 10, min(10, days_waiting * 2), 5)
        reasons.append(f"No reply received in {days_waiting} days")

        if existing:
            if existing.status in (ActionStatus.OPEN.value, ActionStatus.SNOOZED.value):
                existing.score = score
                existing.reasons = json.dumps(reasons)
            synced_items.append(existing)
        else:
            new_item = ActionItem(
                user_id=user_id,
                action_type=ActionType.FOLLOW_UP.value,
                title=f"Follow up: {fu.get('subject') or 'Thread'}"[:255],
                description=fu.get("suggested_followup") or f"Awaiting reply from {fu.get('recipient')}",
                priority="medium" if score < 60 else "high",
                score=score,
                reasons=json.dumps(reasons),
                source_thread_id=thread_id,
                source_email_id=fu.get("latest_email_id"),
                status=ActionStatus.OPEN.value,
            )
            db.session.add(new_item)
            synced_items.append(new_item)

    db.session.commit()
    return synced_items


def get_action_center(
    user_id: str,
    action_type: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    include_snoozed: bool = False,
    page: int = 1,
    page_size: int = 20
) -> dict[str, Any]:
    """Get paginated Action Center items for the user."""
    now = datetime.now(timezone.utc)

    query = ActionItem.query.filter(ActionItem.user_id == user_id)

    if status:
        query = query.filter(ActionItem.status == status.upper())
    else:
        # By default show OPEN actions, or SNOOZED actions whose snooze expired
        if not include_snoozed:
            query = query.filter(
                or_(
                    ActionItem.status == ActionStatus.OPEN.value,
                    and_(
                        ActionItem.status == ActionStatus.SNOOZED.value,
                        ActionItem.snoozed_until <= now
                    )
                )
            )

    if action_type:
        query = query.filter(ActionItem.action_type == action_type.upper())

    if priority:
        query = query.filter(ActionItem.priority == priority.lower())

    # Order by score descending, due_at ascending
    query = query.order_by(ActionItem.score.desc(), ActionItem.due_at.asc())

    total = query.count()
    offset = max(0, (page - 1) * page_size)
    items = query.offset(offset).limit(page_size).all()

    serialized_items = [item.to_dict() for item in items]
    return {
        "items": serialized_items,
        "actions": serialized_items,
        "action_items": serialized_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": (offset + len(items)) < total,
    }


def snooze_action(user_id: str, action_id: str, duration: str, custom_date: str | None = None) -> ActionItem:
    """Snooze an action item (MailMind internal state only, never touches Gmail)."""
    item = ActionItem.query.filter_by(id=action_id, user_id=user_id).first()
    if not item:
        raise ValueError("Action item not found.")

    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=24)  # Default tomorrow

    dur = (duration or "tomorrow").lower()
    if dur == "1h":
        until = now + timedelta(hours=1)
    elif dur == "tomorrow":
        until = now + timedelta(days=1)
    elif dur == "3d":
        until = now + timedelta(days=3)
    elif dur == "next_week":
        until = now + timedelta(days=7)
    elif dur == "custom" and custom_date:
        try:
            dt = datetime.fromisoformat(custom_date.replace("Z", "+00:00"))
            until = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            until = now + timedelta(days=1)

    item.status = ActionStatus.SNOOZED.value
    item.snoozed_until = until
    db.session.commit()
    return item


def dismiss_action(user_id: str, action_id: str) -> ActionItem:
    """Dismiss an action item (internal state only)."""
    item = ActionItem.query.filter_by(id=action_id, user_id=user_id).first()
    if not item:
        raise ValueError("Action item not found.")

    item.status = ActionStatus.DISMISSED.value
    item.dismissed_at = datetime.now(timezone.utc)
    db.session.commit()
    return item


def complete_action(user_id: str, action_id: str) -> ActionItem:
    """Mark an action item complete (internal state only)."""
    item = ActionItem.query.filter_by(id=action_id, user_id=user_id).first()
    if not item:
        raise ValueError("Action item not found.")

    item.status = ActionStatus.COMPLETED.value
    item.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    return item
