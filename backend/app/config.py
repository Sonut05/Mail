"""
Application configuration loaded from environment variables with production hardening.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def normalize_database_uri(uri: str | None) -> str:
    """Normalize PostgreSQL database URI to SQLAlchemy-compatible scheme."""
    if not uri:
        return "sqlite:///mail_assistant.db"
    # Heroku / AWS often supply 'postgres://', SQLAlchemy 1.4+ requires 'postgresql://'
    if uri.startswith("postgres://"):
        return uri.replace("postgres://", "postgresql://", 1)
    return uri


def get_engine_options(db_uri: str) -> dict:
    """Return hardened SQLAlchemy engine connection pool options for production databases."""
    if db_uri.startswith("sqlite"):
        return {}
    return {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        "pool_pre_ping": True,
    }


class Config:
    """Base configuration class. All values are sourced from environment
    variables with sensible development defaults."""

    # --- Flask Core ---
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = os.getenv("FLASK_ENV", "development") == "development"
    SESSION_COOKIE_NAME = "mailmild_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("true", "1")
    SESSION_COOKIE_PATH = "/"
    USE_PROXY_FIX = os.getenv("USE_PROXY_FIX", "false").lower() in ("true", "1")

    # --- Database ---
    _raw_db_uri = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:///mail_assistant.db")
    SQLALCHEMY_DATABASE_URI = normalize_database_uri(_raw_db_uri)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = get_engine_options(SQLALCHEMY_DATABASE_URI)
    CREATE_DB_TABLES_ON_STARTUP = os.getenv("CREATE_DB_TABLES_ON_STARTUP", "true").lower() in ("true", "1")

    # --- Google OAuth 2.0 ---
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:5000/api/auth/google/callback"
    )

    # --- Gemini AI ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    GEMINI_REQUEST_TIMEOUT = int(os.getenv("GEMINI_REQUEST_TIMEOUT", "30"))

    # --- Token Encryption ---
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

    # --- Frontend ---
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

    # --- Background AI Worker & Queue (Phase 6.1 / 6.2) ---
    AI_JOB_POLL_INTERVAL = float(os.getenv("AI_JOB_POLL_INTERVAL", "1.0"))
    AI_JOB_STALE_SECONDS = int(os.getenv("AI_JOB_STALE_SECONDS", "300"))
    AI_JOB_MAX_ATTEMPTS = int(os.getenv("AI_JOB_MAX_ATTEMPTS", "3"))
    AI_WORKER_ID = os.getenv("AI_WORKER_ID", f"worker-{os.getpid()}")
    AI_JOB_ALWAYS_EAGER = os.getenv("AI_JOB_ALWAYS_EAGER", "false").lower() in ("true", "1")
    AI_JOB_ASYNC_TESTING = os.getenv("AI_JOB_ASYNC_TESTING", "false").lower() in ("true", "1")


class ProductionConfig(Config):
    """Production configuration with strict security requirements."""

    DEBUG = False
    SESSION_COOKIE_SECURE = True
    CREATE_DB_TABLES_ON_STARTUP = False


def validate_production_config(cfg: dict | type[Config]) -> list[str]:
    """Validate that production environment has all mandatory security configurations.

    Returns a list of error descriptions (empty list if valid).
    """
    errors: list[str] = []

    def get_val(key: str, default: any = None) -> any:
        if isinstance(cfg, dict):
            return cfg.get(key, default)
        return getattr(cfg, key, default)

    env = get_val("ENV", os.getenv("FLASK_ENV", "development"))
    is_prod = env == "production"

    if is_prod:
        # Check SECRET_KEY
        secret = get_val("SECRET_KEY", "")
        if not secret or secret == "dev-secret-key-change-me" or len(secret) < 16:
            errors.append("Production requires a strong, unguessable SECRET_KEY (at least 16 characters).")

        # Check DEBUG
        if get_val("DEBUG", False):
            errors.append("DEBUG mode must be False in production.")

        # Check Database
        db_uri = get_val("SQLALCHEMY_DATABASE_URI", "")
        if not db_uri or db_uri.startswith("sqlite"):
            errors.append("Production requires a PostgreSQL database (DATABASE_URL starting with postgresql://). SQLite is not permitted.")

        # Check Encryption Key
        enc_key = get_val("ENCRYPTION_KEY", "")
        if not enc_key:
            errors.append("Production requires an ENCRYPTION_KEY for OAuth token security.")
        else:
            try:
                from cryptography.fernet import Fernet
                Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
            except Exception:
                errors.append("ENCRYPTION_KEY must be a valid 32-byte base64-encoded Fernet key.")

    return errors
