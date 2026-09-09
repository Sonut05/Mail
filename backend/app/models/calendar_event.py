"""
CalendarEvent model — meetings / events detected in emails by the AI.
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class CalendarEvent(db.Model):
    """A calendar event extracted from an email or created manually."""

    __tablename__ = "calendar_events"

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
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_date_time = db.Column(db.DateTime, nullable=False, index=True)
    end_date_time = db.Column(db.DateTime, nullable=True)
    timezone = db.Column(db.String(100), nullable=False, default="UTC")
    location = db.Column(db.String(500), nullable=True)
    meeting_link = db.Column(db.String(1000), nullable=True)
    organizer = db.Column(db.String(255), nullable=True)
    attendees = db.Column(db.Text, nullable=True)  # JSON-serialised list
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
    user = db.relationship("User", back_populates="calendar_events")
    email = db.relationship("EmailMessage", back_populates="calendar_events")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self):
        """Return a JSON-safe dictionary."""
        start_iso = self.start_date_time.isoformat() if self.start_date_time else None
        end_iso = self.end_date_time.isoformat() if self.end_date_time else None
        return {
            "id": self.id,
            "user_id": self.user_id,
            "email_id": self.email_id,
            "title": self.title,
            "description": self.description,
            "start": start_iso,
            "end": end_iso,
            "start_date_time": start_iso,
            "end_date_time": end_iso,
            "timezone": self.timezone,
            "location": self.location,
            "meeting_link": self.meeting_link,
            "organizer": self.organizer,
            "attendees": self.attendees,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<CalendarEvent {self.title[:40]}>"
