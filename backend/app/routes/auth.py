"""
Authentication routes — Google OAuth 2.0 login / callback / logout.
"""

from __future__ import annotations

import hmac
import os
import secrets
import urllib.parse
from datetime import datetime, timezone

# Ensure OAuthlib allows returned scope variations without raising ScopeChangedError
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from flask import Blueprint, redirect, request, session, jsonify, current_app
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build as build_service
from itsdangerous import URLSafeTimedSerializer

from app.extensions import db

from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.services.encryption import encrypt_token, decrypt_token

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Google OAuth scopes — Phase 1 least-privilege read-only scopes (NO gmail.send)
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _get_state_serializer() -> URLSafeTimedSerializer:
    """Return a timed serializer for cryptographically signing OAuth CSRF state."""
    secret_key = current_app.config.get("SECRET_KEY", "dev-secret-key-change-me")
    return URLSafeTimedSerializer(secret_key, salt="oauth-state")


def _build_flow(state: str | None = None) -> Flow:
    """Build a Google OAuth2 Flow from application config.

    Args:
        state: Optional CSRF state string to bind to the flow.

    Returns:
        A configured ``google_auth_oauthlib.flow.Flow`` instance.
    """
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = current_app.config.get("GOOGLE_REDIRECT_URI", "").strip()

    if not client_id or not client_secret or not redirect_uri:
        raise ValueError("Google OAuth credentials or redirect URI are not configured.")

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri,
    )
    return flow


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────


@auth_bp.route("/google", methods=["GET"])
@auth_bp.route("/google/login", methods=["GET"])
def google_login():
    """Redirect user to Google's official OAuth consent screen.
    
    If the user is already logged into MailMild, their session is tracked so the
    connected Gmail account is associated with their existing MailMild user.
    If the user is not yet logged in, completing OAuth will authenticate them.
    Generates a cryptographically secure state token to protect against CSRF attacks.
    """
    user_id = session.get("user_id")
    if user_id:
        session["oauth_user_id"] = user_id
    else:
        session.pop("oauth_user_id", None)

    # Check if mock simulation is explicitly requested or client ID is placeholder
    mock = request.args.get("mock", "false").lower() == "true"
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    is_placeholder = not client_id or "googleusercontent.com" not in client_id

    if mock or is_placeholder:
        try:
            demo_email = "demo.developer@gmail.com"
            user = db.session.get(User, user_id) if user_id else None
            if not user:
                user = User.query.filter_by(email=demo_email).first()
                if not user:
                    user = User(email=demo_email, name="Demo Developer", provider="google")
                    db.session.add(user)
                    db.session.flush()

            user.name = user.name or "Demo Developer"
            user.picture = user.picture or "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=256&h=256&q=80"
            session["user_id"] = user.id

            connected_acc = ConnectedEmailAccount.query.filter_by(
                user_id=user.id,
                provider="gmail",
                email_address=demo_email,
            ).first()

            if not connected_acc:
                connected_acc = ConnectedEmailAccount(
                    user_id=user.id,
                    provider="gmail",
                    provider_account_id="mock_google_sub_123",
                    email_address=demo_email,
                    encrypted_access_token=encrypt_token("mock-access-token"),
                    sync_status="idle",
                )
                db.session.add(connected_acc)
            else:
                connected_acc.encrypted_access_token = encrypt_token("mock-access-token")
                connected_acc.sync_status = "idle"
                connected_acc.updated_at = datetime.now(timezone.utc)

            db.session.commit()
            frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:3000")
            if user_id:
                return redirect(f"{frontend_url}/settings?connected=gmail&email={urllib.parse.quote(demo_email)}")
            return redirect(f"{frontend_url}/dashboard")
        except Exception as exc:
            current_app.logger.error("Mock Gmail connection error: %s", exc)
            return jsonify({"error": "Failed to create mock connected account."}), 500

    try:
        # Generate cryptographically signed state token for robust CSRF protection
        serializer = _get_state_serializer()
        state = serializer.dumps({
            "nonce": secrets.token_urlsafe(16),
            "user_id": user_id,
        })
        session["oauth_state"] = state

        flow = _build_flow(state=state)
        prompt_val = request.args.get("prompt", "consent select_account")
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            prompt=prompt_val,
        )
        return redirect(authorization_url)
    except Exception as exc:
        current_app.logger.error("Failed to build Google OAuth flow: %s", exc)
        return jsonify({"error": f"Failed to initiate OAuth flow: {str(exc)}"}), 500


