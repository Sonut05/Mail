"""
Routes package — central blueprint registration.
"""

from __future__ import annotations

from flask import Flask

from app.routes.auth import auth_bp
from app.routes.emails import emails_bp
from app.routes.tasks import tasks_bp
from app.routes.calendar import calendar_bp
from app.routes.dashboard import dashboard_bp
from app.routes.webhooks import webhooks_bp
from app.routes.resume import resume_bp
from app.routes.mail_accounts import mail_bp
from app.routes.preferences import preferences_bp
from app.routes.threads import threads_bp
from app.routes.contacts import contacts_bp
from app.routes.actions import actions_bp
from app.routes.notifications import notifications_bp
from app.routes.digest import digest_bp
from app.routes.analytics import analytics_bp
from app.routes.searches import searches_bp


def register_blueprints(app: Flask) -> None:
    """Register every blueprint with the Flask application.

    Args:
        app: The Flask application instance.
    """
    app.register_blueprint(auth_bp)
    app.register_blueprint(emails_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(resume_bp)
    app.register_blueprint(mail_bp)
    app.register_blueprint(preferences_bp)
    app.register_blueprint(threads_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(actions_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(digest_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(searches_bp)

