"""Rattrape les adresses de l’ancien site.

Les portfolios d’avant vivaient à `/artiste/<slug>`, `/portfolio/<slug>` ou
`/en/artist/<slug>` ; ils vivent désormais à `/galerie/<slug>`. Les moteurs
et les visiteurs, eux, connaissent encore les anciennes — et tombent sur une
porte fermée.

On ne redirige que lorsqu’on sait où mener : si la salle existe, la visite
continue ; sinon la page d’erreur reste, car une redirection vers l’accueil
n’aide personne et les moteurs la comptent comme une erreur déguisée.
"""

from __future__ import annotations

import re

# Les langues que l’ancien site préfixait à ses adresses.
LANGS = ("en", "ja", "ko", "fr", "es", "de", "it")
_LANG = "|".join(LANGS)

# Chaque motif livre le slug de l’artiste dans son premier groupe.
ARTIST_PATTERNS = tuple(
    re.compile(p)
    for p in (
        rf"^/(?:(?:{_LANG})/)?artistes?/([^/]+)",
        rf"^/(?:(?:{_LANG})/)?artist/([^/]+)",
        rf"^/(?:(?:{_LANG})/)?portfolio/([^/]+)",
        rf"^/(?:(?:{_LANG})/)?galerie/([^/]+)/",  # une œuvre dont l’identifiant a changé
    )
)

# Les répertoires d’avant mènent au répertoire d’aujourd’hui.
DIRECTORY_PATTERNS = tuple(
    re.compile(p)
    for p in (
        rf"^/(?:(?:{_LANG})/)?artistes?/?$",
        rf"^/(?:(?:{_LANG})/)?artists/?$",
        rf"^/(?:(?:{_LANG})/)?portfolios?/?$",
        rf"^/(?:(?:{_LANG})/)?galer(?:ies|y)/?$",
        r"^/marketplace(?:/.*)?$",
    )
)


def artist_slug(path: str) -> str | None:
    """Le slug d’artiste que porte une ancienne adresse, s’il y en a un."""
    for pattern in ARTIST_PATTERNS:
        found = pattern.match(path)
        if found:
            slug = found.group(1).strip().lower()
            # Une extension ou une ancre ne fait pas partie du nom.
            slug = re.sub(r"\.(html?|php|aspx?)$", "", slug)
            if slug and slug not in ("oeuvre", "artwork", "artworks"):
                return slug
    return None


def destination(path: str) -> str | None:
    """Où mène cette ancienne adresse — ou rien, si l’on ne sait pas."""
    from artworks.models import Artist

    slug = artist_slug(path)
    if slug:
        artist = Artist.query.filter_by(slug=slug, published=True).first()
        if artist is None:
            # Certains anciens slugs portaient des majuscules ou des suffixes.
            artist = Artist.query.filter(
                Artist.published.is_(True), db_lower(Artist.slug) == slug
            ).first()
        if artist is not None:
            return f"/galerie/{artist.slug}"
        return None

    for pattern in DIRECTORY_PATTERNS:
        if pattern.match(path):
            return "/galeries"
    return None


def db_lower(column):
    from artworks.extensions import db

    return db.func.lower(column)
