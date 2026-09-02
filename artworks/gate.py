from hmac import compare_digest

from flask import current_app, redirect, request, session, url_for


SESSION_KEY = "site_unlocked"

OPEN_ENDPOINTS = {
    None,
    "static",
    "media",
    "public.home",
    "public.gallery",
    "public.artwork",
    "public.galleries",
    "public.sitemap",
    "public.robots",
    "public.offers",
    "public.contact",
    "billing.stripe_webhook",
}


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
    if request.endpoint in OPEN_ENDPOINTS:
        return None
    if request.endpoint and (
        request.endpoint.startswith("atelier.")
        or request.endpoint.startswith("admin.")
        or request.endpoint in ("auth.login", "auth.logout", "auth.forgot_password", "auth.reset_password")
    ):
        return None
    return redirect(url_for("public.home"))
