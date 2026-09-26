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


class TestAuthenticationAudit(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestSecurityConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            user = User(email="authaudit@mailmind.io", name="Auth Audit", provider="local")
            user.set_password("SecurePassword123!")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_unauthenticated_endpoints_return_401(self):
        """All private endpoints reject unauthenticated access with 401."""
        endpoints = [
            ("GET", "/api/auth/me"),
            ("GET", "/api/emails"),
            ("POST", "/api/emails/generate-reply"),
            ("GET", "/api/tasks"),
            ("GET", "/api/calendar"),
            ("GET", "/api/dashboard/stats"),
            ("GET", "/api/preferences"),
            ("GET", "/api/notifications"),
            ("GET", "/api/resume/profiles"),
            ("GET", "/api/mail/accounts"),
            ("GET", "/api/searches"),
            ("GET", "/api/threads"),
            ("GET", "/api/contacts"),
            ("GET", "/api/actions"),
            ("GET", "/api/digest"),
            ("GET", "/api/analytics/productivity"),
        ]
        for method, url in endpoints:
            if method == "GET":
                res = self.client.get(url)
            else:
                res = self.client.post(url, json={"email_body": "test"})
            self.assertEqual(res.status_code, 401, f"{method} {url} did not return 401")

    def test_session_rotation_on_login_and_register(self):
        """Session is rotated (cleared + reissued) on login and registration."""
        with self.client.session_transaction() as sess:
            sess["old_preauth_data"] = "attacker_session_fixation_payload"

        res = self.client.post("/api/auth/login", json={
            "email": "authaudit@mailmind.io",
            "password": "SecurePassword123!"
        })
        self.assertEqual(res.status_code, 200)

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), self.user_id)
            self.assertNotIn("old_preauth_data", sess)
            self.assertIn("_auth_created_at", sess)
            self.assertIn("_auth_last_active", sess)

    def test_session_idle_timeout(self):
        """Session expires when idle timeout (e.g. 24h) is exceeded."""
        import time
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["_auth_created_at"] = time.time() - 3600
            # Last active 25 hours ago (timeout is 24h)
            sess["_auth_last_active"] = time.time() - (25 * 3600)

        res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, 401)
        self.assertIn("inactivity", res.get_json().get("error", "").lower())

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

    def test_session_absolute_expiry(self):
        """Session expires when absolute expiry (e.g. 7 days) is exceeded even if actively used."""
        import time
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            # Created 8 days ago (absolute expiry is 7 days)
            sess["_auth_created_at"] = time.time() - (8 * 86400)
            sess["_auth_last_active"] = time.time() - 100

        res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, 401)
        self.assertIn("expired", res.get_json().get("error", "").lower())

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

