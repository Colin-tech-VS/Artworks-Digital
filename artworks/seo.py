from pathlib import Path

from flask import current_app, redirect, request, url_for

# Nom tel qu’on le cherche, et tel que la barre l’écrit. L’extrait Google
# a soixante signes : autant que la marque tienne entière, avec les mots
# qui disent la galerie.
SITE_NAME = "Artworks Digital"
SITE_SLOGAN = "chaque artiste ouvre sa galerie"
TITLE_LIMIT = 58
DESC_LIMIT = 158
ALT_LIMIT = 125


def meta_trim(text: str, limit: int = DESC_LIMIT) -> str:
    """Coupe une description au dernier mot entier : les moteurs n’affichent
    qu’environ 160 signes, autant choisir où la phrase s’arrête."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:–—-") + "…"


def page_title(primary: str, suffix: str | None = SITE_NAME, limit: int = TITLE_LIMIT) -> str:
    """Titre d’onglet : l’essentiel d’abord, la marque ensuite, jamais trop long."""
    primary = " ".join((primary or "").split())
    suffix = " ".join((suffix or "").split())
    if not primary:
        return meta_trim(suffix or SITE_NAME, limit)
    if not suffix:
        return meta_trim(primary, limit)
    combined = f"{primary} — {suffix}"
    if len(combined) <= limit:
        return combined
    extra = f" — {suffix}"
    budget = limit - len(extra)
    if budget >= 12:
        return meta_trim(primary, budget) + extra
    return meta_trim(primary, limit)


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