@auth_bp.route("/google/callback", methods=["GET"])
def google_callback():
    """Handle Google's OAuth callback: validate state, exchange code, store tokens safely."""
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:3000")

    # Check for denial or error parameter from Google
    google_error = request.args.get("error")
    if google_error:
        current_app.logger.warning("Google OAuth denied or failed: %s", google_error)
        return redirect(f"{frontend_url}/settings?error={urllib.parse.quote(google_error)}")

    # 1. CSRF state validation (Dual-layer: Session match + Cryptographic signature fallback)
    returned_state = request.args.get("state")
    stored_state = session.get("oauth_state")
    oauth_user_id = session.get("oauth_user_id")

    state_valid = False
    state_user_id = None

    if returned_state:
        # Check A: Session state exact match
        if stored_state and hmac.compare_digest(returned_state, stored_state):
            state_valid = True

        # Check B: Cryptographic verification of server signature (valid for 15 minutes)
        # Guarantees state was created by this server even if session cookie was dropped by browser
        if not state_valid:
            try:
                serializer = _get_state_serializer()
                payload = serializer.loads(returned_state, max_age=900)
                state_valid = True
                state_user_id = payload.get("user_id")
            except Exception as sig_err:
                current_app.logger.warning("OAuth state cryptographic signature check failed: %s", sig_err)

    if not state_valid:
        current_app.logger.error("OAuth state mismatch or missing state parameter.")
        return jsonify({
            "error": "Invalid or missing OAuth state parameter (CSRF protection failed). Please return to the login page and try again."
        }), 400

    # Pop used state from session once validated
    session.pop("oauth_state", None)
    session.pop("oauth_user_id", None)

    was_already_logged_in = bool(session.get("user_id") or oauth_user_id or state_user_id)
    current_user_id = session.get("user_id") or oauth_user_id or state_user_id

    try:
        # 2. Exchange authorization code for credentials
        flow = _build_flow(state=returned_state)
        flow.fetch_token(authorization_response=request.url)

        credentials = flow.credentials
        access_token = credentials.token
        refresh_token = credentials.refresh_token or ""
        token_expiry = credentials.expiry

        # 3. Fetch Google account info using Google userinfo API
        oauth2_service = build_service(
            "oauth2", "v2", credentials=credentials, cache_discovery=False
        )
        user_info = oauth2_service.userinfo().get().execute()
        google_email = user_info.get("email", "").strip().lower()
        google_account_id = user_info.get("id", "")
        name = user_info.get("name", "")
        picture = user_info.get("picture", "")

        if not google_email:
            return jsonify({"error": "Could not retrieve email from Google OAuth response."}), 400

        # 4. Resolve MailMild User: use existing authenticated session or find/create by Google email
        if current_user_id:
            user = db.session.get(User, current_user_id)
        else:
            user = User.query.filter_by(email=google_email).first()
            if not user:
                user = User(
                    email=google_email,
                    name=name if name else google_email.split("@")[0].capitalize(),
                    picture=picture,
                    provider="google",
                )
                db.session.add(user)
                db.session.flush()

        if not user:
            return jsonify({"error": "Could not identify or create MailMild user."}), 500

        # Maintain active session
        session["user_id"] = user.id

        # 5. Encrypt tokens before writing to database (NEVER store plaintext)
        enc_access = encrypt_token(access_token)
        enc_refresh = encrypt_token(refresh_token) if refresh_token else None

        # 6. Create or update ConnectedEmailAccount for this MailMild user
        connected_acc = ConnectedEmailAccount.query.filter_by(
            user_id=user.id,
            provider="gmail",
            email_address=google_email,
        ).first()

        if not connected_acc:
            connected_acc = ConnectedEmailAccount(
                user_id=user.id,
                provider="gmail",
                provider_account_id=google_account_id,
                email_address=google_email,
                encrypted_access_token=enc_access,
                encrypted_refresh_token=enc_refresh,
                token_expiry=token_expiry,
                sync_status="idle",
            )
            db.session.add(connected_acc)
        else:
            connected_acc.provider_account_id = google_account_id
            connected_acc.encrypted_access_token = enc_access
            if enc_refresh:
                connected_acc.encrypted_refresh_token = enc_refresh
            connected_acc.token_expiry = token_expiry
            connected_acc.sync_status = "idle"
            connected_acc.updated_at = datetime.now(timezone.utc)

        # Update user profile picture and tokens for backwards-compatibility
        if picture and not user.picture:
            user.picture = picture
        user.encrypted_access_token = enc_access
        if enc_refresh:
            user.encrypted_refresh_token = enc_refresh
        user.updated_at = datetime.now(timezone.utc)

        db.session.commit()

        # Redirect: if connecting from Settings (user was already authenticated), return to settings;
        # if logging in from Login screen, return to dashboard.
        if was_already_logged_in:
            return redirect(f"{frontend_url}/settings?connected=gmail&email={urllib.parse.quote(google_email)}")
        return redirect(f"{frontend_url}/dashboard")

    except Exception as exc:
        current_app.logger.error("OAuth callback processing error: %s", exc)
        db.session.rollback()
        err_msg = str(exc)
        if "invalid_grant" in err_msg.lower():
            err_msg = "Google authorization code has expired or was already used. Please start sign-in again from the login page."
        return jsonify({"error": f"OAuth callback failed: {err_msg}"}), 500




