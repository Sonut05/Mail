"""
Input validation and injection defense utilities.

Covers:
- SSRF prevention (blocking loopback, private ranges, link-local, and cloud metadata addresses)
- File upload security (MIME checking, magic byte inspection, size limits)
- AI prompt delimiter injection defense
- Path traversal verification
"""

from __future__ import annotations

import io
import ipaddress
import os
import socket
import urllib.parse
from typing import Optional
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

# Disallowed hostnames for SSRF
DISALLOWED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "::1",
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
}

# Maximum PDF upload size (10 MB)
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


def validate_safe_url(url: str) -> tuple[bool, Optional[str]]:
    """Validate a URL to prevent Server-Side Request Forgery (SSRF).

    Checks:
    - Scheme must be http or https
    - Hostname cannot resolve to loopback, link-local, private IP (RFC 1918),
      multicast, or cloud metadata endpoints.

    Returns:
        (is_safe, error_message)
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string."

    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "Malformed URL."

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed."

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "URL must include a valid hostname."

    if hostname in DISALLOWED_HOSTNAMES:
        return False, f"Access to restricted host '{hostname}' is blocked."

    # Resolve IP address to detect internal/private IPs
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"Could not resolve host '{hostname}'."
    except Exception as exc:
        return False, f"Host resolution error: {exc}"

    for entry in addr_info:
        ip_str = entry[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip.is_loopback:
                return False, f"Loopback address '{ip}' is blocked."
            if ip.is_private:
                return False, f"Private address '{ip}' is blocked."
            if ip.is_link_local:
                return False, f"Link-local address '{ip}' is blocked."
            if ip.is_reserved:
                return False, f"Reserved address '{ip}' is blocked."
            if ip.is_multicast:
                return False, f"Multicast address '{ip}' is blocked."
            if ip_str == "169.254.169.254":
                return False, "Cloud metadata service access is blocked."
        except ValueError:
            return False, f"Invalid IP address '{ip_str}' resolved."

    return True, None


def validate_pdf_upload(
    file_storage: FileStorage,
    max_size: int = MAX_FILE_SIZE_BYTES
) -> tuple[bool, Optional[str], Optional[bytes]]:
    """Inspect and validate an uploaded PDF file for security.

    Checks:
    - Filename has .pdf extension
    - Content-Type is application/pdf (or generic octet-stream with valid magic bytes)
    - File size is within max_size limit
    - File starts with valid PDF magic bytes (%PDF-)

    Returns:
        (is_valid, error_message, file_bytes)
    """
    if not file_storage or not file_storage.filename:
        return False, "No file provided.", None

    safe_name = secure_filename(file_storage.filename)
    if not safe_name.lower().endswith(".pdf"):
        return False, "File must have a .pdf extension.", None

    # Read bytes safely with bounded size
    file_bytes = file_storage.read(max_size + 1)
    if len(file_bytes) > max_size:
        return False, f"File exceeds maximum allowed size of {max_size // (1024 * 1024)}MB.", None

    if len(file_bytes) < 5:
        return False, "File is too small to be a valid PDF.", None

    # Magic byte inspection: PDF files must start with %PDF-
    if not file_bytes.startswith(b"%PDF-"):
        return False, "Invalid PDF file structure (missing %PDF- header).", None

    # Reset file pointer for any downstream consumer
    file_storage.seek(0)
    return True, None, file_bytes


def sanitize_ai_prompt_input(text: str) -> str:
    """Neutralize delimiter injection attempts in user-supplied strings before LLM prompts.

    Prevents untrusted text from breaking out of XML/tag delimiters such as:
    <email_body>, </email_body>, <email_subject>, </email_subject>, etc.
    """
    if not text or not isinstance(text, str):
        return ""

    sanitized = text
    delimiters = [
        ("</email_body>", "&lt;/email_body&gt;"),
        ("<email_body>", "&lt;email_body&gt;"),
        ("</email_subject>", "&lt;/email_subject&gt;"),
        ("<email_subject>", "&lt;email_subject&gt;"),
        ("</email_metadata>", "&lt;/email_metadata&gt;"),
        ("<email_metadata>", "&lt;email_metadata&gt;"),
        ("</resume_content>", "&lt;/resume_content&gt;"),
        ("<resume_content>", "&lt;resume_content&gt;"),
        ("</system>", "&lt;/system&gt;"),
        ("<system>", "&lt;system&gt;"),
    ]
    for tag, replacement in delimiters:
        sanitized = sanitized.replace(tag, replacement)

    return sanitized


def validate_safe_filepath(base_directory: str, filename_or_path: str) -> tuple[bool, Optional[str]]:
    """Verify that a path stays within base_directory, preventing directory traversal.

    Returns:
        (is_safe, resolved_absolute_path_or_error)
    """
    if not filename_or_path:
        return False, "Path cannot be empty."

    base_abs = os.path.abspath(base_directory)
    target_abs = os.path.abspath(os.path.join(base_abs, filename_or_path))

    common = os.path.commonpath([base_abs, target_abs])
    if common != base_abs:
        return False, "Path traversal attempt detected."

    return True, target_abs
