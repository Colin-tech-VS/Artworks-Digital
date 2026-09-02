"""L'API par laquelle K.A.E.L. pilote Artworks Digital.

Tout passe par un jeton porteur, et un jeton porte des portées. Le
navigateur ne voit jamais ce jeton : il n'est présenté que de serveur à
serveur, depuis le centre de commande.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from artworks.extensions import csrf
from artworks.kael import confirm, permissions, tokens
from artworks.kael.registry import (
    ConfirmationRequired,
    PermissionDenied,
    ToolError,
    get as get_tool,
    manifest,
)
from artworks.kael.runner import run
from artworks.models import Artist, Work

kael_bp = Blueprint("kael", __name__, url_prefix="/api/kael")


def _grant_or_error():
    raw = request.headers.get("Authorization") or request.headers.get("X-Kael-Token") or ""
    grant = tokens.verify(raw)
    if grant is None:
        return None, (
            jsonify({
                "ok": False,
                "error": "Jeton K.A.E.L. absent, révoqué ou invalide.",
                "hint": "En-tête Authorization: Bearer <KAEL_API_KEY>.",
            }),
            401,
        )
    return grant, None


@kael_bp.after_request
def _no_store(response):
    # Rien de ce que rend cette API n'a vocation à être mis en cache.
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@kael_bp.route("/manifest")
def tool_manifest():
    """Ce que K.A.E.L. peut faire ici, avec ce jeton-là."""
    grant, error = _grant_or_error()
    if error:
        return error
    payload = manifest(grant.scopes)
    payload["token"] = {
        "label": grant.label,
        "scopes": sorted(grant.scopes),
        "artist_scope": grant.artist_id,
    }
    return jsonify(payload)


@kael_bp.route("/context")
def context():
    """Le contexte d'un tour de conversation : qui parle, d'où, sur quoi."""
    grant, error = _grant_or_error()
    if error:
        return error

    artist = grant.artist
    page = (request.args.get("page") or "").strip()[:200]
    work_id = request.args.get("work_id")
    artist_ref = request.args.get("artist")

    current_work = None
    if work_id and str(work_id).isdigit():
        work = Work.query.get(int(work_id))
        if work and (grant.artist_id is None or work.artist_id == grant.artist_id):
            current_work = {
                "id": work.id,
                "title": work.title,
                "artist_id": work.artist_id,
                "cartel": work.cartel,
                "visible": bool(work.visible),
            }
    if artist is None and artist_ref:
        found = Artist.query.filter(
            (Artist.slug == str(artist_ref)) | (Artist.email == str(artist_ref).lower())
        ).first()
        if found is not None:
            artist = found

    return jsonify({
        "application": "artworks-digital",
        "assistant": "K.A.E.L.",
        "tagline": "L’intelligence d’Artworks Digital.",
        "token_label": grant.label,
        "available_permissions": sorted(grant.scopes),
        "artist_id": artist.id if artist else None,
        "artist": {
            "id": artist.id,
            "display_name": artist.display_name,
            "slug": artist.slug,
            "plan": artist.plan_key,
            "published": bool(artist.published),
            "works": artist.works.count(),
        } if artist else None,
        "current_page": page or None,
        "current_artwork": current_work,
        "scoped_to_artist": grant.artist_id is not None,
        "tool_count": len(manifest(grant.scopes)["tools"]),
    })


@kael_bp.route("/tools/<name>", methods=["POST"])
@csrf.exempt
def call_tool(name: str):
    """Exécute un outil. 403 sans le droit, 409 quand une main humaine manque."""
    grant, error = _grant_or_error()
    if error:
        return error

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "Corps JSON attendu."}), 400
    params = body.get("params") if isinstance(body.get("params"), dict) else {
        key: value for key, value in body.items() if key != "confirm_token"
    }
    confirm_token = str(body.get("confirm_token") or "")

    try:
        return jsonify(run(name, params, grant, confirm_token=confirm_token))
    except PermissionDenied as exc:
        spec = get_tool(name)
        return jsonify({
            "ok": False,
            "error": str(exc),
            "required_permission": spec.permission if spec else None,
            "granted": sorted(grant.scopes),
        }), 403
    except ConfirmationRequired as exc:
        return jsonify({
            "ok": False,
            "status": "confirmation_required",
            "error": "Cette action attend une confirmation humaine.",
            "confirmation": confirm.card(
                exc.tool, params, exc.intent, exc.consequences, exc.target
            ),
        }), 409
    except ToolError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@kael_bp.route("/health")
def health():
    """Vivant, et combien d'outils sont déclarés — sans jeton, rien d'autre."""
    return jsonify({
        "ok": True,
        "application": "artworks-digital",
        "assistant": "K.A.E.L.",
        "tools": len(manifest()["tools"]),
        "permissions": list(permissions.ALL),
        "authenticated": tokens.verify(
            request.headers.get("Authorization") or ""
        ) is not None,
    })
