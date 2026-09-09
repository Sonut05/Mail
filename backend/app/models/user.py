"""
User model — stores OAuth credentials and profile info.
"""

import uuid
from datetime import datetime, timezone

from app.extensions import db


class User(db.Model):
    """Represents an authenticated user with encrypted OAuth tokens."""

    __tablename__ = "users"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    contact_no = db.Column(db.String(50), nullable=True)
    provider = db.Column(db.String(50), nullable=False, default="google")
    password_hash = db.Column(db.String(255), nullable=True)
    encrypted_access_token = db.Column(db.Text, nullable=True)
    encrypted_refresh_token = db.Column(db.Text, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    target_role = db.Column(db.String(255), nullable=True)
    min_salary = db.Column(db.Integer, nullable=True)
    max_salary = db.Column(db.Integer, nullable=True)
    resume_text = db.Column(db.Text, nullable=True)
    resume_parsed_json = db.Column(db.Text, nullable=True)
    resume_profiles = db.Column(db.Text, nullable=True)
    picture = db.Column(db.String(511), nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    # Relationships
    emails = db.relationship(
        "EmailMessage", back_populates="user", cascade="all, delete-orphan", lazy="dynamic"
    )
    tasks = db.relationship(
        "Task", back_populates="user", cascade="all, delete-orphan", lazy="dynamic"
    )
    calendar_events = db.relationship(
        "CalendarEvent", back_populates="user", cascade="all, delete-orphan", lazy="dynamic"
    )
    preference = db.relationship(
        "UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    feedback_signals = db.relationship(
        "UserFeedbackSignal", back_populates="user", cascade="all, delete-orphan", lazy="dynamic"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self):
        """Return a JSON-safe dictionary (never exposes tokens)."""
        import json
        parsed_resume = None
        if self.resume_parsed_json:
            try:
                parsed_resume = json.loads(self.resume_parsed_json)
            except Exception:
                pass

        profiles = []
        if self.resume_profiles:
            try:
                profiles = json.loads(self.resume_profiles)
            except Exception:
                pass

        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
            "contact_no": self.contact_no,
            "provider": self.provider,
            "target_role": self.target_role,
            "min_salary": self.min_salary,
            "max_salary": self.max_salary,
            "resume_text": self.resume_text,
            "resume_parsed_json": parsed_resume,
            "resume_profiles": profiles,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<User {self.email}>"
