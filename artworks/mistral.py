import json
import urllib.error
import urllib.request

from flask import current_app


def mistral_ready() -> bool:
    return bool(current_app.config.get("MISTRAL_API_KEY"))


def complete(prompt: str, *, heavy: bool = False, max_tokens: int = 400) -> str:
    key = current_app.config.get("MISTRAL_API_KEY") or ""
    if not key:
        raise RuntimeError("Clé Mistral absente.")
    model = current_app.config.get("MISTRAL_MODEL_HEAVY" if heavy else "MISTRAL_MODEL") or "mistral-small-latest"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", "replace")[:240]) from exc
    choices = data.get("choices") or []
    if not choices:
        return ""
    return ((choices[0].get("message") or {}).get("content") or "").strip()
