from flask import Blueprint, abort, request

from artworks.extensions import csrf
from artworks.stripe_billing import handle_webhook, stripe_ready


billing_bp = Blueprint("billing", __name__)


@billing_bp.route("/stripe/webhook", methods=["POST"])
@csrf.exempt
def stripe_webhook():
    if not stripe_ready():
        abort(503)
    try:
        handle_webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
    except Exception:
        abort(400)
    return "", 200
