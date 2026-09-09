"""
UserPreference model — persistent email intelligence & personalization preferences.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.extensions import db


class UserPreference(db.Model):
    """User-scoped email intelligence and personalization preferences."""

    __tablename__ = "user_preferences"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    preferred_priority_behavior = db.Column(
        db.String(50), nullable=False, default="balanced"
    )
    important_senders = db.Column(db.Text, nullable=True)  # JSON-serialized list of emails
    ignored_senders = db.Column(db.Text, nullable=True)  # JSON-serialized list of emails
    preferred_categories = db.Column(db.Text, nullable=True)  # JSON-serialized list of categories
    default_inbox_view = db.Column(
        db.String(50), nullable=False, default="needs_action"
    )
    show_low_priority = db.Column(db.Boolean, nullable=False, default=True)
    smart_inbox_enabled = db.Column(db.Boolean, nullable=False, default=True)
    follow_up_detection_enabled = db.Column(db.Boolean, nullable=False, default=True)
    follow_up_threshold_days = db.Column(db.Integer, nullable=False, default=3)
    ai_summary_enabled = db.Column(db.Boolean, nullable=False, default=True)
    ai_contact_insights_enabled = db.Column(db.Boolean, nullable=False, default=True)
    ai_analysis_enabled = db.Column(db.Boolean, nullable=False, default=True)
    auto_ai_analysis = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = db.relationship("User", back_populates="preference")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def get_important_senders_list(self) -> list[str]:
        if not self.important_senders:
            return []
        try:
            data = json.loads(self.important_senders)
            return [str(e).strip().lower() for e in data if isinstance(e, str)]
        except Exception:
            return []

    def get_ignored_senders_list(self) -> list[str]:
        if not self.ignored_senders:
            return []
        try:
            data = json.loads(self.ignored_senders)
            return [str(e).strip().lower() for e in data if isinstance(e, str)]
        except Exception:
            return []

    def get_preferred_categories_list(self) -> list[str]:
        if not self.preferred_categories:
            return []
        try:
            data = json.loads(self.preferred_categories)
            return [str(c).strip().lower() for c in data if isinstance(c, str)]
        except Exception:
            return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "preferred_priority_behavior": self.preferred_priority_behavior,
            "important_senders": self.get_important_senders_list(),
            "ignored_senders": self.get_ignored_senders_list(),
            "preferred_categories": self.get_preferred_categories_list(),
            "default_inbox_view": self.default_inbox_view,
            "show_low_priority": self.show_low_priority,
            "smart_inbox_enabled": self.smart_inbox_enabled,
            "follow_up_detection_enabled": self.follow_up_detection_enabled,
            "follow_up_threshold_days": self.follow_up_threshold_days,
            "ai_summary_enabled": self.ai_summary_enabled,
            "ai_contact_insights_enabled": self.ai_contact_insights_enabled,
            "ai_analysis_enabled": self.ai_analysis_enabled,
            "auto_ai_analysis": self.auto_ai_analysis,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<UserPreference for User {self.user_id}>"
