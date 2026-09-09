"""
Reminder model — follow-up / deadline reminders extracted by the AI.
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class Reminder(db.Model):
    """A reminder or follow-up item extracted from an email."""

    __tablename__ = "reminders"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email_id = db.Column(
        db.String(36),
        db.ForeignKey("email_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    reminder_type = db.Column(db.String(100), nullable=False)
    event_date_time = db.Column(db.DateTime, nullable=False)
    reminder_date_time = db.Column(db.DateTime, nullable=False)
    priority = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), nullable=False, default="PENDING")
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    email = db.relationship("EmailMessage", back_populates="reminders")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self):
        """Return a JSON-safe dictionary."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "title": self.title,
            "description": self.description,
            "reminder_type": self.reminder_type,
            "event_date_time": (
                self.event_date_time.isoformat() if self.event_date_time else None
            ),
            "reminder_date_time": (
                self.reminder_date_time.isoformat() if self.reminder_date_time else None
            ),
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Reminder {self.title[:40]}>"
