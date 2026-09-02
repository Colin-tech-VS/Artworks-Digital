"""Importe une base Artworks d’avant (V1 ou V2) dans le schéma actuel.

    python scripts/import_legacy.py --source postgresql://user:pass@host:5432/postgres
    python scripts/import_legacy.py --source /chemin/legacy.db --limit 20 --dry-run
    python scripts/import_legacy.py --source export.json --no-images

La source peut être :

* une URL Postgres — une restauration Supabase, un dump rechargé en local,
  un addon Scalingo encore vivant ;
* un fichier SQLite — l’ancienne ``instance/artworks.db`` ;
* un fichier JSON — ``{"artists": [...], "works": [...]}``, pratique quand on
  n’a plus qu’un export CSV converti à la main.

Deux schémas anciens sont reconnus :

* V2 « portfolio » — ``portfolio_artists`` / ``portfolio_paintings``
* V1 — ``artists`` / ``artworks``

Les empreintes de mot de passe sont conservées : elles viennent de Werkzeug
des deux côtés, donc les artistes se reconnectent avec leur mot de passe.
Les visuels sont retéléchargés depuis leur URL et stockés en base, comme le
reste de l’application. L’import est idempotent : un e-mail déjà présent est
ignoré, on peut relancer sans créer de doublon.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from artworks import create_app  # noqa: E402
from artworks.extensions import db  # noqa: E402
from artworks.images import save_bytes  # noqa: E402
from artworks.models import Artist, Work  # noqa: E402
from artworks.slugs import unique_slug  # noqa: E402

# (table artistes, table œuvres, clé étrangère)
SHAPES = (
    ("portfolio_artists", "portfolio_paintings", "artist_id"),
    ("artists", "artworks", "artist_id"),
)


def _rows(cursor) -> list[dict]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def read_postgres(dsn: str) -> tuple[list[dict], list[dict], str]:
    import psycopg2

    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            present = {row[0] for row in cursor.fetchall()}
            for artists_table, works_table, _ in SHAPES:
                if artists_table in present:
                    cursor.execute(f"SELECT * FROM {artists_table}")
                    artists = _rows(cursor)
                    works: list[dict] = []
                    if works_table in present:
                        cursor.execute(f"SELECT * FROM {works_table}")
                        works = _rows(cursor)
                    return artists, works, artists_table
    raise SystemExit("Aucune table d’artistes reconnue dans cette base.")


def read_sqlite(path: str) -> tuple[list[dict], list[dict], str]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    present = {
        row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for artists_table, works_table, _ in SHAPES:
        if artists_table in present:
            artists = [dict(row) for row in connection.execute(f"SELECT * FROM {artists_table}")]
            works = (
                [dict(row) for row in connection.execute(f"SELECT * FROM {works_table}")]
                if works_table in present
                else []
            )
            connection.close()
            return artists, works, artists_table
    connection.close()
    raise SystemExit("Aucune table d’artistes reconnue dans ce fichier.")


def read_json(path: str) -> tuple[list[dict], list[dict], str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("artists") or [], payload.get("works") or payload.get("paintings") or [], "json"


def load(source: str) -> tuple[list[dict], list[dict], str]:
    if source.startswith(("postgres://", "postgresql://")):
        return read_postgres(source)
    if source.endswith(".json"):
        return read_json(source)
    return read_sqlite(source)


def pick(row: dict, *names: str, default=""):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return default


def fetch_image(url: str, timeout: int = 25) -> bytes | None:
    """Rapatrie un visuel. Une URL morte n’interrompt pas l’import."""
    if not url:
        return None
    if not url.startswith("http"):
        # Chemin sur disque : absolu tel quel, sinon relatif au dossier courant.
        for candidate in (Path(url), Path(url.lstrip("/"))):
            if candidate.is_file():
                return candidate.read_bytes()
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "artworksdigital-import"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception:
        return None


def import_all(source: str, *, with_images: bool, limit: int, dry_run: bool, plan: str) -> dict:
    artists_raw, works_raw, shape = load(source)
    print(f"Source lue — schéma « {shape} » : {len(artists_raw)} artistes, {len(works_raw)} œuvres.")

    by_artist: dict[str, list[dict]] = {}
    for row in works_raw:
        by_artist.setdefault(str(pick(row, "artist_id", default="")), []).append(row)

    report = {"artists": 0, "skipped": 0, "works": 0, "images": 0, "images_lost": 0}

    for index, row in enumerate(artists_raw):
        if limit and index >= limit:
            break
        email = str(pick(row, "email")).strip().lower()
        if not email:
            report["skipped"] += 1
            continue
        if Artist.query.filter_by(email=email).first():
            print(f"  = {email} déjà présent, ignoré")
            report["skipped"] += 1
            continue

        name = str(pick(row, "display_name", "full_name", "name", default=email.split("@")[0]))
        artist = Artist(
            email=email,
            display_name=name[:120],
            slug=unique_slug(str(pick(row, "slug", default=name))),
            statement=str(pick(row, "artist_statement", "bio", "artistic_approach", "curatorial_note"))[:4000],
            location=str(pick(row, "location"))[:120],
            discipline=str(pick(row, "art_style", "artistic_style", "headline"))[:120],
            contact_email=email,
            plan_key=plan,
            published=str(pick(row, "status", default="active")).lower() == "active",
        )
        # L’empreinte Werkzeug traverse : le mot de passe de l’artiste reste valable.
        password_hash = str(pick(row, "password_hash"))
        if password_hash:
            artist.password_hash = password_hash
        else:
            artist.set_password(os.urandom(16).hex())

        cover = str(pick(row, "profile_photo_url", "profile_photo", "cover_path"))
        if with_images and cover and not dry_run:
            payload = fetch_image(cover)
            if payload:
                artist.cover_path = save_bytes(payload)
                report["images"] += 1
            else:
                report["images_lost"] += 1

        print(f"  + {artist.display_name} <{email}> /galerie/{artist.slug}")
        report["artists"] += 1
        if not dry_run:
            db.session.add(artist)
            db.session.flush()

        for position, work_row in enumerate(by_artist.get(str(pick(row, "id", default="")), [])):
            title = str(pick(work_row, "title", default="Sans titre"))[:180]
            image_url = str(pick(work_row, "image_url", "image"))
            image_name = ""
            if with_images and not dry_run:
                payload = fetch_image(image_url)
                if payload:
                    image_name = save_bytes(payload)
                    report["images"] += 1
                else:
                    report["images_lost"] += 1
            if not image_name and not dry_run:
                # Sans visuel, l’œuvre ne peut pas être accrochée : on la passe.
                print(f"      · {title} — visuel introuvable, œuvre ignorée")
                continue
            report["works"] += 1
            if dry_run:
                continue
            db.session.add(
                Work(
                    artist_id=artist.id,
                    title=title,
                    year=str(pick(work_row, "year", "year_created"))[:12],
                    medium=str(pick(work_row, "medium", "technique"))[:160],
                    dimensions=str(pick(work_row, "dimensions"))[:120],
                    note=str(pick(work_row, "description", "note"))[:2000],
                    image_path=image_name,
                    collection_name=str(pick(work_row, "group_name", "collection_name"))[:120],
                    visible=str(pick(work_row, "is_selected", default="1")) not in ("0", "False", "false"),
                    position=int(pick(work_row, "display_order", "position", default=position) or position),
                )
            )

    if dry_run:
        db.session.rollback()
        print("\n— essai à blanc : rien n’a été écrit —")
    else:
        db.session.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Importer une ancienne base Artworks.")
    parser.add_argument("--source", required=True, help="URL Postgres, fichier SQLite ou JSON")
    parser.add_argument("--limit", type=int, default=0, help="n’importer que les N premiers artistes")
    parser.add_argument("--dry-run", action="store_true", help="afficher sans rien écrire")
    parser.add_argument("--no-images", action="store_true", help="ne pas retélécharger les visuels")
    parser.add_argument("--plan", default="decouverte", help="offre attribuée aux comptes importés")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        report = import_all(
            args.source,
            with_images=not args.no_images,
            limit=args.limit,
            dry_run=args.dry_run,
            plan=args.plan,
        )
    print(
        "\nRésultat — "
        f"{report['artists']} artiste(s), {report['works']} œuvre(s), "
        f"{report['images']} visuel(s) récupéré(s), {report['images_lost']} perdu(s), "
        f"{report['skipped']} ignoré(s)."
    )


if __name__ == "__main__":
    main()
