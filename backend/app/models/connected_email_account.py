"""
ConnectedEmailAccount model — stores OAuth credentials and metadata
for external email accounts (e.g. Gmail) connected by a MailMild user.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


class ConnectedEmailAccount(db.Model):
    """Represents a third-party email account (e.g. Gmail) connected to a MailMild user."""

    __tablename__ = "connected_email_accounts"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = db.Column(db.String(50), nullable=False, default="gmail")
    provider_account_id = db.Column(db.String(255), nullable=True, index=True)
    email_address = db.Column(db.String(255), nullable=False, index=True)

    # Securely encrypted OAuth tokens (never plain text)
    encrypted_access_token = db.Column(db.Text, nullable=False)
    encrypted_refresh_token = db.Column(db.Text, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)

    # Synchronization state
    sync_status = db.Column(db.String(50), nullable=False, default="idle")
    sync_progress = db.Column(db.Text, nullable=True)
    last_sync_at = db.Column(db.DateTime, nullable=True)
    history_id = db.Column(db.String(255), nullable=True)
    messages_synced = db.Column(db.Integer, nullable=False, default=0)

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
    user = db.relationship(
        "User",
        backref=db.backref("connected_accounts", cascade="all, delete-orphan", lazy="dynamic"),
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "provider", "email_address", name="uq_user_provider_email"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def is_token_expired(self) -> bool:
        """Check if the access token has expired."""
        if not self.token_expiry:
            return False
        # Treat as expired if within 60 seconds of expiry
        expiry = self.token_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expiry

    def to_safe_dict(self) -> dict:
        """Return safe account information for frontend/API serialization.
        
        CRITICAL: Never exposes access tokens, refresh tokens, or encrypted token strings.
        """
        from app.models.email_message import EmailMessage
        total_in_db = EmailMessage.query.filter_by(connected_account_id=self.id).count() if self.id else 0
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "email_address": self.email_address,
            "provider_account_id": self.provider_account_id,
            "sync_status": self.sync_status,
            "sync_progress": self.sync_progress,
            "history_id": self.history_id,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "messages_synced": total_in_db or self.messages_synced or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<ConnectedEmailAccount {self.provider}:{self.email_address} (User: {self.user_id})>"
