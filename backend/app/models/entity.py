"""
Entity model — named entities (people, orgs, dates, etc.) extracted by the AI.
"""

import uuid

from app.extensions import db


class Entity(db.Model):
    """A named entity extracted from an email (person, org, date, etc.)."""

    __tablename__ = "entities"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email_id = db.Column(
        db.String(36),
        db.ForeignKey("email_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)

    # Relationships
    email = db.relationship("EmailMessage", back_populates="entities")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self):
        """Return a JSON-safe dictionary."""
        return {
            "id": self.id,
            "email_id": self.email_id,
            "type": self.type,
            "value": self.value,
        }

    def __repr__(self):
        return f"<Entity {self.type}: {self.value[:30]}>"
