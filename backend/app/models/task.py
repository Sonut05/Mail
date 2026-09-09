"""
Task model — action items extracted from emails by the AI.
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class Task(db.Model):
    """An actionable task extracted from an email."""

    __tablename__ = "tasks"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email_id = db.Column(
        db.String(36),
        db.ForeignKey("email_messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    task_title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.DateTime, nullable=True, index=True)
    priority = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), nullable=False, default="pending", index=True)
    assignee = db.Column(db.String(255), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
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
    user = db.relationship("User", back_populates="tasks")
    email = db.relationship("EmailMessage", back_populates="tasks")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def is_overdue(self) -> bool:
        """Check if task is overdue based on due_date and status."""
        if not self.due_date:
            return False
        if (self.status or "").lower() in ("completed", "cancelled"):
            return False
        now = datetime.now(timezone.utc)
        due = self.due_date
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return due < now

    def to_dict(self):
        """Return a JSON-safe dictionary."""
        return {
            "id": self.id,
            "title": self.task_title,
            "task_title": self.task_title,
            "description": self.description,
            "user_id": self.user_id,
            "email_id": self.email_id,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "priority": self.priority,
            "status": self.status,
            "assignee": self.assignee,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_overdue": self.is_overdue,
        }

    def __repr__(self):
        return f"<Task {self.task_title[:40]}>"
