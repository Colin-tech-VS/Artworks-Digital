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


def media_url(filename: str | None, width: int | None = None) -> str:
    """L'adresse d'un visuel, éventuellement à une largeur donnée."""
    if not filename:
        return url_for("static", filename="og-default.jpg")
    if width:
        return url_for("media_variant", width=width, filename=filename)
    return url_for("media", filename=filename)


def media_srcset(filename: str | None, natural_width: int = 0) -> str:
    """Le jeu de largeurs d'un visuel, pour que le navigateur choisisse.

    On n'annonce jamais une largeur que l'original n'a pas : promettre du
    1600 px pour une image qui en fait 900 ferait télécharger le gros
    fichier pour rien, exactement le contraire du but. Quand la largeur
    d'origine est inconnue (les visuels d'avant la mesure), on s'arrête à
    la déclinaison moyenne, qui ne trahit personne."""
    from artworks.images import VARIANT_WIDTHS

    if not filename:
        return ""
    ceiling = natural_width if natural_width and natural_width > 0 else VARIANT_WIDTHS[1]
    parts = [f"{media_url(filename, w)} {w}w" for w in VARIANT_WIDTHS if w <= ceiling]
    if natural_width and natural_width > VARIANT_WIDTHS[-1]:
        parts.append(f"{media_url(filename)} {natural_width}w")
    return ", ".join(parts)
