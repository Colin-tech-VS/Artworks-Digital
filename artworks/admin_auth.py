from hmac import compare_digest

from flask import current_app, redirect, request, session, url_for


SESSION_KEY = "admin_signed_in"


def _same(left: str, right: str) -> bool:
    a = (left or "").encode("utf-8")
    b = (right or "").encode("utf-8")
    if len(a) != len(b):
        compare_digest(b, b)
        return False
    return compare_digest(a, b)


def admin_is_in() -> bool:
    return bool(session.get(SESSION_KEY))


def try_admin_login(username: str, password: str) -> bool:
    expected_user = current_app.config.get("ADMIN_USERNAME") or ""
    expected_pass = current_app.config.get("ADMIN_PASSWORD") or ""
    if not expected_user or not expected_pass:
        return False
    if _same(username.strip(), expected_user) and _same(password, expected_pass):
        session[SESSION_KEY] = True
        session.permanent = True
        return True
    return False


def admin_logout() -> None:
    session.pop(SESSION_KEY, None)


def require_admin():
    if admin_is_in():
        return None
    return redirect(url_for("admin.login", next=request.path))
