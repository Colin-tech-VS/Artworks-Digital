"""Jetons signés — réinitialisation de mot de passe.

Le hash du mot de passe entre dans la signature : dès que le mot de passe
change, tous les liens émis avant deviennent invalides.
"""

from flask import current_app
from itsdangerous import URLSafeTimedSerializer

from artworks.extensions import db
from artworks.models import Artist

RESET_SALT = "artworks-password-reset"
RESET_MAX_AGE = 3600  # une heure


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=RESET_SALT)


def _fingerprint(artist: Artist) -> str:
    return (artist.password_hash or "")[-24:]


def make_reset_token(artist: Artist) -> str:
    return _serializer().dumps({"id": artist.id, "fp": _fingerprint(artist)})


def read_reset_token(token: str) -> Artist | None:
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=RESET_MAX_AGE)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    artist = db.session.get(Artist, payload.get("id") or 0)
    if artist is None:
        return None
    if payload.get("fp") != _fingerprint(artist):
        return None
    return artist
