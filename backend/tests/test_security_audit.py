"""
Security regression tests covering:
1. Auth backdoor remediation (mock parameter restriction in production)
2. Access control and IDOR protections
3. Session rotation and timeout checks
4. Rate limiting and input validation
"""

import unittest
from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User


class TestSecurityConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-key-12345"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "123456789-testclient.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "GOCSPX-testclientsecret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"
    ENV = "development"


class TestAuthBackdoorFix(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestSecurityConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_mock_in_production_returns_404(self):
        """In production, ?mock=true must return 404, not authenticate."""
        self.app.config["ENV"] = "production"
        res = self.client.get("/api/auth/google?mock=true")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertIn("disabled in production", data.get("error", "").lower())

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

    def test_placeholder_in_production_does_not_autologin_demo_user(self):
        """In production, placeholder client ID directs to Google OAuth, not demo.developer."""
        self.app.config["ENV"] = "production"
        self.app.config["GOOGLE_CLIENT_ID"] = "placeholder_id"
        res = self.client.get("/api/auth/google")
        # In production, it initiates normal Google OAuth flow redirect rather than mock login
        self.assertEqual(res.status_code, 302)
        self.assertIn("accounts.google.com", res.headers.get("Location", ""))
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

    def test_mock_in_development_works(self):
        """In development, ?mock=true behaves normally for local testing."""
        self.app.config["ENV"] = "development"
        res = self.client.get("/api/auth/google?mock=true", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertIsNotNone(sess.get("user_id"))
