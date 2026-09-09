"""
SavedSearch model — stores parameterized user-saved search queries.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


class SavedSearch(db.Model):
    """User-saved search query bookmarks."""

    __tablename__ = "saved_searches"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(100), nullable=False)
    query = db.Column(db.String(500), nullable=False)
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
        db.UniqueConstraint("user_id", "name", name="uq_saved_searches_user_name"),
    )

    user = db.relationship("User", backref=db.backref("saved_searches", cascade="all, delete-orphan", lazy="dynamic"))

    def to_dict(self) -> dict:
        """Return a JSON-serializable dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "query": self.query,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<SavedSearch {self.id} '{self.name}'>"
