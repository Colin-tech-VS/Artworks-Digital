from flask import current_app, request, url_for


def canonical_url(path: str | None = None) -> str:
    host = current_app.config.get("CANONICAL_HOST") or request.host
    scheme = current_app.config.get("CANONICAL_SCHEME") or "https"
    if path is None:
        path = request.path or "/"
    if path.startswith("http"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{scheme}://{host}{path}"


def absolute_media(filename: str | None) -> str:
    if not filename:
        return canonical_url(url_for("static", filename="og-default.jpg"))
    return canonical_url(url_for("media", filename=filename))


def default_og_image() -> str:
    return canonical_url(url_for("static", filename="og-default.jpg"))
