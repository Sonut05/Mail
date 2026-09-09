"""
UserFeedbackSignal model — records explicit user actions to learn ranking weights.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.extensions import db


class UserFeedbackSignal(db.Model):
    """User-scoped feedback signal reflecting explicit actions on emails/tasks/events."""

    __tablename__ = "user_feedback_signals"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_type = db.Column(
        db.String(50), nullable=False, index=True
    )  # e.g., 'mark_important', 'mark_unimportant', 'accept_task', 'dismiss_task', 'category_override'
    target_type = db.Column(
        db.String(50), nullable=False, index=True
    )  # 'sender', 'category', 'email', 'thread'
    target_value = db.Column(
        db.String(255), nullable=False, index=True
    )  # e.g., sender email address, category name
    weight = db.Column(
        db.Float, nullable=False, default=1.0
    )  # bounded increment/decrement (e.g. +1.0, -1.0)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = db.relationship("User", back_populates="feedback_signals")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "signal_type": self.signal_type,
            "target_type": self.target_type,
            "target_value": self.target_value,
            "weight": self.weight,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<UserFeedbackSignal {self.signal_type}:{self.target_type}={self.target_value} ({self.weight:+0.1f})>"
