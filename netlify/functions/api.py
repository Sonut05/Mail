"""
MailMind AI — Netlify Serverless Function WSGI Adapter.

Exposes the Flask Web API as an AWS Lambda / Netlify Serverless Function.
Preserves:
- Complete WSGI environment and Flask middleware pipeline
- Full /api/* routing, correlation IDs, and security headers
- Session authentication and multiple Set-Cookie headers via multiValueHeaders
- Request bodies (JSON, form data, multipart, base64 encoded payloads)
- Strict error sanitization (no secret leakage)
"""

from __future__ import annotations

import base64
import io
import logging
import os
import sys
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

# Ensure both the function directory and backend directory are on sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_current_dir, "..", "..", "backend"))

if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

logger = logging.getLogger("mailmind.netlify")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [NetlifyFunction] %(message)s",
    )

# ── Module-level cached Flask application ────────────────────────────────────
_app: Optional[Any] = None


def get_application() -> Any:
    """Initialize and return the cached Flask application instance."""
    global _app
    if _app is None:
        try:
            from app import create_app
            from app.config import Config, ProductionConfig
        except ImportError:
            # Fallback when packaged directly inside netlify/functions/app
            from app import create_app  # type: ignore
            from app.config import Config, ProductionConfig  # type: ignore

        env = os.getenv("FLASK_ENV", "development")
        config_cls = ProductionConfig if env == "production" else Config
        _app = create_app(config_cls)
        logger.info("Flask application successfully initialized for Netlify Functions (env=%s)", env)
    return _app


# ── URL and Path Normalizer ──────────────────────────────────────────────────
def normalize_path(raw_path: Optional[str]) -> str:
    """Normalize incoming Netlify redirect paths to standard Flask routes.

    Examples:
    - "/.netlify/functions/api/auth/me" -> "/api/auth/me"
    - "/.netlify/functions/api" -> "/api"
    - "/health" -> "/api/health"
    - "/ready" -> "/api/ready"
    - "/api/emails" -> "/api/emails"
    """
    if not raw_path:
        return "/api/health"

    path = raw_path
    if path.startswith("/.netlify/functions/api"):
        sub = path[len("/.netlify/functions/api") :]
        path = "/api" + sub if sub else "/api"

    # Alias standalone /health and /ready to their /api counterparts
    if path == "/health":
        path = "/api/health"
    elif path == "/ready":
        path = "/api/ready"

    return path if path.startswith("/") else f"/{path}"


# ── WSGI Environment Builder ─────────────────────────────────────────────────
def build_wsgi_environ(event: Dict[str, Any], path: str) -> Dict[str, Any]:
    """Construct a standard PEP 3333 WSGI environment dictionary from an API Gateway event."""
    http_method = event.get("httpMethod", "GET").upper()

    # Query string construction
    query_string = ""
    multi_qs = event.get("multiValueQueryStringParameters") or {}
    single_qs = event.get("queryStringParameters") or {}

    if multi_qs:
        pairs: List[Tuple[str, str]] = []
        for k, vals in multi_qs.items():
            if vals:
                for v in vals:
                    pairs.append((k, v))
            else:
                pairs.append((k, ""))
        query_string = urllib.parse.urlencode(pairs)
    elif single_qs:
        query_string = urllib.parse.urlencode(single_qs)

    # Request body decoding
    body_bytes = b""
    raw_body = event.get("body")
    if raw_body:
        if event.get("isBase64Encoded", False):
            try:
                body_bytes = base64.b64decode(raw_body)
            except Exception as exc:
                logger.warning("Failed to decode base64 request body: %s", exc)
                body_bytes = raw_body.encode("utf-8")
        else:
            body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body

    headers = event.get("headers") or {}
    server_name = headers.get("host", "localhost").split(":")[0]
    server_port = "443" if headers.get("x-forwarded-proto", "https") == "https" else "80"

    environ: Dict[str, Any] = {
        "REQUEST_METHOD": http_method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": query_string,
        "SERVER_NAME": server_name,
        "SERVER_PORT": server_port,
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": headers.get("x-forwarded-proto", "https"),
        "wsgi.input": io.BytesIO(body_bytes),
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }

    # Transform HTTP headers into WSGI environ keys
    for header_key, header_val in headers.items():
        if not header_val:
            continue
        key_upper = header_key.upper().replace("-", "_")
        if key_upper == "CONTENT_TYPE":
            environ["CONTENT_TYPE"] = header_val
        elif key_upper == "CONTENT_LENGTH":
            environ["CONTENT_LENGTH"] = header_val
        else:
            environ[f"HTTP_{key_upper}"] = header_val

    # Ensure CONTENT_LENGTH is set accurately from decoded body length
    if body_bytes and "CONTENT_LENGTH" not in environ:
        environ["CONTENT_LENGTH"] = str(len(body_bytes))

    return environ


# ── Response Formatting ──────────────────────────────────────────────────────
def format_response(
    status_code: int,
    headers_list: List[Tuple[str, str]],
    body_bytes: bytes,
) -> Dict[str, Any]:
    """Format WSGI status, headers, and body into AWS Lambda / Netlify return structure."""
    single_headers: Dict[str, str] = {}
    multi_headers: Dict[str, List[str]] = {}

    for key, value in headers_list:
        key_lower = key.lower()
        if key_lower == "set-cookie":
            # Multi-cookie support: preserve every Set-Cookie header separately
            if "Set-Cookie" not in multi_headers:
                multi_headers["Set-Cookie"] = []
            multi_headers["Set-Cookie"].append(value)
        else:
            single_headers[key] = value

    # Check whether response body is text or binary
    content_type = single_headers.get("Content-Type", "").lower()
    is_text = any(
        text_type in content_type
        for text_type in ("text/", "application/json", "application/javascript", "application/xml")
    )

    if is_text or not content_type:
        try:
            body_str = body_bytes.decode("utf-8")
            is_b64 = False
        except UnicodeDecodeError:
            body_str = base64.b64encode(body_bytes).decode("ascii")
            is_b64 = True
    else:
        body_str = base64.b64encode(body_bytes).decode("ascii")
        is_b64 = True

    response: Dict[str, Any] = {
        "statusCode": status_code,
        "headers": single_headers,
        "body": body_str,
        "isBase64Encoded": is_b64,
    }

    if multi_headers:
        response["multiValueHeaders"] = multi_headers

    return response


# ── Main Netlify Function Handler ────────────────────────────────────────────
def handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """Main entrypoint invoked by Netlify Functions / AWS Lambda."""
    try:
        app = get_application()
        raw_path = event.get("path", "")
        normalized_path = normalize_path(raw_path)

        environ = build_wsgi_environ(event, normalized_path)

        status_code = 200
        response_headers: List[Tuple[str, str]] = []

        def start_response(status: str, headers: List[Tuple[str, str]], exc_info: Any = None) -> Callable:
            nonlocal status_code, response_headers
            try:
                status_code = int(status.split(" ")[0])
            except Exception:
                status_code = 200
            response_headers = headers
            return lambda _: None

        # Execute the Flask WSGI application
        response_chunks = app(environ, start_response)
        body_bytes = b"".join(response_chunks)

        return format_response(status_code, response_headers, body_bytes)

    except Exception as exc:
        logger.error("Unhandled exception in Netlify Function handler: %s", exc, exc_info=True)
        # Safe structured error response avoiding secret leakage
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", "X-Content-Type-Options": "nosniff"},
            "body": '{"error":"Internal server error","message":"An unexpected error occurred in serverless execution."}',
            "isBase64Encoded": False,
        }
