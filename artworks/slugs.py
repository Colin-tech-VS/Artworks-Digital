import re
import unicodedata

from artworks.models import Artist


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:80] or "galerie"


def unique_slug(value: str, artist_id: int | None = None) -> str:
    base = slugify(value)
    slug = base
    n = 2
    while True:
        query = Artist.query.filter_by(slug=slug)
        if artist_id:
            query = query.filter(Artist.id != artist_id)
        if query.first() is None:
            return slug
        slug = f"{base}-{n}"[:80]
        n += 1
