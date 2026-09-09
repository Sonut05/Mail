"""
Notification Service — User-scoped notification creation, deduplication, reading, and dismissal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.models.notification import Notification, NotificationType, NotificationSeverity


def create_notification_if_not_exists(
    user_id: str,
    notif_type: str,
    title: str,
    message: str,
    severity: str = "info",
    source_type: str | None = None,
    source_id: str | None = None
) -> Notification:
    """Idempotently create a notification for a user.
    Deduplicates identical logical notifications using (user_id, notif_type, source_type, source_id).
    """
    if source_type and source_id:
        existing = Notification.query.filter_by(
            user_id=user_id,
            type=notif_type,
            source_type=source_type,
            source_id=str(source_id)
        ).first()
        if existing:
            return existing

    notif = Notification(
        user_id=user_id,
        type=notif_type,
        title=title[:255],
        message=message,
        severity=severity,
        source_type=source_type,
        source_id=str(source_id) if source_id else None,
    )
    try:
        db.session.add(notif)
        db.session.commit()
        return notif
    except Exception:
        db.session.rollback()
        if source_type and source_id:
            existing = Notification.query.filter_by(
                user_id=user_id,
                type=notif_type,
                source_type=source_type,
                source_id=str(source_id)
            ).first()
            if existing:
                return existing
        raise


def get_user_notifications(
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False
) -> dict[str, Any]:
    """List paginated notifications for the user."""
    query = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.dismissed_at.is_(None)
    )
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))

    query = query.order_by(Notification.created_at.desc())
    total = query.count()
    offset = max(0, (page - 1) * page_size)
    items = query.offset(offset).limit(page_size).all()

    unread_count = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
        Notification.dismissed_at.is_(None)
    ).count()

    return {
        "items": [item.to_dict() for item in items],
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "page_size": page_size,
        "has_next": (offset + len(items)) < total,
    }


def mark_notification_read(user_id: str, notif_id: str) -> Notification:
    """Mark a notification as read (user-scoped)."""
    notif = Notification.query.filter_by(id=notif_id, user_id=user_id).first()
    if not notif:
        raise ValueError("Notification not found.")
    if not notif.read_at:
        notif.read_at = datetime.now(timezone.utc)
        db.session.commit()
    return notif


def mark_all_notifications_read(user_id: str) -> int:
    """Mark all unread notifications as read for the user."""
    now = datetime.now(timezone.utc)
    updated = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.read_at.is_(None)
    ).update({"read_at": now})
    db.session.commit()
    return updated


def dismiss_notification(user_id: str, notif_id: str) -> Notification:
    """Dismiss a notification."""
    notif = Notification.query.filter_by(id=notif_id, user_id=user_id).first()
    if not notif:
        raise ValueError("Notification not found.")
    notif.dismissed_at = datetime.now(timezone.utc)
    db.session.commit()
    return notif


def get_unread_notifications_count(user_id: str) -> int:
    """Return count of unread and undismissed notifications for a user."""
    return Notification.query.filter(
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
        Notification.dismissed_at.is_(None),
    ).count()