@auth_bp.route("/me", methods=["GET"])
def me():
    """Return the currently authenticated user's profile.

    Returns:
        200 with user info, or 401 if not authenticated.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not authenticated."}), 401

    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return jsonify({"error": "User not found."}), 401

    return jsonify({"user": user.to_dict()}), 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Clear the server-side session (log out).

    Returns:
        200 with a success message.
    """
    session.clear()
    return jsonify({"message": "Logged out successfully."}), 200


@auth_bp.route("/register", methods=["POST"])
def register():
    """Register a new user with email and password, name, and contact number."""
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        name = data.get("name", "").strip()
        contact_no = data.get("contact_no", "").strip()

        if not email or not password:
            return jsonify({"error": "Email and password are required."}), 400

        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return jsonify({"error": "An account with this email already exists."}), 400

        # Create user
        user = User(email=email, name=name, contact_no=contact_no, provider="local")
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()

        # Log user in by setting session
        session["user_id"] = user.id
        return jsonify({"user": user.to_dict()}), 201

    except Exception as exc:
        current_app.logger.error("Registration error: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Registration failed: {str(exc)}"}), 500


@auth_bp.route("/login", methods=["POST"])
def login():
    """Login a user with email and password."""
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")

        if not email or not password:
            return jsonify({"error": "Email and password are required."}), 400

        user = User.query.filter_by(email=email).first()
        if not user or user.provider != "local" or not user.check_password(password):
            return jsonify({"error": "Invalid email or password."}), 401

        # Log user in by setting session
        session["user_id"] = user.id
        return jsonify({"user": user.to_dict()}), 200

    except Exception as exc:
        current_app.logger.error("Login error: %s", exc)
        return jsonify({"error": f"Login failed: {str(exc)}"}), 500

