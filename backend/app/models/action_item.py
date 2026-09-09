"""
ActionItem model — represents centralized, explainable productivity actions.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum

from app.extensions import db


class ActionType(str, Enum):
    EMAIL_RESPONSE = "EMAIL_RESPONSE"
    TASK_DUE = "TASK_DUE"
    FOLLOW_UP = "FOLLOW_UP"
    DEADLINE = "DEADLINE"
    MEETING_PROPOSAL = "MEETING_PROPOSAL"
    WAITING_FOR_REPLY = "WAITING_FOR_REPLY"
    STALE_CONVERSATION = "STALE_CONVERSATION"
    REMINDER = "REMINDER"


class ActionStatus(str, Enum):
    OPEN = "OPEN"
    SNOOZED = "SNOOZED"
    DISMISSED = "DISMISSED"
    COMPLETED = "COMPLETED"


class ActionItem(db.Model):
    """Unified action item across MailMind."""

    __tablename__ = "action_items"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(50), nullable=False, default="medium")
    score = db.Column(db.Integer, nullable=False, default=50)
    reasons = db.Column(db.Text, nullable=True)  # JSON array of reasons
    source_email_id = db.Column(
        db.String(36),
        db.ForeignKey("email_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_thread_id = db.Column(db.String(255), nullable=True, index=True)
    due_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(50), nullable=False, default="OPEN", index=True)
    snoozed_until = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)  # JSON object with extra payload

    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.CheckConstraint("score >= 0 AND score <= 100", name="ck_action_items_score_bounds"),
        db.Index("ix_action_items_user_status_due", "user_id", "status", "due_at"),
        db.Index("ix_action_items_dedup", "user_id", "action_type", "source_email_id"),
    )

    # Relationships
    user = db.relationship("User", backref=db.backref("action_items", cascade="all, delete-orphan", lazy="dynamic"))
    source_email = db.relationship("EmailMessage", foreign_keys=[source_email_id], backref=db.backref("action_items", lazy="dynamic"))

    def __init__(self, **kwargs):
        # Validate score boundaries
        if "score" in kwargs and kwargs["score"] is not None:
            kwargs["score"] = max(0, min(100, int(kwargs["score"])))
        if "reasons" in kwargs and isinstance(kwargs["reasons"], (list, dict)):
            kwargs["reasons"] = json.dumps(kwargs["reasons"])
        if "metadata_json" in kwargs and isinstance(kwargs["metadata_json"], (list, dict)):
            kwargs["metadata_json"] = json.dumps(kwargs["metadata_json"])
        super().__init__(**kwargs)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dictionary."""
        reasons_list = []
        if self.reasons:
            try:
                reasons_list = json.loads(self.reasons)
            except Exception:
                reasons_list = [self.reasons]

        extra_meta = {}
        if self.metadata_json:
            try:
                extra_meta = json.loads(self.metadata_json)
            except Exception:
                pass

        return {
            "id": self.id,
            "user_id": self.user_id,
            "action_type": self.action_type,
            "type": self.action_type,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "score": self.score,
            "reasons": reasons_list,
            "source_email_id": self.source_email_id,
            "source_thread_id": self.source_thread_id,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "status": self.status,
            "snoozed_until": self.snoozed_until.isoformat() if self.snoozed_until else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "dismissed_at": self.dismissed_at.isoformat() if self.dismissed_at else None,
            "metadata": extra_meta,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<ActionItem {self.id} [{self.action_type}] {self.status} {self.score}>"
