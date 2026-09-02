"""La main humaine sur les actions sensibles.

Une action à risque ne s'exécute pas parce que K.A.E.L. la propose : elle
attend un jeton de confirmation, signé, court, et lié à ces paramètres-là.
Changer un seul paramètre invalide la confirmation — on ne confirme pas
« supprimer une œuvre » en général, on confirme celle-ci.
"""

from __future__ import annotations

import hashlib
import json

from flask import current_app
from itsdangerous import URLSafeTimedSerializer

SALT = "artworks-kael-confirm"
MAX_AGE = 600  # dix minutes : le temps de lire, pas celui d'oublier


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def fingerprint(tool: str, params: dict) -> str:
    """Empreinte stable de l'action exacte proposée."""
    payload = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{tool}:{payload}".encode("utf-8")).hexdigest()[:32]


def issue(tool: str, params: dict) -> str:
    return _serializer().dumps({"t": tool, "f": fingerprint(tool, params)})


def valid(token: str, tool: str, params: dict) -> bool:
    if not token:
        return False
    try:
        payload = _serializer().loads(token, max_age=MAX_AGE)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    return payload.get("t") == tool and payload.get("f") == fingerprint(tool, params)


def card(tool: str, params: dict, intent: str, consequences: list[str], target: str = "") -> dict:
    """Ce que K.A.E.L. doit montrer avant de demander « on y va ? »."""
    return {
        "tool": tool,
        "intent": intent,
        "target": target,
        "consequences": consequences,
        "irreversible": any("irréversible" in line.lower() for line in consequences),
        "confirm_token": issue(tool, params),
        "expires_in_seconds": MAX_AGE,
        "how": "Rappeler le même outil, mêmes paramètres, en ajoutant confirm_token.",
    }
