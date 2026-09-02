from hmac import compare_digest

from flask import current_app, redirect, request, session, url_for


SESSION_KEY = "site_unlocked"


def site_is_gated() -> bool:
    return bool(current_app.config.get("SITE_UNLOCK_PASSWORD"))


def site_is_open() -> bool:
    if not site_is_gated():
        return True
    return bool(session.get(SESSION_KEY))


def try_unlock(password: str) -> bool:
    expected = current_app.config.get("SITE_UNLOCK_PASSWORD") or ""
    if expected and compare_digest(password, expected):
        session[SESSION_KEY] = True
        session.permanent = True
        return True
    return False


def enforce_gate():
    if site_is_open():
        return None
    if request.endpoint in (None, "static", "public.home"):
        return None
    return redirect(url_for("public.home"))
