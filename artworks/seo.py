from pathlib import Path

from flask import current_app, redirect, request, url_for


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


def static_url(filename: str) -> str:
    """URL statique avec l’empreinte du fichier : un an de cache, et pourtant
    la moindre modification arrive tout de suite chez le visiteur."""
    path = Path(current_app.static_folder or "") / filename
    try:
        stamp = int(path.stat().st_mtime)
    except OSError:
        return url_for("static", filename=filename)
    return url_for("static", filename=filename, v=stamp)


def canonical_redirect():
    """Un seul hôte, un seul schéma : le reste part en 301.

    Sans cela, https://artworksdigital.fr et https://www.artworksdigital.fr
    servent les mêmes pages à deux adresses, et l’indexation se divise.
    """
    host = (current_app.config.get("CANONICAL_HOST") or "").strip()
    if not host or current_app.config.get("CANONICAL_REDIRECT") is False:
        return None
    if request.method not in ("GET", "HEAD"):
        return None
    incoming = (request.host or "").lower()
    # En local et en préproduction, on ne redirige pas vers le domaine public.
    if incoming.startswith(("127.0.0.1", "localhost", "0.0.0.0")) or incoming.endswith(".local"):
        return None
    scheme = current_app.config.get("CANONICAL_SCHEME") or "https"
    if incoming == host.lower() and request.scheme == scheme:
        return None
    target = f"{scheme}://{host}{request.full_path.rstrip('?') if request.query_string else request.path}"
    return redirect(target, code=301)
