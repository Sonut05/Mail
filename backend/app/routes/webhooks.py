"""
Webhook routes — receive Gmail push notifications.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")


@webhooks_bp.route("/gmail", methods=["POST"])
def gmail_push_notification():
    """Handle a Gmail push notification (Pub/Sub).

    Google Cloud Pub/Sub sends a POST with a JSON body containing a
    ``message`` field. This endpoint acknowledges the notification and
    can be extended to trigger an email sync for the relevant user.

    Returns:
        200 acknowledgement (required by Pub/Sub to prevent retries).
    """
    try:
        data = request.get_json(silent=True) or {}
        current_app.logger.info("Gmail push notification received: %s", data)

        # TODO: Decode the Pub/Sub message, identify the user by their
        #       historyId / email address, and trigger a targeted sync.
        #       For now we simply acknowledge the notification.

        return jsonify({"status": "acknowledged"}), 200

    except Exception as exc:
        current_app.logger.error("Webhook error: %s", exc)
        # Always return 200 so Pub/Sub doesn't retry endlessly.
        return jsonify({"status": "error", "detail": str(exc)}), 200
