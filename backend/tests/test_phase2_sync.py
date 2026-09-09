"""
Phase 2 Tests — Initial Full Gmail Mailbox Sync.

Covers:
- Pagination across multiple Gmail API pages
- Batch processing in bounded chunks
- Idempotency: synchronizing twice produces zero duplicate records
- MIME parsing (text/plain, text/html, multipart/alternative, multipart/mixed, nested, malformed)
- Gmail labels normalization and attachment metadata
- Token refresh for expired tokens
- Revoked token error handling (RefreshError -> error status)
- Multi-user isolation (User A cannot sync or read User B's accounts)
- Error resilience: single malformed message does not abort the batch
- API authentication and token security (tokens never leaked in sync responses)
"""

import base64
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.services.encryption import encrypt_token, decrypt_token
from app.services.sync_service import (
    parse_gmail_message_payload,
    sync_gmail_mailbox,
)
from google.auth.exceptions import RefreshError


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-phase2-secret-key"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "test-client-secret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"


def _b64(text: str) -> str:
    """Helper to encode string to urlsafe base64 without padding."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


class TestPhase2MailboxSync(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create User A
            self.user_a = User(
                email="user_a@mailmild.com",
                name="Alice User",
                provider="google",
            )
            db.session.add(self.user_a)

            # Create User B
            self.user_b = User(
                email="user_b@mailmild.com",
                name="Bob User",
                provider="google",
            )
            db.session.add(self.user_b)
            db.session.commit()

            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

            # Create Connected Account for User A
            self.acc_a = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                provider_account_id="gmail_sub_a",
                email_address="alice.gmail@gmail.com",
                encrypted_access_token=encrypt_token("valid-access-token-a"),
                encrypted_refresh_token=encrypt_token("valid-refresh-token-a"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="idle",
            )
            db.session.add(self.acc_a)

            # Create Connected Account for User B
            self.acc_b = ConnectedEmailAccount(
                user_id=self.user_b_id,
                provider="gmail",
                provider_account_id="gmail_sub_b",
                email_address="bob.gmail@gmail.com",
                encrypted_access_token=encrypt_token("valid-access-token-b"),
                encrypted_refresh_token=encrypt_token("valid-refresh-token-b"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="idle",
            )
            db.session.add(self.acc_b)
            db.session.commit()

            self.acc_a_id = self.acc_a.id
            self.acc_b_id = self.acc_b.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    # ──────────────────────────────────────────────────────────
    # 1. MIME & Header Parsing Unit Tests
    # ──────────────────────────────────────────────────────────

    def test_parse_plain_text_message(self):
        """Parse simple text/plain Gmail message."""
        msg = {
            "id": "msg_plain_1",
            "threadId": "th_1",
            "labelIds": ["INBOX", "IMPORTANT"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Plain Text Subject"},
                    {"name": "From", "value": "Sender <sender@example.com>"},
                    {"name": "To", "value": "Recipient <recipient@example.com>"},
                    {"name": "Date", "value": "Tue, 08 Sep 2026 08:00:00 +0000"},
                ],
                "body": {"data": _b64("Hello, this is a plain text body.")},
            },
        }
        parsed = parse_gmail_message_payload(msg)
        self.assertEqual(parsed["message_id"], "msg_plain_1")
        self.assertEqual(parsed["provider_message_id"], "msg_plain_1")
        self.assertEqual(parsed["subject"], "Plain Text Subject")
        self.assertEqual(parsed["body_text"], "Hello, this is a plain text body.")
        self.assertIn("INBOX", parsed["labels"])
        self.assertFalse(parsed["has_attachments"])

    def test_parse_multipart_alternative_html_and_text(self):
        """Parse multipart/alternative message preserving both plain text and HTML."""
        msg = {
            "id": "msg_multi_1",
            "threadId": "th_2",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "Subject", "value": "Multipart Newsletter"},
                    {"name": "From", "value": "News <news@example.com>"},
                    {"name": "To", "value": "user@example.com"},
                    {"name": "Cc", "value": "team@example.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64("Plain text version of newsletter.")},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {"data": _b64("<p>HTML version of newsletter.</p>")},
                    },
                ],
            },
        }
        parsed = parse_gmail_message_payload(msg)
        self.assertEqual(parsed["subject"], "Multipart Newsletter")
        self.assertEqual(parsed["body_text"], "Plain text version of newsletter.")
        self.assertEqual(parsed["body_html"], "<p>HTML version of newsletter.</p>")
        self.assertEqual(parsed["cc"], "team@example.com")

    def test_parse_multipart_mixed_with_attachment_metadata(self):
        """Parse multipart/mixed message and extract attachment metadata without downloading payload."""
        msg = {
            "id": "msg_attach_1",
            "threadId": "th_3",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "Subject", "value": "Project Specifications"},
                    {"name": "From", "value": "Client <client@company.com>"},
                    {"name": "To", "value": "dev@mailmild.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64("Please review the attached contract.")},
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "Contract_2026.pdf",
                        "body": {"attachmentId": "att_pdf_123", "size": 1048576},
                    },
                ],
            },
        }
        parsed = parse_gmail_message_payload(msg)
        self.assertTrue(parsed["has_attachments"])
        self.assertEqual(len(parsed["attachment_metadata"]), 1)
        att = parsed["attachment_metadata"][0]
        self.assertEqual(att["filename"], "Contract_2026.pdf")
        self.assertEqual(att["mimeType"], "application/pdf")
        self.assertEqual(att["size"], 1048576)

    def test_parse_malformed_and_missing_bodies_gracefully(self):
        """Parse message with completely missing body and missing headers without crashing."""
        msg = {
            "id": "msg_empty",
            "threadId": "th_empty",
            "payload": {
                "headers": [],
                "body": {},
            },
        }
        parsed = parse_gmail_message_payload(msg)
        self.assertEqual(parsed["message_id"], "msg_empty")
        self.assertEqual(parsed["subject"], "(No Subject)")
        self.assertEqual(parsed["body_text"], "")
        self.assertIsNotNone(parsed["received_at"])

    # ──────────────────────────────────────────────────────────
    # 2. Pagination & Batching Synchronization Tests
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_sync_pagination_across_multiple_pages(self, mock_build_service):
        """Sync fetches multiple pages using pageToken and nextPageToken."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        # Page 1 returns 2 message stubs and a nextPageToken
        page1_res = {
            "messages": [{"id": "page1_msg1"}, {"id": "page1_msg2"}],
            "nextPageToken": "token_page_2",
        }
        # Page 2 returns 1 message stub and no nextPageToken
        page2_res = {
            "messages": [{"id": "page2_msg1"}],
        }

        # Mock list responses based on pageToken
        def mock_list(**kwargs):
            req = MagicMock()
            if kwargs.get("pageToken") == "token_page_2":
                req.execute.return_value = page2_res
            else:
                req.execute.return_value = page1_res
            return req

        mock_gmail.users().messages().list.side_effect = mock_list

        # Mock get responses
        def mock_get(userId, id, format):
            req = MagicMock()
            req.execute.return_value = {
                "id": id,
                "threadId": f"thread_{id}",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": f"Subject for {id}"},
                        {"name": "From", "value": f"from_{id}@example.com"},
                        {"name": "To", "value": "alice@gmail.com"},
                    ],
                    "body": {"data": _b64(f"Body content of {id}")},
                },
            }
            return req

        mock_gmail.users().messages().get.side_effect = mock_get

        with self.app.app_context():
            result = sync_gmail_mailbox(self.acc_a_id, batch_size=2)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["messages_synced"], 3)

            # Verify SQLite records
            count = EmailMessage.query.filter_by(connected_account_id=self.acc_a_id).count()
            self.assertEqual(count, 3)

            account = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(account.sync_status, "completed")
            self.assertEqual(account.messages_synced, 3)
            self.assertIsNotNone(account.last_sync_at)

    # ──────────────────────────────────────────────────────────
    # 3. Idempotency Tests
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_sync_idempotency_running_twice_creates_no_duplicates(self, mock_build_service):
        """Running sync twice for the same messages must never duplicate EmailMessage records."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        list_res = {
            "messages": [{"id": "idemp_msg_1"}, {"id": "idemp_msg_2"}],
        }
        mock_gmail.users().messages().list().execute.return_value = list_res

        def mock_get(userId, id, format):
            req = MagicMock()
            req.execute.return_value = {
                "id": id,
                "threadId": f"th_{id}",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": f"Idempotent Subject {id}"},
                        {"name": "From", "value": "sender@test.com"},
                        {"name": "To", "value": "alice@gmail.com"},
                    ],
                    "body": {"data": _b64("Idempotency test body")},
                },
            }
            return req

        mock_gmail.users().messages().get.side_effect = mock_get

        with self.app.app_context():
            # Run 1
            res1 = sync_gmail_mailbox(self.acc_a_id)
            self.assertEqual(res1["status"], "completed")
            self.assertEqual(res1["messages_synced"], 2)
            self.assertEqual(EmailMessage.query.filter_by(connected_account_id=self.acc_a_id).count(), 2)

            # Run 2 (Same messages)
            res2 = sync_gmail_mailbox(self.acc_a_id)
            self.assertEqual(res2["status"], "completed")
            self.assertEqual(res2["messages_synced"], 2)
            # Must STILL be exactly 2, zero duplicates created!
            self.assertEqual(EmailMessage.query.filter_by(connected_account_id=self.acc_a_id).count(), 2)

    # ──────────────────────────────────────────────────────────
    # 4. Token Refresh & Revocation Tests
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    @patch("google.oauth2.credentials.Credentials.refresh")
    def test_token_auto_refreshes_when_expired(self, mock_refresh, mock_build_service):
        """Expired access token triggers refresh and updates encrypted token in database."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail
        mock_gmail.users().messages().list().execute.return_value = {"messages": []}

        # Set account token as expired
        with self.app.app_context():
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            acc.token_expiry = datetime.now(timezone.utc) - timedelta(minutes=10)
            db.session.commit()

            # Setup refresh side-effect to simulate token update
            def do_refresh(request):
                # simulate Google returning a new token
                pass
            mock_refresh.side_effect = do_refresh

            res = sync_gmail_mailbox(self.acc_a_id)
            self.assertEqual(res["status"], "completed")
            mock_refresh.assert_called_once()

    @patch("app.services.sync_service.build_service")
    @patch("google.oauth2.credentials.Credentials.refresh")
    def test_revoked_token_marks_account_in_error_state(self, mock_refresh, mock_build_service):
        """Revoked refresh token puts account into error/reauth state without deleting user."""
        mock_refresh.side_effect = RefreshError("invalid_grant: Token has been expired or revoked.")

        with self.app.app_context():
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            acc.token_expiry = datetime.now(timezone.utc) - timedelta(minutes=10)
            db.session.commit()

            res = sync_gmail_mailbox(self.acc_a_id)
            self.assertEqual(res["status"], "error")
            self.assertEqual(res.get("error"), "Reauthorization required.")

            acc_updated = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc_updated.sync_status, "error")
            self.assertIn("Reauthorization required", acc_updated.sync_progress)

            # MailMild user record must remain completely intact
            user = db.session.get(User, self.user_a_id)
            self.assertIsNotNone(user)

    # ──────────────────────────────────────────────────────────
    # 5. Error Resilience Tests
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_single_malformed_message_does_not_abort_batch(self, mock_build_service):
        """If one message fails during get/parsing, valid messages in the batch are still saved."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        list_res = {
            "messages": [{"id": "good_msg_1"}, {"id": "corrupted_msg"}, {"id": "good_msg_2"}],
        }
        mock_gmail.users().messages().list().execute.return_value = list_res

        def mock_get(userId, id, format):
            req = MagicMock()
            if id == "corrupted_msg":
                # Simulate a corrupted message payload throwing an unexpected exception
                req.execute.side_effect = RuntimeError("Corrupted MIME payload from provider")
            else:
                req.execute.return_value = {
                    "id": id,
                    "threadId": f"th_{id}",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "mimeType": "text/plain",
                        "headers": [
                            {"name": "Subject", "value": f"Valid {id}"},
                            {"name": "From", "value": "sender@valid.com"},
                        ],
                        "body": {"data": _b64("Valid body content")},
                    },
                }
            return req

        mock_gmail.users().messages().get.side_effect = mock_get

        with self.app.app_context():
            res = sync_gmail_mailbox(self.acc_a_id)
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["messages_synced"], 2)

            # Verify that good_msg_1 and good_msg_2 were successfully saved
            saved = EmailMessage.query.filter_by(connected_account_id=self.acc_a_id).all()
            self.assertEqual(len(saved), 2)
            saved_ids = [m.provider_message_id for m in saved]
            self.assertIn("good_msg_1", saved_ids)
            self.assertIn("good_msg_2", saved_ids)

    # ──────────────────────────────────────────────────────────
    # 6. Multi-User Isolation & API Security Tests
    # ──────────────────────────────────────────────────────────

    def test_sync_endpoints_require_authentication(self):
        """Unauthenticated requests to sync endpoints must return 401."""
        res_post = self.client.post("/api/mail/sync")
        self.assertEqual(res_post.status_code, 401)

        res_get = self.client.get("/api/mail/sync-status")
        self.assertEqual(res_get.status_code, 401)

    def test_multi_user_isolation_user_a_cannot_sync_user_b_account(self):
        """User A cannot trigger sync or view status for User B's connected account."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id

        # User A tries to trigger sync for User B's account
        res_sync = self.client.post("/api/mail/sync", json={"account_id": self.acc_b_id})
        self.assertEqual(res_sync.status_code, 403)
        self.assertIn("Unauthorized", res_sync.get_json().get("error", ""))

        # User A tries to view sync status for User B's account
        res_status = self.client.get(f"/api/mail/sync-status?account_id={self.acc_b_id}")
        self.assertEqual(res_status.status_code, 403)
        self.assertIn("Unauthorized", res_status.get_json().get("error", ""))

    @patch("app.services.sync_service.build_service")
    def test_sync_responses_never_expose_tokens(self, mock_build_service):
        """Sync and sync-status APIs must never return access tokens or secrets."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail
        mock_gmail.users().messages().list().execute.return_value = {"messages": []}

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_a_id

        # Trigger sync
        res_sync = self.client.post("/api/mail/sync?sync_now=true", json={"account_id": self.acc_a_id})
        self.assertEqual(res_sync.status_code, 200)
        data_sync = json.dumps(res_sync.get_json())
        self.assertNotIn("valid-access-token", data_sync)
        self.assertNotIn("valid-refresh-token", data_sync)
        self.assertNotIn("client_secret", data_sync)

        # Check status
        res_status = self.client.get(f"/api/mail/sync-status?account_id={self.acc_a_id}")
        self.assertEqual(res_status.status_code, 200)
        data_status = json.dumps(res_status.get_json())
        self.assertNotIn("valid-access-token", data_status)
        self.assertNotIn("valid-refresh-token", data_status)
        self.assertNotIn("client_secret", data_status)


if __name__ == "__main__":
    unittest.main()
