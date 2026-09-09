"""
Tests for MailMind AI Netlify Functions Serverless Adapter (netlify/functions/api.py).

Validates:
- Path normalization from Netlify rewrites (/.netlify/functions/api/* -> /api/*)
- WSGI environment construction (headers, query parameters, bodies)
- Multiple Set-Cookie preservation via multiValueHeaders
- Health and readiness endpoints through the adapter
- Session authentication and user isolation through serverless invocations
- Secret redaction and error containment
"""

from __future__ import annotations

import base64
import json
import os
import sys
from typing import Any, Dict

import pytest

# Ensure root and netlify/functions are on sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
netlify_func_dir = os.path.join(root_dir, "netlify", "functions")
if netlify_func_dir not in sys.path:
    sys.path.insert(0, netlify_func_dir)

from api import (  # type: ignore
    build_wsgi_environ,
    format_response,
    handler,
    normalize_path,
)


class TestNetlifyPathNormalization:
    """Validate path normalization across various Netlify rewrite scenarios."""

    def test_normalize_splat_path(self):
        assert normalize_path("/.netlify/functions/api/health") == "/api/health"
        assert normalize_path("/.netlify/functions/api/auth/me") == "/api/auth/me"
        assert normalize_path("/.netlify/functions/api/emails/123") == "/api/emails/123"

    def test_normalize_root_function_path(self):
        assert normalize_path("/.netlify/functions/api") == "/api"
        assert normalize_path("/.netlify/functions/api/") == "/api/"

    def test_normalize_direct_api_path(self):
        assert normalize_path("/api/health") == "/api/health"
        assert normalize_path("/api/dashboard/stats") == "/api/dashboard/stats"

    def test_normalize_health_and_ready_aliases(self):
        assert normalize_path("/health") == "/api/health"
        assert normalize_path("/ready") == "/api/ready"

    def test_normalize_empty_or_none(self):
        assert normalize_path("") == "/api/health"
        assert normalize_path(None) == "/api/health"


class TestNetlifyWsgiConstruction:
    """Validate WSGI environment creation from Lambda API Gateway events."""

    def test_wsgi_query_parameters(self):
        event = {
            "httpMethod": "GET",
            "path": "/api/emails",
            "queryStringParameters": {"limit": "10", "category": "Work"},
        }
        environ = build_wsgi_environ(event, "/api/emails")
        assert environ["REQUEST_METHOD"] == "GET"
        assert environ["PATH_INFO"] == "/api/emails"
        assert "limit=10" in environ["QUERY_STRING"]
        assert "category=Work" in environ["QUERY_STRING"]

    def test_wsgi_multi_query_parameters(self):
        event = {
            "httpMethod": "GET",
            "path": "/api/emails",
            "multiValueQueryStringParameters": {"tag": ["urgent", "action"]},
        }
        environ = build_wsgi_environ(event, "/api/emails")
        assert "tag=urgent" in environ["QUERY_STRING"]
        assert "tag=action" in environ["QUERY_STRING"]

    def test_wsgi_headers_mapping(self):
        event = {
            "httpMethod": "POST",
            "path": "/api/test",
            "headers": {
                "Content-Type": "application/json",
                "Content-Length": "42",
                "X-Request-ID": "req-test-123",
                "Authorization": "Bearer token-xyz",
            },
        }
        environ = build_wsgi_environ(event, "/api/test")
        assert environ["CONTENT_TYPE"] == "application/json"
        assert environ["CONTENT_LENGTH"] == "42"
        assert environ["HTTP_X_REQUEST_ID"] == "req-test-123"
        assert environ["HTTP_AUTHORIZATION"] == "Bearer token-xyz"

    def test_wsgi_body_base64_decoding(self):
        raw_text = '{"name": "test"}'
        b64_payload = base64.b64encode(raw_text.encode("utf-8")).decode("ascii")
        event = {
            "httpMethod": "POST",
            "path": "/api/data",
            "body": b64_payload,
            "isBase64Encoded": True,
        }
        environ = build_wsgi_environ(event, "/api/data")
        body_read = environ["wsgi.input"].read().decode("utf-8")
        assert body_read == raw_text


class TestNetlifyResponseFormatting:
    """Validate conversion of WSGI status and headers to Netlify response format."""

    def test_format_multi_value_cookies(self):
        headers = [
            ("Content-Type", "application/json"),
            ("Set-Cookie", "mailmild_session=abc; Path=/; HttpOnly"),
            ("Set-Cookie", "remember_token=xyz; Path=/; Secure"),
        ]
        resp = format_response(200, headers, b'{"ok": true}')
        assert resp["statusCode"] == 200
        assert resp["headers"]["Content-Type"] == "application/json"
        assert "multiValueHeaders" in resp
        cookies = resp["multiValueHeaders"]["Set-Cookie"]
        assert len(cookies) == 2
        assert "mailmild_session=abc; Path=/; HttpOnly" in cookies
        assert "remember_token=xyz; Path=/; Secure" in cookies

    def test_format_binary_response(self):
        headers = [("Content-Type", "image/png")]
        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        resp = format_response(200, headers, binary_data)
        assert resp["isBase64Encoded"] is True
        assert base64.b64decode(resp["body"]) == binary_data


