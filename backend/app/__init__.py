"""
Flask application factory with Phase 6.2 production hardening.

Usage::

    from app import create_app
    app = create_app()
"""

from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone

from flask import Flask, request, g, jsonify
import sqlalchemy as sa

from app.config import Config, validate_production_config
from app.extensions import db, migrate, cors
from app.routes import register_blueprints


def create_app(config_class: type = Config) -> Flask:
    """Create and configure the Flask application.

    Args:
        config_class: A configuration class (defaults to ``Config``).

    Returns:
        A fully configured Flask application instance.
    """
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
    app = Flask(
        __name__,
        static_folder=frontend_dir if os.path.exists(frontend_dir) else None,
        static_url_path=""
    )
    app.config.from_object(config_class)

    # ── Production Configuration Validation ─────────────────
    if app.config.get("ENV") == "production" or os.getenv("FLASK_ENV") == "production":
        config_errors = validate_production_config(app.config)
        if config_errors:
            raise RuntimeError(f"Production configuration validation failed: {'; '.join(config_errors)}")

    # ── Reverse Proxy Header Fix (Requirement 20) ───────────
    if app.config.get("USE_PROXY_FIX", False):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # ── Extensions ──────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    allowed_origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        app.config.get("FRONTEND_URL", "http://localhost:3000"),
    ]
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": list(set(allowed_origins))}},
        supports_credentials=True,
    )

    # ── Blueprints ──────────────────────────────────────────
    register_blueprints(app)

    # ── Database Initialization Guard ───────────────────────
    # In production, migrations manage tables. db.create_all is strictly for SQLite local dev/tests.
    with app.app_context():
        from app import models  # noqa: F401 — force model registration
        if app.config.get("CREATE_DB_TABLES_ON_STARTUP", True):
            db.create_all()

    # ── Correlation ID and Structured Logging Middleware ───
    @app.before_request
    def before_request_correlation():
        req_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        if not req_id:
            req_id = f"req-{uuid.uuid4().hex[:12]}"
        g.request_id = req_id

    @app.after_request
    def after_request_security_and_correlation(response):
        if hasattr(g, "request_id"):
            response.headers["X-Request-ID"] = g.request_id
        # Production security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https:; "
            "connect-src 'self' http://localhost:* ws://localhost:* https://*.googleapis.com; "
            "frame-ancestors 'self';"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # ── Standardized Safe Error Handlers ───────────────────
    @app.errorhandler(400)
    def handle_bad_request(err):
        return jsonify({
            "error": "Bad request",
            "message": str(getattr(err, "description", "Malformed request parameters")),
            "request_id": getattr(g, "request_id", None)
        }), 400

    @app.errorhandler(404)
    def handle_not_found(err):
        return jsonify({
            "error": "Not found",
            "message": "The requested resource was not found",
            "request_id": getattr(g, "request_id", None)
        }), 404

    @app.errorhandler(500)
    def handle_internal_error(err):
        req_id = getattr(g, "request_id", "unknown")
        app.logger.error("Internal Server Error [%s]: %s", req_id, err)
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred. Please contact support.",
            "request_id": req_id
        }), 500

    # ── Health-check & Readiness Endpoints (Requirement 4) ──
    @app.route("/health")
    @app.route("/api/health")
    def health():
        """Liveness probe: verifies process is alive and responsive."""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200

    @app.route("/ready")
    @app.route("/api/ready")
    def ready():
        """Readiness probe: verifies database connectivity and core requirements."""
        try:
            db.session.execute(sa.text("SELECT 1"))
            # Check mandatory secret key
            if not app.config.get("SECRET_KEY"):
                return jsonify({
                    "status": "unready",
                    "database": "connected",
                    "reason": "Missing SECRET_KEY configuration"
                }), 503

            return jsonify({
                "status": "ready",
                "database": "connected",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }), 200
        except Exception as exc:
            app.logger.error("Readiness probe database connection check failed: %s", exc)
            return jsonify({
                "status": "unready",
                "database": "unavailable",
                "reason": "Database query failed or timed out"
            }), 503

    # ── Queue Observability Endpoints (Requirement 5) ──────
    @app.route("/api/queue/health")
    @app.route("/api/queue/stats")
    def queue_health():
        """Queue observability: return safe, aggregated queue health metrics."""
        from app.services.job_queue_service import get_queue_metrics
        try:
            metrics = get_queue_metrics(stale_timeout_seconds=app.config.get("AI_JOB_STALE_SECONDS", 300))
            return jsonify({
                "status": "healthy",
                "queue": metrics,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }), 200
        except Exception as exc:
            app.logger.error("Queue observability probe failed: %s", exc)
            return jsonify({
                "status": "error",
                "message": "Failed to collect queue metrics"
            }), 500

    # ── Documentation download endpoint ───────────────────────
    @app.route("/api/docs/readme/download")
    def download_readme():
        """Download the repository's README.md file."""
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        readme_path = os.path.join(root_dir, "README.md")
        if os.path.exists(readme_path):
            from flask import send_file
            return send_file(
                readme_path,
                as_attachment=True,
                download_name="README.md",
                mimetype="text/markdown"
            )
        return {"error": "README.md not found"}, 404

    # ── Frontend Static Assets Serving ────────────────────────
    if app.static_folder:
        from flask import send_from_directory
        
        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_frontend(path):
            if path.startswith("api/") or path in ("health", "ready"):
                return {"error": "Not Found"}, 404
            
            if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
                return send_from_directory(app.static_folder, path)
            else:
                return send_from_directory(app.static_folder, "index.html")

    return app
