"""Jetons d'accès de K.A.E.L.

Un jeton se présente sous la forme ``kael_<préfixe>_<secret>``. Seul le
préfixe est indexé ; le secret n'existe en clair qu'au moment où on le crée
et l'affiche une fois. Ensuite, seule son empreinte reste.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from werkzeug.security import check_password_hash, generate_password_hash

from artworks.extensions import db
from artworks.kael import permissions
from artworks.models import Artist, KaelToken, utcnow

PREFIX = "kael"


@dataclass(frozen=True)
class Grant:
    """Ce qu'un jeton présenté autorise réellement, une fois vérifié."""

    token: KaelToken
    scopes: frozenset[str]
    artist_id: int | None

    @property
    def label(self) -> str:
        return self.token.label

    def allows(self, required: str) -> bool:
        return required in self.scopes

    @property
    def artist(self) -> Artist | None:
        if self.artist_id is None:
            return None
        return db.session.get(Artist, self.artist_id)


def issue(label: str, scopes, *, artist_id: int | None = None) -> tuple[KaelToken, str]:
    """Crée un jeton et rend le secret en clair — la seule et unique fois."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    row = KaelToken(
        label=(label or "K.A.E.L.").strip()[:120],
        prefix=prefix,
        secret_hash=generate_password_hash(secret),
        artist_id=artist_id,
        active=True,
    )
    row.scopes = permissions.normalize(scopes)
    db.session.add(row)
    db.session.commit()
    return row, f"{PREFIX}_{prefix}_{secret}"


def revoke(token_id: int) -> bool:
    row = db.session.get(KaelToken, token_id)
    if row is None:
        return False
    row.active = False
    db.session.commit()
    return True


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
    """Rend les droits du jeton présenté, ou rien du tout."""
    parsed = parse(raw)
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
        token=row,
        scopes=permissions.expand(row.scopes),
        artist_id=row.artist_id,
    )
