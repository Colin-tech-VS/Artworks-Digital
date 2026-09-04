"""Recherche des salles publiées.

Le visiteur tape un nom, une discipline, une ville : on range les adresses
qui correspondent. Chaque résultat reste une galerie d’artiste, pas une
fiche dans un catalogue commun.
"""

from __future__ import annotations

import unicodedata
from collections import Counter

from sqlalchemy import case, func

from artworks.extensions import db
from artworks.models import Artist, Work
from artworks.seo import absolute_media


def fold(text: str) -> str:
    """Minuscules sans accents : « Côte » trouve « cote »."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def tokens(query: str) -> list[str]:
    return [part for part in fold(query).replace("-", " ").split() if part]


def room_letter(name: str) -> str:
    for ch in fold(name):
        if ch.isalpha():
            return ch.upper()
    return "#"


def room_haystack(artist: Artist) -> str:
    return fold(
        " ".join(
            part
            for part in (
                artist.display_name,
                artist.slug,
                artist.discipline,
                artist.location,
                (artist.statement or "")[:280],
            )
            if part
        )
    )


def _score(artist: Artist, parts: list[str]) -> int:
    name = fold(artist.display_name)
    slug = fold(artist.slug)
    discipline = fold(artist.discipline)
    location = fold(artist.location)
    hay = room_haystack(artist)
    joined = " ".join(parts)
    score = 0
    if name == joined:
        score += 200
    elif name.startswith(joined):
        score += 140
    elif joined in name:
        score += 100
    if all(part in slug for part in parts):
        score += 60
    if all(part in discipline for part in parts):
        score += 40
    if all(part in location for part in parts):
        score += 40
    if all(part in hay for part in parts):
        score += 10
    return score + artist.plan_rank


def matches(artist: Artist, query: str) -> bool:
    parts = tokens(query)
    if not parts:
        return True
    hay = room_haystack(artist)
    return all(part in hay for part in parts)


def search_rooms(rooms: list[Artist], query: str) -> list[Artist]:
    parts = tokens(query)
    if not parts:
        return list(rooms)
    found = [artist for artist in rooms if matches(artist, query)]
    found.sort(key=lambda artist: (-_score(artist, parts), fold(artist.display_name)))
    return found


def open_rooms() -> list[Artist]:
    rank = case(
        (Artist.plan_key == "studio", 4),
        (Artist.plan_key == "pro", 3),
        (Artist.plan_key == "artiste", 2),
        else_=1,
    )
    return (
        Artist.query.filter_by(published=True)
        .order_by(rank.desc(), Artist.updated_at.desc(), Artist.created_at.desc())
        .all()
    )


def public_work_counts(rooms: list[Artist]) -> dict[int, int]:
    """Nombre d’œuvres visibles, plafonné par l’offre — une requête pour toutes les salles."""
    ids = [artist.id for artist in rooms]
    if not ids:
        return {}
    raw = dict(
        db.session.query(Work.artist_id, func.count(Work.id))
        .filter(Work.artist_id.in_(ids), Work.visible.is_(True))
        .group_by(Work.artist_id)
        .all()
    )
    counts: dict[int, int] = {}
    for artist in rooms:
        hung = int(raw.get(artist.id, 0))
        limit = artist.work_limit()
        counts[artist.id] = hung if not limit else min(hung, limit)
    return counts


def hung_works_by_artist(rooms: list[Artist]) -> dict[int, list[Work]]:
    """Accrochages publics, pour le sitemap, sans N+1."""
    ids = [artist.id for artist in rooms]
    grouped: dict[int, list[Work]] = {artist.id: [] for artist in rooms}
    if not ids:
        return grouped
    rows = (
        Work.query.filter(Work.artist_id.in_(ids), Work.visible.is_(True))
        .order_by(Work.position.asc(), Work.id.desc())
        .all()
    )
    for work in rows:
        grouped.setdefault(work.artist_id, []).append(work)
    for artist in rooms:
        limit = artist.work_limit()
        if limit:
            grouped[artist.id] = grouped.get(artist.id, [])[:limit]
    return grouped


def directory_facets(rooms: list[Artist]) -> dict:
    letters = sorted({room_letter(artist.display_name) for artist in rooms}, key=lambda ch: (ch == "#", ch))
    counted = Counter(
        (artist.discipline or "").strip()
        for artist in rooms
        if (artist.discipline or "").strip()
    )
    return {
        "letters": letters,
        "disciplines": [name for name, _count in counted.most_common(12)],
    }


def rooms_index(rooms: list[Artist], counts: dict[int, int] | None = None) -> list[dict]:
    counts = counts if counts is not None else public_work_counts(rooms)
    payload = []
    for artist in rooms:
        payload.append(
            {
                "id": artist.id,
                "name": artist.display_name,
                "slug": artist.slug,
                "url": f"/galerie/{artist.slug}",
                "discipline": artist.discipline or "",
                "location": artist.location or "",
                "works": counts.get(artist.id, 0),
                "cover": absolute_media(artist.cover_path) if artist.cover_path else "",
                "hay": room_haystack(artist),
                "letter": room_letter(artist.display_name),
            }
        )
    return payload


def wall_works(rooms: list[Artist], limit: int = 12, per_room: int = 2) -> list[Work]:
    """Ce qui est accroché en ce moment, toutes salles confondues.

    L'accueil montrait des noms ; il montre des œuvres. On en prend au
    plus `per_room` par salle pour qu'une salle bien remplie ne mange pas
    le mur, et on suit l'ordre des salles — les offres hautes d'abord,
    c'est ce qu'elles paient.

    Une seule requête pour tout le mur : la page d'accueil ne doit pas
    coûter une requête par artiste.
    """
    ids = [artist.id for artist in rooms]
    if not ids or limit <= 0:
        return []
    rows = (
        Work.query.filter(Work.artist_id.in_(ids), Work.visible.is_(True))
        .order_by(Work.artist_id.asc(), Work.position.asc(), Work.id.desc())
        .all()
    )
    by_room: dict[int, list[Work]] = {}
    for work in rows:
        by_room.setdefault(work.artist_id, []).append(work)

    # Le plafond de l'offre s'applique ici aussi : une œuvre au-delà du
    # plafond n'est pas publique, elle n'a rien à faire sur le mur.
    for artist in rooms:
        cap = artist.work_limit()
        if cap:
            by_room[artist.id] = by_room.get(artist.id, [])[:cap]

    picked: list[Work] = []
    for rank in range(per_room):
        for artist in rooms:
            bucket = by_room.get(artist.id) or []
            if rank < len(bucket):
                picked.append(bucket[rank])
            if len(picked) >= limit:
                return picked
    return picked


def room_previews(rooms: list[Artist], per_room: int = 3) -> dict[int, list[Work]]:
    """Trois œuvres par salle, pour la bande sous une carte du répertoire."""
    grouped = hung_works_by_artist(rooms)
    return {artist_id: works[:per_room] for artist_id, works in grouped.items()}


def discipline_slug(name: str) -> str:
    """« Art numérique » devient « art-numerique » : une adresse propre."""
    folded = fold(name)
    kept = [ch if (ch.isalnum()) else "-" for ch in folded]
    return "-".join(part for part in "".join(kept).split("-") if part)


def disciplines_index(rooms: list[Artist]) -> list[dict]:
    """Les disciplines réellement présentes, avec leur compte et leur adresse.

    C'est le seul découpage du répertoire qui ait un sens pour un visiteur
    comme pour un moteur : on ne cherche pas « une galerie », on cherche
    « une galerie de photographie »."""
    counted = Counter()
    labels: dict[str, str] = {}
    for artist in rooms:
        name = (artist.discipline or "").strip()
        if not name:
            continue
        slug = discipline_slug(name)
        if not slug:
            continue
        counted[slug] += 1
        labels.setdefault(slug, name)
    return [
        {"slug": slug, "name": labels[slug], "count": count}
        for slug, count in sorted(counted.items(), key=lambda row: (-row[1], labels[row[0]]))
    ]


def rooms_of_discipline(rooms: list[Artist], slug: str) -> list[Artist]:
    return [artist for artist in rooms if discipline_slug(artist.discipline or "") == slug]


def kin_rooms(rooms: list[Artist], artist: Artist, limit: int = 4) -> list[Artist]:
    """Les salles voisines : même discipline d'abord, puis même ville.

    Une salle sans porte de sortie est une impasse — pour le visiteur qui
    a fini sa visite comme pour le moteur qui suit les liens."""
    slug = discipline_slug(artist.discipline or "")
    town = fold(artist.location or "")
    same_art, same_town, rest = [], [], []
    for other in rooms:
        if other.id == artist.id:
            continue
        if slug and discipline_slug(other.discipline or "") == slug:
            same_art.append(other)
        elif town and fold(other.location or "") == town:
            same_town.append(other)
        else:
            rest.append(other)
    return (same_art + same_town + rest)[:limit]
