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


class TestAuthorizationAccessControlAudit(unittest.TestCase):
    def setUp(self):
        from app.models import EmailMessage, Task, CalendarEvent, Notification, ConnectedEmailAccount
        from datetime import datetime, timezone, timedelta

        self.app = create_app(TestSecurityConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            # User A
            self.user_a = User(email="user_a@mailmind.io", name="User Alpha", provider="local")
            self.user_a.set_password("PasswordA123!")
            # User B
            self.user_b = User(email="user_b@mailmind.io", name="User Beta", provider="local")
            self.user_b.set_password("PasswordB123!")
            db.session.add_all([self.user_a, self.user_b])
            db.session.commit()

            from app.services.encryption import encrypt_token
            # Connected account for User B
            self.acc_b = ConnectedEmailAccount(
                user_id=self.user_b.id,
                email_address="user_b@gmail.com",
                provider="gmail",
                provider_account_id="b_acc_123",
                encrypted_access_token=encrypt_token("mock_b_token"),
            )
            db.session.add(self.acc_b)
            db.session.commit()

            # Email belonging to User B
            self.email_b = EmailMessage(
                user_id=self.user_b.id,
                connected_account_id=self.acc_b.id,
                message_id="msg_b_1",
                subject="Confidential B",
                body_text="Secret content of User B",
                from_address="boss@company.com",
                to_address="user_b@gmail.com",
            )
            # Task belonging to User B
            self.task_b = Task(
                user_id=self.user_b.id,
                task_title="Secret Task B",
                status="pending",
                priority="high",
            )
            # Calendar event belonging to User B
            now = datetime.now(timezone.utc)
            self.event_b = CalendarEvent(
                user_id=self.user_b.id,
                title="Secret Meeting B",
                start_date_time=now + timedelta(hours=2),
                end_date_time=now + timedelta(hours=3),
                timezone="UTC",
            )
            # Notification belonging to User B
            self.notif_b = Notification(
                user_id=self.user_b.id,
                type="IMPORTANT_EMAIL",
                title="Secret Notif B",
                message="User B message",
            )
            db.session.add_all([self.email_b, self.task_b, self.event_b, self.notif_b])
            db.session.commit()

            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id
            self.email_b_id = self.email_b.id
            self.task_b_id = self.task_b.id
            self.event_b_id = self.event_b.id
            self.notif_b_id = self.notif_b.id
            self.acc_b_id = self.acc_b.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login_as(self, user_id):
        import time
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["_auth_created_at"] = time.time()
            sess["_auth_last_active"] = time.time()

    def test_user_a_cannot_read_or_mutate_user_b_email(self):
        """User A must get 403 or 404 when attempting to access User B's email."""
        self._login_as(self.user_a_id)

        # GET User B email
        res = self.client.get(f"/api/emails/{self.email_b_id}")
        self.assertIn(res.status_code, (403, 404))

        # POST analyze User B email
        res = self.client.post(f"/api/emails/{self.email_b_id}/analyze")
        self.assertIn(res.status_code, (403, 404))

        # POST approve reply User B email
        res = self.client.post(f"/api/emails/{self.email_b_id}/approve")
        self.assertIn(res.status_code, (403, 404))

        # POST discard reply User B email
        res = self.client.post(f"/api/emails/{self.email_b_id}/discard")
        self.assertIn(res.status_code, (403, 404))

        # POST mark read User B email
        res = self.client.post(f"/api/emails/{self.email_b_id}/read")
        self.assertIn(res.status_code, (403, 404))

    def test_user_a_cannot_read_or_mutate_user_b_task(self):
        """User A must get 403 or 404 when accessing or mutating User B's task."""
        self._login_as(self.user_a_id)

        # GET User B task
        res = self.client.get(f"/api/tasks/{self.task_b_id}")
        self.assertIn(res.status_code, (403, 404))

        # PATCH User B task
        res = self.client.patch(f"/api/tasks/{self.task_b_id}", json={"title": "Hacked Title"})
        self.assertIn(res.status_code, (403, 404))

        # COMPLETE User B task
        res = self.client.post(f"/api/tasks/{self.task_b_id}/complete")
        self.assertIn(res.status_code, (403, 404))

        # DELETE User B task
        res = self.client.delete(f"/api/tasks/{self.task_b_id}")
        self.assertIn(res.status_code, (403, 404))

    def test_user_a_cannot_link_task_to_user_b_email(self):
        """User A cannot create a task linked to User B's email (IDOR)."""
        self._login_as(self.user_a_id)
        res = self.client.post("/api/tasks", json={
            "task_title": "Malicious task",
            "email_id": self.email_b_id,
        })
        self.assertEqual(res.status_code, 403)

    def test_user_a_cannot_read_or_mutate_user_b_calendar_event(self):
        """User A must get 403 or 404 when accessing or mutating User B's calendar event."""
        self._login_as(self.user_a_id)

        # GET User B event
        res = self.client.get(f"/api/calendar/{self.event_b_id}")
        self.assertIn(res.status_code, (403, 404))

        # PUT User B event
        res = self.client.put(f"/api/calendar/{self.event_b_id}", json={"title": "Hacked Meeting"})
        self.assertIn(res.status_code, (403, 404))

        # DELETE User B event
        res = self.client.delete(f"/api/calendar/{self.event_b_id}")
        self.assertIn(res.status_code, (403, 404))

    def test_user_a_cannot_link_calendar_event_to_user_b_email(self):
        """User A cannot create a calendar event linked to User B's email (IDOR)."""
        self._login_as(self.user_a_id)
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        res = self.client.post("/api/calendar", json={
            "title": "Malicious Event",
            "email_id": self.email_b_id,
            "start": (now + timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=2)).isoformat(),
        })
        self.assertEqual(res.status_code, 403)

    def test_user_a_cannot_access_user_b_notification(self):
        """User A must get 403 or 404 when accessing or deleting User B's notification."""
        self._login_as(self.user_a_id)

        # GET User B notification
        res = self.client.get(f"/api/notifications/{self.notif_b_id}")
        self.assertIn(res.status_code, (403, 404))

        # DELETE User B notification
        res = self.client.delete(f"/api/notifications/{self.notif_b_id}")
        self.assertIn(res.status_code, (403, 404))

    def test_user_a_cannot_trigger_sync_on_user_b_account(self):
        """User A must get 403 when trying to sync User B's email account."""
        self._login_as(self.user_a_id)
        res = self.client.post("/api/mail/sync", json={"account_id": self.acc_b_id})
        self.assertEqual(res.status_code, 403)


