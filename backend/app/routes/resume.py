"""
Resume and recruitment autopilot routes supporting multiple profiles.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
import uuid
from flask import Blueprint, jsonify, request, session, current_app

from app.extensions import db
from app.models import User
from app.services.ai_service import parse_resume, match_resume_and_autofill

try:
    pypdf = importlib.import_module("pypdf")
except Exception:
    pypdf = None

resume_bp = Blueprint("resume", __name__, url_prefix="/api/resume")


def _get_current_user() -> User | None:
    """Retrieve the authenticated user from the session."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def _require_auth():
    """Return (user, None) or (None, error_response)."""
    user = _get_current_user()
    if not user:
        return None, (jsonify({"error": "Authentication required."}), 401)
    return user, None


@resume_bp.route("/profiles", methods=["GET"])
def get_profiles():
    """Retrieve user's list of resume autopilot profiles."""
    user, err = _require_auth()
    if err:
        return err

    try:
        profiles = []
        if user.resume_profiles:
            try:
                profiles = json.loads(user.resume_profiles)
            except Exception:
                pass
        return jsonify({"profiles": profiles}), 200
    except Exception as exc:
        current_app.logger.error("Error fetching profiles: %s", exc)
        return jsonify({"error": "Failed to fetch profiles."}), 500


@resume_bp.route("/profiles", methods=["POST"])
def save_profile():
    """Save (create or update) a resume autopilot profile."""
    user, err = _require_auth()
    if err:
        return err

    try:
        # Check if request is JSON or multipart/form-data
        is_json = request.is_json
        profile_id = request.json.get("id") if is_json else request.form.get("id")
        target_role = request.json.get("target_role") if is_json else request.form.get("target_role")
        min_sal = request.json.get("min_salary") if is_json else request.form.get("min_salary")
        max_sal = request.json.get("max_salary") if is_json else request.form.get("max_salary")

        profiles = []
        if user.resume_profiles:
            try:
                profiles = json.loads(user.resume_profiles)
            except Exception:
                pass

        profile = None
        if profile_id:
            profile = next((p for p in profiles if p["id"] == profile_id), None)

        if not profile:
            profile = {
                "id": str(uuid.uuid4()),
                "target_role": "",
                "min_salary": None,
                "max_salary": None,
                "resume_text": "",
                "resume_parsed_json": None
            }
            profiles.append(profile)

        # Update text fields
        if target_role is not None:
            profile["target_role"] = target_role.strip()
        if min_sal is not None and str(min_sal).strip() != "":
            try:
                profile["min_salary"] = int(float(min_sal))
            except (ValueError, TypeError):
                profile["min_salary"] = None
        elif min_sal == "":
            profile["min_salary"] = None
            
        if max_sal is not None and str(max_sal).strip() != "":
            try:
                profile["max_salary"] = int(float(max_sal))
            except (ValueError, TypeError):
                profile["max_salary"] = None
        elif max_sal == "":
            profile["max_salary"] = None

        # Check for resume text or file upload
        resume_text = ""
        if "file" in request.files:
            file = request.files["file"]
            if file.filename != "":
                filename = file.filename.lower()
                if filename.endswith(".txt"):
                    resume_text = file.read().decode("utf-8", errors="ignore")
                elif filename.endswith(".pdf"):
                    if pypdf is None:
                        return jsonify({"error": "pypdf is not installed. Please install pypdf or upload a .txt file."}), 400
                    try:
                        reader = pypdf.PdfReader(file)
                        text_list = [page.extract_text() for page in reader.pages]
                        resume_text = "\n".join([t for t in text_list if t])
                    except Exception as e:
                        current_app.logger.warning("Could not parse PDF: %s", e)
                        return jsonify({"error": f"Failed to parse PDF resume: {str(e)}"}), 400
                else:
                    return jsonify({"error": "Unsupported file format. Use .txt or .pdf."}), 400
        else:
            resume_text = request.json.get("resume_text") if is_json else request.form.get("resume_text")

        if resume_text:
            profile["resume_text"] = resume_text.strip()
            profile["resume_parsed_json"] = parse_resume(resume_text.strip())

        user.resume_profiles = json.dumps(profiles)
        
        # Legacy compatibility updates (for single profile columns)
        if len(profiles) == 1:
            user.target_role = profile["target_role"]
            user.min_salary = profile["min_salary"]
            user.max_salary = profile["max_salary"]
            user.resume_text = profile["resume_text"]
            user.resume_parsed_json = json.dumps(profile["resume_parsed_json"]) if profile["resume_parsed_json"] else None
            
        db.session.commit()
        return jsonify({
            "message": "Profile saved successfully.",
            "profile": profile,
            "profiles": profiles
        }), 200
    except Exception as exc:
        current_app.logger.error("Error saving profile: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to save profile: {str(exc)}"}), 500