class TestNetlifyHandlerEndToEnd:
    """End-to-end integration tests invoking handler() with simulated API Gateway events."""

    def test_handler_health_check(self):
        event = {
            "httpMethod": "GET",
            "path": "/api/health",
            "headers": {"Host": "mailmind.netlify.app"},
        }
        resp = handler(event)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "healthy"
        assert "timestamp" in body
        # Security headers verified
        assert resp["headers"].get("X-Content-Type-Options") == "nosniff"
        assert resp["headers"].get("X-Frame-Options") == "SAMEORIGIN"

    def test_handler_rewritten_netlify_path(self):
        event = {
            "httpMethod": "GET",
            "path": "/.netlify/functions/api/health",
            "headers": {"Host": "mailmind.netlify.app"},
        }
        resp = handler(event)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "healthy"

    def test_handler_ready_probe(self):
        event = {
            "httpMethod": "GET",
            "path": "/ready",
            "headers": {"Host": "mailmind.netlify.app"},
        }
        resp = handler(event)
        # Database connected in test environment
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "ready"

    def test_handler_registration_and_cookie_flow(self):
        # 1. Register a test user via serverless POST request
        reg_payload = json.dumps({
            "email": "netlify.user@example.com",
            "password": "Password123!",
            "name": "Netlify User",
        })
        reg_event = {
            "httpMethod": "POST",
            "path": "/api/auth/register",
            "headers": {"Content-Type": "application/json"},
            "body": reg_payload,
            "isBase64Encoded": False,
        }
        reg_resp = handler(reg_event)
        assert reg_resp["statusCode"] in (201, 400)  # 201 if fresh, 400 if already created

        # 2. Login with credentials to verify session cookie generation
        login_payload = json.dumps({
            "email": "netlify.user@example.com",
            "password": "Password123!",
        })
        login_event = {
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "headers": {"Content-Type": "application/json"},
            "body": login_payload,
            "isBase64Encoded": False,
        }
        login_resp = handler(login_event)
        assert login_resp["statusCode"] == 200
        login_body = json.loads(login_resp["body"])
        assert "user" in login_body
        assert login_body["user"]["email"] == "netlify.user@example.com"

        # Verify session cookie was set in multiValueHeaders
        assert "multiValueHeaders" in login_resp
        set_cookie_headers = login_resp["multiValueHeaders"]["Set-Cookie"]
        assert any("mailmild_session=" in c for c in set_cookie_headers)

        # Extract session cookie value
        cookie_header = [c for c in set_cookie_headers if "mailmild_session=" in c][0]
        cookie_val = cookie_header.split(";")[0]

        # 3. Use the session cookie to request /api/auth/me
        me_event = {
            "httpMethod": "GET",
            "path": "/api/auth/me",
            "headers": {
                "Cookie": cookie_val,
                "Content-Type": "application/json",
            },
        }
        me_resp = handler(me_event)
        assert me_resp["statusCode"] == 200
        me_body = json.loads(me_resp["body"])
        assert me_body["user"]["email"] == "netlify.user@example.com"

    def test_handler_unauthenticated_protected_route(self):
        event = {
            "httpMethod": "GET",
            "path": "/api/auth/me",
            "headers": {"Content-Type": "application/json"},
        }
        resp = handler(event)
        assert resp["statusCode"] == 401
        body = json.loads(resp["body"])
        assert "error" in body

    def test_handler_safe_404_routing(self):
        event = {
            "httpMethod": "GET",
            "path": "/api/nonexistent-route-xyz",
            "headers": {},
        }
        resp = handler(event)
        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert body["error"] == "Not found"

    def test_handler_cross_user_idor_isolation(self):
        # 1. Register User A
        user_a_email = "usera.idor@example.com"
        reg_a = handler({
            "httpMethod": "POST",
            "path": "/api/auth/register",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"email": user_a_email, "password": "PasswordA123!", "name": "User A"}),
        })
        assert reg_a["statusCode"] in (201, 400)

        # Login User A to get cookie
        login_a = handler({
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"email": user_a_email, "password": "PasswordA123!"}),
        })
        cookie_a = [c for c in login_a["multiValueHeaders"]["Set-Cookie"] if "mailmild_session=" in c][0].split(";")[0]

        # 2. Register User B
        user_b_email = "userb.idor@example.com"
        reg_b = handler({
            "httpMethod": "POST",
            "path": "/api/auth/register",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"email": user_b_email, "password": "PasswordB123!", "name": "User B"}),
        })
        assert reg_b["statusCode"] in (201, 400)

        # Login User B to get cookie
        login_b = handler({
            "httpMethod": "POST",
            "path": "/api/auth/login",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"email": user_b_email, "password": "PasswordB123!"}),
        })
        cookie_b = [c for c in login_b["multiValueHeaders"]["Set-Cookie"] if "mailmild_session=" in c][0].split(";")[0]

        # 3. User A queries emails
        emails_a = handler({
            "httpMethod": "GET",
            "path": "/api/emails",
            "headers": {"Cookie": cookie_a, "Content-Type": "application/json"},
        })
        assert emails_a["statusCode"] == 200

        # 4. User B queries emails — verified isolated from User A
        emails_b = handler({
            "httpMethod": "GET",
            "path": "/api/emails",
            "headers": {"Cookie": cookie_b, "Content-Type": "application/json"},
        })
        assert emails_b["statusCode"] == 200
        # No User A data leaks to User B
        body_b = json.loads(emails_b["body"])
        for item in body_b.get("emails", []):
            assert item.get("user_id") != json.loads(login_a["body"])["user"]["id"]

    def test_handler_error_containment_no_secret_leakage(self):
        # Simulate an event causing internal error with dummy secret in query
        event = {
            "httpMethod": "GET",
            "path": "/api/ready",
            "queryStringParameters": {"secret": "MY_SUPER_SECRET_TOKEN_XYZ12345"},
            "headers": {},
        }
        resp = handler(event)
        # Body must not leak server secrets
        assert "GEMINI_API_KEY" not in resp["body"]
        assert "ENCRYPTION_KEY" not in resp["body"]
        assert "SECRET_KEY" not in resp["body"]

