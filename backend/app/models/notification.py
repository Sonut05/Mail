"""
Notification model — internal MailMind notification system.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from app.extensions import db


class NotificationType(str, Enum):
    IMPORTANT_EMAIL = "IMPORTANT_EMAIL"
    DEADLINE_APPROACHING = "DEADLINE_APPROACHING"
    FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
    STALE_THREAD = "STALE_THREAD"
    MEETING_CONFLICT = "MEETING_CONFLICT"
    AI_ANALYSIS_FAILED = "AI_ANALYSIS_FAILED"
    DIGEST_READY = "DIGEST_READY"


class NotificationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"


class Notification(db.Model):
    """Internal user-scoped notification."""

    __tablename__ = "notifications"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(50), nullable=False, default="info")
    source_type = db.Column(db.String(50), nullable=True)
    source_id = db.Column(db.String(255), nullable=True)
    read_at = db.Column(db.DateTime, nullable=True, index=True)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )

    __table_args__ = (
        db.Index("ix_notifications_user_unread", "user_id", "read_at", "dismissed_at"),
        db.Index("ix_notifications_dedup", "user_id", "type", "source_type", "source_id"),
    )

    user = db.relationship("User", backref=db.backref("notifications", cascade="all, delete-orphan", lazy="dynamic"))

    def to_dict(self) -> dict:
        """Return a JSON-serializable dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "read": self.read_at is not None,
            "is_read": self.read_at is not None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "dismissed": self.dismissed_at is not None,
            "is_dismissed": self.dismissed_at is not None,
            "dismissed_at": self.dismissed_at.isoformat() if self.dismissed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Notification {self.id} [{self.type}] {self.title[:30]}>"
