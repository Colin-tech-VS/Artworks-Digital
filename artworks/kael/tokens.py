"""Accès de K.A.E.L. à Artworks Digital.

K.A.E.L. présente ``KAEL_API_KEY`` (Scalingo). Artworks ne crée pas ce
secret : il le vérifie, puis ouvre toute la plateforme.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from flask import current_app
from werkzeug.security import check_password_hash

from artworks.extensions import db
from artworks.kael import permissions
from artworks.models import Artist, KaelToken, utcnow

PREFIX = "kael"


@dataclass(frozen=True)
class Grant:
    """Ce que la clé présentée autorise réellement, une fois vérifiée."""

    scopes: frozenset[str]
    artist_id: int | None
    label: str = "K.A.E.L."
    token: KaelToken | None = None

    def allows(self, required: str) -> bool:
        return required in self.scopes

    @property
    def artist(self) -> Artist | None:
        if self.artist_id is None:
            return None
        return db.session.get(Artist, self.artist_id)


def _env_keys() -> list[str]:
    cfg = current_app.config
    keys = []
    for name in ("KAEL_API_KEY", "KAEL_API_TOKEN"):
        value = (cfg.get(name) or "").strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def _same_secret(presented: str, expected: str) -> bool:
    if not presented or not expected or len(presented) != len(expected):
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def parse(raw: str) -> tuple[str, str] | None:
    """Sépare préfixe et secret sans rien dévoiler d'autre."""
    raw = (raw or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    parts = raw.split("_", 2)
    if len(parts) != 3 or parts[0] != PREFIX:
        return None
    return parts[1], parts[2]


def verify(raw: str) -> Grant | None:
    """Rend les droits de la clé présentée, ou rien du tout."""
    presented = (raw or "").strip()
    if presented.lower().startswith("bearer "):
        presented = presented[7:].strip()
    for key in _env_keys():
        if _same_secret(presented, key):
            return Grant(
                scopes=frozenset(permissions.ALL),
                artist_id=None,
                label="K.A.E.L.",
            )
    parsed = parse(presented)
    if parsed is None:
        return None
    prefix, secret = parsed
    row = KaelToken.query.filter_by(prefix=prefix, active=True).first()
    if row is None:
        return None
    if not check_password_hash(row.secret_hash, secret):
        return None
    row.last_used_at = utcnow()
    row.use_count = (row.use_count or 0) + 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return Grant(
        scopes=permissions.expand(row.scopes),
        artist_id=row.artist_id,
        label=row.label,
        token=row,
    )
