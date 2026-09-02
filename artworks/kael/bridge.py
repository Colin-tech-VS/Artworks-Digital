"""Le pont vers K.A.E.L.

Artworks Digital ne réfléchit pas à la place de K.A.E.L. : il lui parle.
Ce module poste sur le ``/chat`` du centre de commande, en joignant le
contexte de la page. Le jeton d'accès reste ici, côté serveur ; le
navigateur ne le voit jamais.

Rien n'est créé côté K.A.E.L. : on utilise son API telle qu'elle est.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from flask import current_app

TIMEOUT = 90


def configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("KAEL_API_URL") and (cfg.get("KAEL_API_KEY") or cfg.get("KAEL_API_TOKEN")))


def _endpoint() -> str:
    base = (current_app.config.get("KAEL_API_URL") or "").rstrip("/")
    return f"{base}/chat"


def context_block(extra: dict | None = None) -> dict:
    """Ce que K.A.E.L. doit savoir sans avoir à le demander."""
    from artworks.kael.registry import manifest
    from artworks.seo import canonical_url

    block = {
        "application": "artworks-digital",
        "application_name": "Artworks Digital",
        "site_url": canonical_url("/").rstrip("/"),
        "tools_url": canonical_url("/api/kael"),
        "tools_available": [tool["name"] for tool in manifest()["tools"]],
        "note": (
            "Les outils Artworks Digital s'appellent en POST sur "
            "{tools_url}/tools/<nom> avec l'en-tête Authorization: Bearer <jeton>. "
            "Le manifeste complet est sur {tools_url}/manifest."
        ),
    }
    for key, value in (extra or {}).items():
        if value not in (None, "", []):
            block[key] = value
    return block


def ask(message: str, *, context: dict | None = None, conversation_id=None) -> dict:
    """Pose une question à K.A.E.L. et rend sa réponse telle quelle."""
    if not configured():
        return {
            "ok": False,
            "error": (
                "K.A.E.L. n’est pas branché : renseignez KAEL_API_URL et "
                "KAEL_API_KEY dans l’environnement."
            ),
        }

    block = context_block(context)
    payload = {
        # Le contexte voyage dans le message : le /chat de K.A.E.L. prend un
        # texte, on n'invente pas de champ qui n'existe pas chez lui.
        "message": (
            f"[contexte Artworks Digital]\n"
            f"{json.dumps(block, ensure_ascii=False, indent=2)}\n"
            f"[/contexte]\n\n{message}"
        ),
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    agent = current_app.config.get("KAEL_AGENT") or ""
    if agent:
        payload["agent"] = agent

    request_object = urllib.request.Request(
        _endpoint(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": (
                f"Bearer {current_app.config.get('KAEL_API_KEY') or current_app.config.get('KAEL_API_TOKEN')}"
            ),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_object, timeout=TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "error": f"K.A.E.L. a répondu HTTP {exc.code} : {detail}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"K.A.E.L. est injoignable : {exc.reason}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Échange interrompu : {exc}"}

    return {
        "ok": True,
        "reply": _reply_of(data),
        "conversation_id": data.get("conversation_id"),
        "raw": data,
    }


def _reply_of(data: dict) -> str:
    """K.A.E.L. peut nommer sa réponse de plusieurs façons ; on les accepte."""
    for key in ("reply", "message", "content", "answer", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            inner = value.get("content") or value.get("text")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    messages = data.get("messages")
    if isinstance(messages, list) and messages:
        last = messages[-1]
        if isinstance(last, dict):
            content = last.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return "K.A.E.L. n’a rien répondu."
