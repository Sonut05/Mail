"""
EmailMessage model — the central entity that links to all AI-derived data.
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class EmailMessage(db.Model):
    """A processed email with AI analysis results."""

    __tablename__ = "email_messages"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connected_account_id = db.Column(
        db.String(36), db.ForeignKey("connected_email_accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    message_id = db.Column(db.String(255), nullable=False, index=True)
    provider_message_id = db.Column(db.String(255), nullable=True, index=True)
    thread_id = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.Text, nullable=True)
    body_text = db.Column(db.Text, nullable=True)
    body_html = db.Column(db.Text, nullable=True)
    from_address = db.Column(db.String(255), nullable=True)
    to_address = db.Column(db.String(255), nullable=True)
    recipients = db.Column(db.Text, nullable=True)
    cc = db.Column(db.Text, nullable=True)
    bcc = db.Column(db.Text, nullable=True)
    labels = db.Column(db.Text, nullable=True)
    has_attachments = db.Column(db.Boolean, default=False, nullable=False)
    attachment_metadata = db.Column(db.Text, nullable=True)
    raw_metadata = db.Column(db.Text, nullable=True)
    received_at = db.Column(db.DateTime, nullable=True)

    # AI analysis fields
    category = db.Column(db.String(100), nullable=True)
    priority = db.Column(db.String(50), nullable=True)
    sentiment = db.Column(db.String(50), nullable=True)
    summary = db.Column(db.Text, nullable=True)
    auto_reply_required = db.Column(db.Boolean, default=False)
    needs_human_review = db.Column(db.Boolean, default=False)
    confidence = db.Column(db.Float, nullable=True)
    spam_score = db.Column(db.Integer, nullable=True)

    # Phase 4 Email Intelligence fields
    ai_status = db.Column(
        db.String(50), default="pending", nullable=False, index=True
    )
    ai_summary = db.Column(db.Text, nullable=True)
    ai_category = db.Column(db.String(50), nullable=True)
    ai_priority = db.Column(db.String(50), nullable=True)
    ai_sentiment = db.Column(db.String(50), nullable=True)
    ai_action_required = db.Column(db.Boolean, default=False, nullable=False)
    ai_deadline = db.Column(db.DateTime, nullable=True)
    ai_processed_at = db.Column(db.DateTime, nullable=True)
    ai_model = db.Column(db.String(100), nullable=True)
    ai_error = db.Column(db.Text, nullable=True)
    ai_suggested_tasks = db.Column(db.Text, nullable=True)
    ai_suggested_event = db.Column(db.Text, nullable=True)

    # Phase 6 Advanced Email Intelligence fields
    ai_importance_score = db.Column(db.Integer, nullable=True, index=True)
    ai_confidence_score = db.Column(db.Float, nullable=True)
    ai_key_points = db.Column(db.Text, nullable=True)
    ai_waiting_for = db.Column(db.Text, nullable=True)
    ai_next_action = db.Column(db.Text, nullable=True)
    ai_reasons = db.Column(db.Text, nullable=True)
    ai_retry_count = db.Column(db.Integer, default=0, nullable=False)
    ai_last_error = db.Column(db.Text, nullable=True)

    # Phase 8 Advanced Productivity fields
    ai_deadlines = db.Column(db.Text, nullable=True)  # JSON array of multiple deadlines
    ai_meeting_proposal = db.Column(db.Text, nullable=True)  # JSON object with meeting proposal

    # Reply management
    reply_draft = db.Column(db.Text, nullable=True)
    auto_reply_sent = db.Column(db.Boolean, default=False)
    sent_reply_id = db.Column(db.String(255), nullable=True)

    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # --- Constraints ---
    __table_args__ = (
        db.UniqueConstraint("connected_account_id", "provider_message_id", name="uq_connected_account_provider_msg"),
        db.Index("ix_email_messages_user_thread", "user_id", "thread_id"),
        db.Index("ix_email_messages_user_from", "user_id", "from_address"),
    )

    # --- Relationships ---
    user = db.relationship("User", back_populates="emails")
    connected_account = db.relationship(
        "ConnectedEmailAccount",
        backref=db.backref("emails", cascade="all, delete-orphan", lazy="dynamic"),
    )
    entities = db.relationship(
        "Entity", back_populates="email", cascade="all, delete-orphan", lazy="select"
    )
    tasks = db.relationship(
        "Task", back_populates="email", cascade="all, delete-orphan", lazy="select"
    )
    calendar_events = db.relationship(
        "CalendarEvent",
        back_populates="email",
        cascade="all, delete-orphan",
        lazy="select",
    )
    reminders = db.relationship(
        "Reminder", back_populates="email", cascade="all, delete-orphan", lazy="select"
    )

    @property
    def calendar_event(self):
        """Backward-compatible single calendar event accessor."""
        return self.calendar_events[0] if self.calendar_events else None

    def __init__(self, **kwargs):
        import json
        if "ai_deadlines" in kwargs and isinstance(kwargs["ai_deadlines"], (list, dict)):
            kwargs["ai_deadlines"] = json.dumps(kwargs["ai_deadlines"])
        if "ai_meeting_proposal" in kwargs and isinstance(kwargs["ai_meeting_proposal"], (list, dict)):
            kwargs["ai_meeting_proposal"] = json.dumps(kwargs["ai_meeting_proposal"])
        super().__init__(**kwargs)

    def to_dict(self, include_relations=False):
        """Serialise to a JSON-safe dictionary.

        Args:
            include_relations: If True, embed entities, tasks, events and reminders.
        """
        import json
        suggested_tasks = []
        if self.ai_suggested_tasks:
            try:
                suggested_tasks = json.loads(self.ai_suggested_tasks)
            except Exception:
                suggested_tasks = []

        suggested_event = None
        if self.ai_suggested_event:
            try:
                suggested_event = json.loads(self.ai_suggested_event)
            except Exception:
                suggested_event = None

        key_points = []
        if self.ai_key_points:
            try:
                key_points = json.loads(self.ai_key_points)
            except Exception:
                key_points = []

        waiting_for = None
        if self.ai_waiting_for:
            try:
                waiting_for = json.loads(self.ai_waiting_for)
            except Exception:
                waiting_for = None

        reasons = []
        if self.ai_reasons:
            try:
                reasons = json.loads(self.ai_reasons)
            except Exception:
                reasons = []

        data = {
            "id": self.id,
            "user_id": self.user_id,
            "connected_account_id": self.connected_account_id,
            "message_id": self.message_id,
            "provider_message_id": self.provider_message_id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "body_text": self.body_text,
            "body_html": self.body_html,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "recipients": self.recipients,
            "cc": self.cc,
            "bcc": self.bcc,
            "labels": self.labels,
            "has_attachments": self.has_attachments,
            "attachment_metadata": self.attachment_metadata,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "category": self.ai_category or self.category,
            "priority": self.ai_priority or self.priority,
            "sentiment": self.ai_sentiment or self.sentiment,
            "summary": self.ai_summary or self.summary,
            "auto_reply_required": self.auto_reply_required,
            "needs_human_review": self.needs_human_review,
            "confidence": self.ai_confidence_score if self.ai_confidence_score is not None else self.confidence,
            "spam_score": self.spam_score,
            "ai_status": self.ai_status or "pending",
            "ai_summary": self.ai_summary,
            "ai_category": self.ai_category,
            "ai_priority": self.ai_priority,
            "ai_sentiment": self.ai_sentiment,
            "ai_action_required": bool(self.ai_action_required),
            "ai_deadline": self.ai_deadline.isoformat() if self.ai_deadline else None,
            "ai_processed_at": self.ai_processed_at.isoformat() if self.ai_processed_at else None,
            "ai_model": self.ai_model,
            "ai_error": self.ai_error,
            "ai_suggested_tasks": suggested_tasks,
            "ai_suggested_event": suggested_event,
            "ai_importance_score": self.ai_importance_score,
            "ai_confidence_score": self.ai_confidence_score,
            "ai_key_points": key_points,
            "ai_waiting_for": waiting_for,
            "ai_next_action": self.ai_next_action,
            "ai_reasons": reasons,
            "ai_retry_count": self.ai_retry_count or 0,
            "ai_last_error": self.ai_last_error,
            "ai_deadlines": json.loads(self.ai_deadlines) if self.ai_deadlines else [],
            "ai_meeting_proposal": json.loads(self.ai_meeting_proposal) if self.ai_meeting_proposal else None,
            "reply_draft": self.reply_draft,
            "auto_reply_sent": self.auto_reply_sent,
            "sent_reply_id": self.sent_reply_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_relations:
            data["entities"] = [e.to_dict() for e in self.entities]
            data["tasks"] = [t.to_dict() for t in self.tasks]
            cal_events = [e.to_dict() for e in self.calendar_events]
            data["calendar_events"] = cal_events
            data["calendar_event"] = cal_events[0] if cal_events else None
            data["reminders"] = [r.to_dict() for r in self.reminders]
        return data

    def __repr__(self):
        return f"<EmailMessage {self.message_id}>"