@resume_bp.route("/profiles/<profile_id>", methods=["DELETE"])
def delete_profile(profile_id):
    """Delete a resume autopilot profile."""
    user, err = _require_auth()
    if err:
        return err

    try:
        profiles = []
        if user.resume_profiles:
            try:
                profiles = json.loads(user.resume_profiles)
            except Exception:
                pass

        profiles = [p for p in profiles if p["id"] != profile_id]
        user.resume_profiles = json.dumps(profiles)
        db.session.commit()
        return jsonify({
            "message": "Profile deleted successfully.",
            "profiles": profiles
        }), 200
    except Exception as exc:
        current_app.logger.error("Error deleting profile: %s", exc)
        db.session.rollback()
        return jsonify({"error": "Failed to delete profile."}), 500


@resume_bp.route("/auto-fill", methods=["POST"])
def auto_fill_form():
    """Analyze recruitment email and populate form details mapping."""
    user, err = _require_auth()
    if err:
        return err

    data = request.get_json() or {}
    email_id = data.get("email_id")
    profile_id = data.get("profile_id")
    
    if not email_id:
        return jsonify({"error": "Email ID is required."}), 400

    from app.models import EmailMessage
    email_msg = EmailMessage.query.filter_by(id=email_id, user_id=user.id).first()
    if not email_msg:
        return jsonify({"error": "Email not found."}), 404

    profiles = []
    if user.resume_profiles:
        try:
            profiles = json.loads(user.resume_profiles)
        except Exception:
            pass

    if not profiles:
        return jsonify({"error": "Please create a profile and upload a resume in Settings first."}), 400

    # Locate targeted profile or auto-detect
    selected_profile = None
    if profile_id:
        selected_profile = next((p for p in profiles if p["id"] == profile_id), None)
    
    if not selected_profile:
        email_content = (email_msg.subject + " " + email_msg.body_text).lower()
        for p in profiles:
            role = p.get("target_role", "").lower()
            if role and role in email_content:
                selected_profile = p
                break
        if not selected_profile:
            selected_profile = profiles[0]

    if not selected_profile.get("resume_parsed_json"):
        return jsonify({"error": f"Selected profile '{selected_profile.get('target_role')}' has no parsed resume. Please upload a resume for this role."}), 400

    preferences = {
        "target_role": selected_profile.get("target_role"),
        "min_salary": selected_profile.get("min_salary"),
        "max_salary": selected_profile.get("max_salary")
    }

    try:
        autofill_result = match_resume_and_autofill(
            email_body=email_msg.body_text,
            resume_json=selected_profile.get("resume_parsed_json"),
            preferences=preferences
        )
        
        # Inject selection IDs for context
        autofill_result["selected_profile_id"] = selected_profile["id"]
        autofill_result["available_profiles"] = [
            {"id": p["id"], "target_role": p["target_role"]} for p in profiles
        ]

        return jsonify({"autofill": autofill_result}), 200
    except Exception as exc:
        current_app.logger.error("Auto-fill generation failed: %s", exc)
        return jsonify({"error": f"Failed to generate auto-fill fields: {str(exc)}"}), 500
