"""
AI Analysis Job model — durable, recoverable background queue for email AI intelligence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.orm import relationship, backref

from app.extensions import db


class AIAnalysisJob(db.Model):
    """Represents a durable asynchronous AI analysis job for an email message.

    State transitions:
        pending -> processing -> completed
        processing -> pending (retry / recovery)
        processing -> failed (max attempts exhausted)
        pending / processing -> cancelled (optional)
    """

    __tablename__ = "ai_analysis_jobs"

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    VALID_STATUSES = {
        STATUS_PENDING,
        STATUS_PROCESSING,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }

    id = sa.Column(
        sa.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email_id = sa.Column(
        sa.String(36),
        sa.ForeignKey("email_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = sa.Column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = sa.Column(
        sa.String(32),
        nullable=False,
        default=STATUS_PENDING,
        index=True,
    )
    attempts = sa.Column(
        sa.Integer,
        nullable=False,
        default=0,
    )
    max_attempts = sa.Column(
        sa.Integer,
        nullable=False,
        default=3,
    )
    available_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    locked_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    locked_by = sa.Column(
        sa.String(128),
        nullable=True,
    )
    lease_token = sa.Column(
        sa.String(64),
        nullable=True,
    )
    heartbeat_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    last_error = sa.Column(
        sa.Text,
        nullable=True,
    )
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    email = relationship(
        "EmailMessage",
        backref=backref("ai_jobs", lazy="dynamic", cascade="all, delete-orphan"),
    )
    user = relationship(
        "User",
        backref=backref("ai_jobs", lazy="dynamic", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        # Partial unique index: at most one active (pending or processing) job per email
        sa.Index(
            "uq_active_ai_job_per_email",
            "email_id",
            unique=True,
            postgresql_where=sa.text("status IN ('pending', 'processing')"),
            sqlite_where=sa.text("status IN ('pending', 'processing')"),
        ),
        # Compound index for atomic queue claiming
        sa.Index("ix_ai_jobs_claim", "status", "available_at"),
        # Compound index for stale recovery
        sa.Index("ix_ai_jobs_stale", "status", "locked_at"),
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.available_at is None:
            self.available_at = datetime.now(timezone.utc)
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serialize job for API responses."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "user_id": self.user_id,
            "status": self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "available_at": self.available_at.isoformat() if self.available_at else None,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "locked_by": self.locked_by,
            "heartbeat_at": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self) -> str:
        return f"<AIAnalysisJob {self.id[:8]} email={self.email_id[:8]} status={self.status} attempts={self.attempts}>"
