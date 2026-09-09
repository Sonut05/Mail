"""
Phase 1 Tests — Google OAuth 2.0 connection, state CSRF validation,
ConnectedEmailAccount model, token encryption, and multi-user security.
"""

import unittest
from unittest.mock import patch, MagicMock
import urllib.parse
from datetime import datetime, timezone

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.services.encryption import decrypt_token


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret-key-12345"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "123456789-testclient.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "GOCSPX-testclientsecret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"


class TestPhase1GmailOAuth(unittest.TestCase):

    def setUp(self):
        # Configure test app with in-memory SQLite and test secrets
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            # Create test user A
            self.user_a = User(
                email="user_a@mailmild.com",
                name="User Alpha",
                provider="local",
            )
            self.user_a.set_password("PasswordA123!")

            # Create test user B
            self.user_b = User(
                email="user_b@mailmild.com",
                name="User Beta",
                provider="local",
            )
            self.user_b.set_password("PasswordB123!")

            db.session.add_all([self.user_a, self.user_b])
            db.session.commit()

            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    # ──────────────────────────────────────────────────────────
    # 1. OAuth Initiation Tests
    # ──────────────────────────────────────────────────────────

    def test_unauthenticated_user_can_start_oauth(self):
        """Unauthenticated user can start OAuth flow to log in or connect account."""
        res = self.client.get("/api/auth/google")
        self.assertEqual(res.status_code, 302)
        location = res.headers.get("Location", "")
        self.assertTrue(location.startswith("https://accounts.google.com/o/oauth2/auth"))

    def test_authenticated_user_generates_valid_oauth_url(self):
        """Authenticated user receives redirect to Google with exact Phase 1 scopes."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id

        res = self.client.get("/api/auth/google")
        self.assertEqual(res.status_code, 302)
        location = res.headers.get("Location", "")
        self.assertTrue(location.startswith("https://accounts.google.com/o/oauth2/auth"))

        parsed = urllib.parse.urlparse(location)
        params = urllib.parse.parse_qs(parsed.query)

        # Verify client ID and redirect URI
        self.assertEqual(params.get("client_id", [""])[0], "123456789-testclient.apps.googleusercontent.com")
        self.assertEqual(params.get("redirect_uri", [""])[0], "http://localhost:5000/api/auth/google/callback")
        self.assertEqual(params.get("access_type", [""])[0], "offline")

        # Verify exact scopes: must have gmail.readonly, must NOT have gmail.send
        scope_str = params.get("scope", [""])[0]
        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", scope_str)
        self.assertIn("https://www.googleapis.com/auth/userinfo.email", scope_str)
        self.assertNotIn("https://www.googleapis.com/auth/gmail.send", scope_str)

        # Verify state is stored in session
        with self.client.session_transaction() as sess:
            self.assertIn("oauth_state", sess)
            self.assertEqual(sess["oauth_state"], params.get("state", [""])[0])

    # ──────────────────────────────────────────────────────────
    # 2. CSRF State Protection Tests
    # ──────────────────────────────────────────────────────────

    def test_callback_fails_with_missing_state(self):
        """Callback with no state parameter must return 400."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id
            sess["oauth_state"] = "valid-session-state-123"

        res = self.client.get("/api/auth/google/callback?code=fake-auth-code")
        self.assertEqual(res.status_code, 400)
        self.assertIn("CSRF protection failed", res.get_json().get("error", ""))

    def test_callback_fails_with_tampered_state(self):
        """Callback with mismatched state parameter must return 400."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id
            sess["oauth_state"] = "secret-stored-state"

        res = self.client.get("/api/auth/google/callback?code=fake-auth-code&state=attacker-tampered-state")
        self.assertEqual(res.status_code, 400)
        self.assertIn("CSRF protection failed", res.get_json().get("error", ""))

    def test_callback_handles_google_denial_gracefully(self):
        """Callback handles error=access_denied by redirecting to settings."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id

        res = self.client.get("/api/auth/google/callback?error=access_denied")
        self.assertEqual(res.status_code, 302)
        self.assertIn("error=access_denied", res.headers.get("Location", ""))

    # ──────────────────────────────────────────────────────────
    # 3. Successful Callback & Token Encryption Tests
    # ──────────────────────────────────────────────────────────

    @patch("app.routes.auth.build_service")
    @patch("app.routes.auth._build_flow")
    def test_successful_oauth_creates_connected_account(self, mock_build_flow, mock_build_service):
        """Mock successful code exchange and verify ConnectedEmailAccount is securely created."""
        # 1. Setup mock flow
        mock_flow = MagicMock()
        mock_credentials = MagicMock()
        mock_credentials.token = "mock-plain-access-token-999"
        mock_credentials.refresh_token = "mock-plain-refresh-token-888"
        mock_credentials.expiry = datetime(2027, 1, 1, tzinfo=timezone.utc)
        mock_flow.credentials = mock_credentials
        mock_build_flow.return_value = mock_flow

        # 2. Setup mock googleapiclient oauth2 userinfo
        mock_oauth2 = MagicMock()
        mock_oauth2.userinfo().get().execute.return_value = {
            "id": "google-account-id-777",
            "email": "personal.gmail@gmail.com",
            "picture": "https://example.com/avatar.png",
        }
        mock_build_service.return_value = mock_oauth2

        # 3. Perform callback request with valid state
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id
            sess["oauth_state"] = "test-valid-state-abc"

        res = self.client.get("/api/auth/google/callback?code=mock-code&state=test-valid-state-abc")
        self.assertEqual(res.status_code, 302)
        self.assertIn("connected=gmail", res.headers.get("Location", ""))

        # 4. Inspect SQLite database record
        with self.app.app_context():
            acc = ConnectedEmailAccount.query.filter_by(
                user_id=self.user_a_id,
                email_address="personal.gmail@gmail.com"
            ).first()

            self.assertIsNotNone(acc)
            self.assertEqual(acc.provider, "gmail")
            self.assertEqual(acc.provider_account_id, "google-account-id-777")
            self.assertEqual(acc.sync_status, "idle")

            # CRITICAL SECURITY VERIFICATION:
            # Tokens MUST NOT be stored in plain text
            self.assertNotEqual(acc.encrypted_access_token, "mock-plain-access-token-999")
            self.assertNotEqual(acc.encrypted_refresh_token, "mock-plain-refresh-token-888")

            # Must decrypt cleanly with encryption service
            self.assertEqual(decrypt_token(acc.encrypted_access_token), "mock-plain-access-token-999")
            self.assertEqual(decrypt_token(acc.encrypted_refresh_token), "mock-plain-refresh-token-888")

            # Verify MailMild User identity was preserved
            user = db.session.get(User, self.user_a_id)
            self.assertEqual(user.email, "user_a@mailmild.com")

    @patch("app.routes.auth.build_service")
    @patch("app.routes.auth._build_flow")
    def test_duplicate_connection_updates_existing_record(self, mock_build_flow, mock_build_service):
        """Connecting the same Google account again updates the existing record instead of duplicating."""
        mock_flow = MagicMock()
        mock_credentials = MagicMock()
        mock_credentials.token = "updated-access-token-111"
        mock_credentials.refresh_token = "updated-refresh-token-222"
        mock_credentials.expiry = datetime(2028, 1, 1, tzinfo=timezone.utc)
        mock_flow.credentials = mock_credentials
        mock_build_flow.return_value = mock_flow

        mock_oauth2 = MagicMock()
        mock_oauth2.userinfo().get().execute.return_value = {
            "id": "google-account-id-777",
            "email": "personal.gmail@gmail.com",
        }
        mock_build_service.return_value = mock_oauth2

        # Pre-seed existing account
        with self.app.app_context():
            from app.services.encryption import encrypt_token
            existing_acc = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                provider_account_id="google-account-id-777",
                email_address="personal.gmail@gmail.com",
                encrypted_access_token=encrypt_token("old-token"),
            )
            db.session.add(existing_acc)
            db.session.commit()

        # Connect again
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id
            sess["oauth_state"] = "state-update-test"

        res = self.client.get("/api/auth/google/callback?code=mock-code-2&state=state-update-test")
        self.assertEqual(res.status_code, 302)

        with self.app.app_context():
            count = ConnectedEmailAccount.query.filter_by(
                user_id=self.user_a_id,
                email_address="personal.gmail@gmail.com"
            ).count()
            self.assertEqual(count, 1)  # No duplicate!

            acc = ConnectedEmailAccount.query.filter_by(
                user_id=self.user_a_id,
                email_address="personal.gmail@gmail.com"
            ).first()
            self.assertEqual(decrypt_token(acc.encrypted_access_token), "updated-access-token-111")

    @patch("app.routes.auth.build_service")
    @patch("app.routes.auth._build_flow")
    def test_callback_succeeds_when_scopes_are_relaxed_with_extra_scopes(self, mock_build_flow, mock_build_service):
        """Callback succeeds without ScopeChangedError when Google returns previously granted extra scopes."""
        import os
        self.assertEqual(os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE"), "1")

        mock_flow = MagicMock()
        mock_credentials = MagicMock()
        mock_credentials.token = "valid-token-relaxed"
        mock_credentials.refresh_token = "valid-refresh-relaxed"
        mock_credentials.expiry = datetime(2028, 1, 1, tzinfo=timezone.utc)
        mock_flow.credentials = mock_credentials
        mock_build_flow.return_value = mock_flow

        mock_oauth2 = MagicMock()
        mock_oauth2.userinfo().get().execute.return_value = {
            "id": "google-account-id-999",
            "email": "user_with_extra_scopes@gmail.com",
        }
        mock_build_service.return_value = mock_oauth2

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id
            sess["oauth_state"] = "state-relaxed-test"

        res = self.client.get("/api/auth/google/callback?code=mock-code-relaxed&state=state-relaxed-test")
        self.assertEqual(res.status_code, 302)
        self.assertIn("connected=gmail", res.headers.get("Location", ""))

    @patch("app.routes.auth.build_service")
    @patch("app.routes.auth._build_flow")
    def test_callback_succeeds_with_signed_state_even_if_session_cookie_lost(self, mock_build_flow, mock_build_service):
        """Callback succeeds via cryptographic signature check even if session cookie was dropped."""
        from itsdangerous import URLSafeTimedSerializer

        # Generate a valid signed state token containing user_a_id
        serializer = URLSafeTimedSerializer(self.app.config["SECRET_KEY"], salt="oauth-state")
        signed_state = serializer.dumps({"nonce": "test-nonce-123", "user_id": self.user_a_id})

        mock_flow = MagicMock()
        mock_credentials = MagicMock()
        mock_credentials.token = "valid-token-no-cookie"
        mock_credentials.refresh_token = "valid-refresh-no-cookie"
        mock_credentials.expiry = datetime(2028, 1, 1, tzinfo=timezone.utc)
        mock_flow.credentials = mock_credentials
        mock_build_flow.return_value = mock_flow

        mock_oauth2 = MagicMock()
        mock_oauth2.userinfo().get().execute.return_value = {
            "id": "google-sub-nocookie",
            "email": "user_nocookie@gmail.com",
        }
        mock_build_service.return_value = mock_oauth2

        # Client has NO session cookies (session is completely empty)
        res = self.client.get(f"/api/auth/google/callback?code=mock-code&state={signed_state}")
        self.assertEqual(res.status_code, 302)
        # Verify user_a_id from signed state was honored and redirected to settings
        self.assertIn("connected=gmail", res.headers.get("Location", ""))

    # ──────────────────────────────────────────────────────────
    # 4. Accounts API & Multi-User Security Tests
    # ──────────────────────────────────────────────────────────

    def test_get_accounts_never_exposes_tokens(self):
        """GET /api/mail/accounts must return safe metadata and NEVER tokens."""
        with self.app.app_context():
            from app.services.encryption import encrypt_token
            acc = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                provider_account_id="sub-123",
                email_address="user_a_gmail@gmail.com",
                encrypted_access_token=encrypt_token("super-secret-access-token"),
                encrypted_refresh_token=encrypt_token("super-secret-refresh-token"),
            )
            db.session.add(acc)
            db.session.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id

        res = self.client.get("/api/mail/accounts")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        accounts = data.get("accounts", [])
        self.assertEqual(len(accounts), 1)

        first_acc = accounts[0]
        self.assertEqual(first_acc["email_address"], "user_a_gmail@gmail.com")
        self.assertEqual(first_acc["provider"], "gmail")

        # CRITICAL SECURITY AUDIT:
        # Verify no token fields exist in response
        self.assertNotIn("encrypted_access_token", first_acc)
        self.assertNotIn("encrypted_refresh_token", first_acc)
        self.assertNotIn("access_token", first_acc)
        self.assertNotIn("refresh_token", first_acc)
        self.assertNotIn("super-secret", str(data))

    def test_multi_user_isolation(self):
        """User B must never be able to see or access User A's connected email accounts."""
        with self.app.app_context():
            from app.services.encryption import encrypt_token
            acc_a = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                email_address="user_a_private@gmail.com",
                encrypted_access_token=encrypt_token("token-a"),
            )
            acc_b = ConnectedEmailAccount(
                user_id=self.user_b_id,
                provider="gmail",
                email_address="user_b_private@gmail.com",
                encrypted_access_token=encrypt_token("token-b"),
            )
            db.session.add_all([acc_a, acc_b])
            db.session.commit()

        # Log in as User B
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_b_id

        res = self.client.get("/api/mail/accounts")
        self.assertEqual(res.status_code, 200)
        accounts = res.get_json().get("accounts", [])

        # User B should only see User B's account
        emails = [a["email_address"] for a in accounts]
        self.assertIn("user_b_private@gmail.com", emails)
        self.assertNotIn("user_a_private@gmail.com", emails)

    # ──────────────────────────────────────────────────────────
    # 5. Disconnect Endpoint Tests
    # ──────────────────────────────────────────────────────────

    def test_disconnect_removes_connected_account_only(self):
        """POST /api/mail/disconnect removes ConnectedEmailAccount and does NOT delete MailMild user."""
        with self.app.app_context():
            from app.services.encryption import encrypt_token
            acc = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                email_address="user_a_to_disconnect@gmail.com",
                encrypted_access_token=encrypt_token("mock-access-token"),
            )
            db.session.add(acc)
            db.session.commit()
            acc_id = acc.id

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id

        res = self.client.post("/api/mail/disconnect", json={"account_id": acc_id})
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            # Connected account is removed
            self.assertIsNone(db.session.get(ConnectedEmailAccount, acc_id))
            # MailMild User account still exists!
            self.assertIsNotNone(db.session.get(User, self.user_a_id))


if __name__ == "__main__":
    unittest.main()