class RateLimitTestConfig(Config):
    TESTING = True
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = "memory://"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-rate-limit-secret-key-12345"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "123456789-testclient.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "GOCSPX-testclientsecret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"


class TestRateLimiting(unittest.TestCase):
    """Regression tests verifying endpoint rate limiting enforcement."""

    def setUp(self):
        self.app = create_app(RateLimitTestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def test_auth_login_rate_limiting_enforced(self):
        """POST /api/auth/login must throttle after 5 requests per minute with HTTP 429."""
        responses = []
        for _ in range(7):
            res = self.client.post("/api/auth/login", json={
                "email": "attacker@example.com",
                "password": "wrongpassword"
            })
            responses.append(res.status_code)

        # First 5 attempts should return 401 (invalid creds)
        self.assertEqual(responses[:5], [401, 401, 401, 401, 401])
        # 6th and 7th attempts must be rate limited with 429
        self.assertEqual(responses[5], 429)
        self.assertEqual(responses[6], 429)

        # Verify 429 response structure
        last_res = self.client.post("/api/auth/login", json={
            "email": "attacker@example.com",
            "password": "wrongpassword"
        })
        self.assertEqual(last_res.status_code, 429)
        data = last_res.get_json()
        self.assertEqual(data.get("error"), "Too Many Requests")
        self.assertIn("Rate limit exceeded", data.get("message", ""))

    def test_auth_register_rate_limiting_enforced(self):
        """POST /api/auth/register must throttle after 5 requests per minute with HTTP 429."""
        responses = []
        for i in range(7):
            res = self.client.post("/api/auth/register", json={
                "email": f"user{i}@example.com",
                "password": "password123",
                "name": f"User {i}"
            })
            responses.append(res.status_code)

        # 6th and 7th attempts must be rate limited with 429
        self.assertIn(429, responses)
        self.assertEqual(responses[5], 429)
        self.assertEqual(responses[6], 429)

    def test_rate_limiting_disabled_in_standard_testing_mode(self):
        """Standard test config (TESTING=True, RATELIMIT_ENABLED not explicitly set) must not throttle."""
        default_test_app = create_app(TestSecurityConfig)
        client = default_test_app.test_client()

        statuses = []
        for _ in range(12):
            res = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
            statuses.append(res.status_code)

        # All requests should return 401 (not 429)
        self.assertTrue(all(s == 401 for s in statuses))


