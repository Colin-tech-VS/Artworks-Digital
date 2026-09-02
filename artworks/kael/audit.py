"""Le journal des actions de K.A.E.L.

Rien de ce que K.A.E.L. fait sur la plateforme n'est invisible : chaque
appel d'outil laisse une ligne, réussite comme échec, avec ce qu'il visait
et s'il a fallu une main humaine.
"""

from __future__ import annotations

import json

from flask import request

from artworks.extensions import db
from artworks.models import KaelAuditLog

#: Ce qui ne doit jamais entrer dans le journal, même passé par erreur.
REDACTED = {"password", "secret", "token", "api_key", "authorization", "confirm_token"}


def _clean(params: dict | None) -> str:
    safe = {}
    for key, value in (params or {}).items():
        if str(key).lower() in REDACTED:
            safe[key] = "•••"
        elif isinstance(value, str) and len(value) > 400:
            safe[key] = value[:400] + "…"
        else:
            safe[key] = value
    try:
        return json.dumps(safe, ensure_ascii=False, default=str)[:4000]
    except Exception:
        return "{}"


def record(
    *,
    tool: str,
    permission: str,
    params: dict | None,
    ok: bool,
    summary: str = "",
    error: str = "",
    grant=None,
    confirmed: bool = False,
    subject_kind: str = "",
    subject_id: str = "",
    duration_ms: int = 0,
) -> None:
    row = KaelAuditLog(
        token_id=grant.token.id if grant else None,
        token_label=(grant.label if grant else "")[:120],
        tool=tool[:80],
        permission=permission[:30],
        params_json=_clean(params),
        ok=ok,
        summary=(summary or "")[:400],
        error=(error or "")[:2000],
        confirmed=confirmed,
        actor=(grant.label if grant else "K.A.E.L.")[:120],
        subject_kind=subject_kind[:30],
        subject_id=str(subject_id)[:40],
        duration_ms=int(duration_ms),
        remote_addr=(request.headers.get("X-Forwarded-For", request.remote_addr or "") or "")[:60],
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def recent(limit: int = 100, *, only_failures: bool = False) -> list[KaelAuditLog]:
    query = KaelAuditLog.query
    if only_failures:
        query = query.filter_by(ok=False)
    return query.order_by(KaelAuditLog.created_at.desc()).limit(limit).all()
