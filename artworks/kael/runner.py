"""L'exécution d'un outil, avec tout ce qui l'entoure.

Un même chemin pour tous les appels : vérifier le droit, valider les
paramètres, demander la main humaine si l'action est sensible, exécuter,
journaliser. Aucun outil ne s'appelle en dehors d'ici.
"""

from __future__ import annotations

import inspect
import time

from artworks.extensions import db
from artworks.kael import audit, confirm
from artworks.kael.registry import (
    ConfirmationRequired,
    PermissionDenied,
    ToolError,
    get,
)
from artworks.kael.tools import consequences_for, subject_of


def _accepted(handler) -> tuple[set[str], bool]:
    """Paramètres que la fonction accepte, et si elle tolère le reste."""
    signature = inspect.signature(handler)
    names, catch_all = set(), False
    for index, (name, param) in enumerate(signature.parameters.items()):
        if index == 0:
            continue  # le premier argument est toujours le droit accordé
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            catch_all = True
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        names.add(name)
    return names, catch_all


def run(name: str, params: dict, grant, *, confirm_token: str = "") -> dict:
    """Exécute un outil et rend une enveloppe uniforme."""
    started = time.perf_counter()
    params = dict(params or {})
    spec = get(name)

    if spec is None:
        audit.record(tool=name, permission="", params=params, ok=False,
                     error="Outil inconnu.", grant=grant)
        raise ToolError(f"Outil inconnu : {name}.")

    if not grant.allows(spec.permission):
        audit.record(tool=name, permission=spec.permission, params=params, ok=False,
                     error=f"Portée {spec.permission} absente du jeton.", grant=grant)
        raise PermissionDenied(
            f"L’outil « {name} » exige la portée {spec.permission}, "
            f"que ce jeton ne porte pas."
        )

    allowed, catch_all = _accepted(spec.handler)
    if catch_all:
        # Une signature en **kwargs avalerait un paramètre mal orthographié
        # sans rien dire. Le schéma déclaré fait alors foi.
        allowed = set(spec.parameters.get("properties") or {}) or allowed
    unknown = sorted(set(params) - allowed)
    if unknown:
        audit.record(tool=name, permission=spec.permission, params=params, ok=False,
                     error=f"Paramètres inconnus : {unknown}.", grant=grant)
        raise ToolError(
            f"Paramètre(s) inconnu(s) pour « {name} » : {', '.join(unknown)}. "
            f"Attendus : {', '.join(sorted(allowed)) or 'aucun'}."
        )
    missing = [n for n in (spec.parameters.get("required") or []) if params.get(n) in (None, "")]
    if missing:
        raise ToolError(f"Paramètre(s) requis manquant(s) : {', '.join(missing)}.")

    confirmed = False
    if spec.needs_confirmation:
        if not confirm.valid(confirm_token, name, params):
            intent, consequences, target = consequences_for(name, params)
            raise ConfirmationRequired(name, intent, consequences, target)
        confirmed = True

    kind, subject = subject_of(name, params)
    try:
        data = spec.handler(grant, **params)
    except (ToolError, PermissionDenied) as exc:
        audit.record(tool=name, permission=spec.permission, params=params, ok=False,
                     error=str(exc), grant=grant, confirmed=confirmed,
                     subject_kind=kind, subject_id=subject,
                     duration_ms=int((time.perf_counter() - started) * 1000))
        raise
    except Exception as exc:  # noqa: BLE001 — journalisé puis remonté proprement
        db.session.rollback()
        audit.record(tool=name, permission=spec.permission, params=params, ok=False,
                     error=f"{type(exc).__name__}: {exc}", grant=grant, confirmed=confirmed,
                     subject_kind=kind, subject_id=subject,
                     duration_ms=int((time.perf_counter() - started) * 1000))
        raise ToolError(f"L’outil « {name} » a échoué : {exc}") from exc

    duration = int((time.perf_counter() - started) * 1000)
    summary = _summarize(name, data)
    audit.record(tool=name, permission=spec.permission, params=params, ok=True,
                 summary=summary, grant=grant, confirmed=confirmed,
                 subject_kind=kind, subject_id=subject, duration_ms=duration)
    return {
        "ok": True,
        "tool": name,
        "permission": spec.permission,
        "mutating": spec.mutating,
        "confirmed": confirmed,
        "duration_ms": duration,
        "summary": summary,
        "data": data,
    }


def _summarize(name: str, data) -> str:
    """Une ligne lisible dans le journal — pas un dump."""
    if not isinstance(data, dict):
        return name
    for key in ("count", "score", "sent", "now"):
        if key in data:
            return f"{name} → {key}={data[key]}"
    if "changed" in data:
        fields = ", ".join(data["changed"]) or "aucun champ"
        return f"{name} → {fields}"
    if "published" in data and isinstance(data["published"], list):
        return f"{name} → publié sur {', '.join(data['published']) or 'aucun réseau'}"
    if "deleted" in data:
        return f"{name} → supprimé {data['deleted'].get('title', '')}"
    if "anomalies" in data:
        return f"{name} → {len(data['anomalies'])} anomalie(s)"
    return name
