"""Importe une base Artworks d’avant (V1 ou V2) dans le schéma actuel.

    python scripts/import_legacy.py --source postgresql://user:pass@host:5432/postgres
    python scripts/import_legacy.py --source /chemin/legacy.db --limit 20 --dry-run
    python scripts/import_legacy.py --source export.json --no-images

Si la base a survécu mais que son projet a changé d’adresse, les URLs des
visuels pointent dans le vide : ``--media-base`` les recolle sur l’hôte qui
les sert aujourd’hui.

    python scripts/import_legacy.py --source postgresql://… \
        --media-base https://<ref>.supabase.co/storage/v1/object/public/uploads/

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
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from artworks import create_app  # noqa: E402
from artworks.extensions import db  # noqa: E402
from PIL import Image  # noqa: E402

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
            best: tuple[list[dict], list[dict], str] | None = None
            for artists_table, works_table, _ in SHAPES:
                if artists_table not in present:
                    continue
                cursor.execute(f"SELECT * FROM {artists_table}")
                artists = _rows(cursor)
                works: list[dict] = []
                if works_table in present:
                    cursor.execute(f"SELECT * FROM {works_table}")
                    works = _rows(cursor)
                if best is None or len(artists) > len(best[0]):
                    best = (artists, works, artists_table)
            if best:
                return best
    raise SystemExit("Aucune table d’artistes reconnue dans cette base.")


def read_sqlite(path: str) -> tuple[list[dict], list[dict], str]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    present = {
        row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    best: tuple[list[dict], list[dict], str] | None = None
    for artists_table, works_table, _ in SHAPES:
        if artists_table not in present:
            continue
        artists = [dict(row) for row in connection.execute(f"SELECT * FROM {artists_table}")]
        works = (
            [dict(row) for row in connection.execute(f"SELECT * FROM {works_table}")]
            if works_table in present
            else []
        )
        if best is None or len(artists) > len(best[0]):
            best = (artists, works, artists_table)
    connection.close()
    if best:
        return best
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


# Les offres d’avant n’ont pas les mêmes noms ni les mêmes plafonds. Par
# défaut on reprend ce que l’artiste avait : une reprise qui masquerait la
# moitié d’une salle serait une perte, pas une restitution. Le plafond de
# l’offre choisie s’applique ensuite aux envois suivants.
DEFAULT_PLANS = {"portfolio": "pro", "pro_monthly": "pro", "pro": "pro"}


def parse_plans(text: str) -> dict:
    """Lit « source=cible,source=cible » et rend la table de correspondance."""
    table = dict(DEFAULT_PLANS)
    for pair in (text or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        source, _, target = pair.partition("=")
        if not target:
            raise SystemExit(f"Correspondance d’offre mal formée : « {pair} » (attendu source=cible).")
        table[source.strip()] = target.strip()
    return table


def pick(row: dict, *names: str, default=""):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return default


STORAGE_MARKER = "/storage/v1/object/public/"


def rewrite_media(url: str, base: str) -> str:
    """Recolle un visuel sur l’hôte qui le sert aujourd’hui.

    Une base restaurée garde les URLs qu’elle avait : si le projet a changé de
    référence en route — ce qui arrive quand un projet en pause doit être
    recréé — elles pointent toutes dans le vide, et l’import perdrait chaque
    œuvre faute de visuel. ``--media-base`` donne la nouvelle adresse du
    bucket ; les chemins relatifs y sont raccrochés de la même façon."""
    if not base or not url:
        return url
    base = base.rstrip("/") + "/"
    if not url.startswith(("http://", "https://")):
        return base + url.lstrip("/")
    marker = url.find(STORAGE_MARKER)
    if marker == -1:
        return url
    # Après le marqueur vient le nom du bucket, que la base fournie contient
    # déjà : on ne garde que le chemin de l’objet.
    _, _, path = url[marker + len(STORAGE_MARKER):].partition("/")
    return base + path if path else url


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


def as_jpeg(payload: bytes, max_side: int = 1800, quality: int = 85) -> bytes | None:
    """Ramène un visuel au format que le site sert.

    Les bases d’avant stockent du WebP, parfois servi sous une étiquette qui
    n’est pas la sienne. Le magasin d’images, lui, annonce du JPEG : garder
    les octets tels quels reviendrait à mentir sur leur nature. On les
    redécode donc une fois, à la bonne taille, et on les réécrit."""
    try:
        image = Image.open(BytesIO(payload))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((max_side, max_side))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
    except Exception:
        return None
    return buffer.getvalue()


def import_all(
    source: str,
    *,
    with_images: bool,
    limit: int,
    dry_run: bool,
    plan: str,
    media_base: str = "",
    max_side: int = 1800,
    quality: int = 85,
    plans: dict | None = None,
) -> dict:
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
            plan_key=(plans or {}).get(str(pick(row, "subscription_plan")), plan),
            published=str(pick(row, "status", default="active")).lower() == "active",
        )
        # L’empreinte Werkzeug traverse : le mot de passe de l’artiste reste valable.
        password_hash = str(pick(row, "password_hash"))
        if password_hash:
            artist.password_hash = password_hash
        else:
            artist.set_password(os.urandom(16).hex())

        cover = rewrite_media(str(pick(row, "profile_photo_url", "profile_photo", "cover_path")), media_base)
        if with_images and cover:
            payload = fetch_image(cover)
            payload = as_jpeg(payload, max_side, quality) if payload else None
            if payload:
                # À blanc, on vérifie que le visuel répond sans rien écrire.
                if not dry_run:
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
            if not with_images:
                # Sans visuel, l’œuvre ne peut pas être accrochée : on la passe.
                continue
            image_url = rewrite_media(str(pick(work_row, "image_url", "image")), media_base)
            # L’essai à blanc rapatrie aussi les visuels : c’est le seul moyen
            # de savoir, avant d’écrire, si les URLs de la base répondent encore.
            payload = fetch_image(image_url)
            payload = as_jpeg(payload, max_side, quality) if payload else None
            if payload is None:
                report["images_lost"] += 1
                print(f"      · {title} — visuel introuvable, œuvre ignorée")
                continue
            report["images"] += 1
            report["works"] += 1
            if dry_run:
                continue
            image_name = save_bytes(payload)
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

        # Une salle à la fois. Reprendre une base entière est long : garder
        # tout ouvert jusqu’au bout ferait d’une coupure au trente-neuvième
        # minute une perte de trente-neuf minutes, et tiendrait une
        # transaction ouverte sur la base tout ce temps. Ici, chaque salle
        # posée est acquise — et comme un e-mail déjà présent est ignoré,
        # relancer l’import reprend là où il s’était arrêté.
        if not dry_run:
            try:
                db.session.commit()
            except Exception as erreur:
                db.session.rollback()
                report["skipped"] += 1
                report["artists"] -= 1
                print(f"  ! {email} — non repris ({type(erreur).__name__}), on continue")

    if dry_run:
        db.session.rollback()
        print("\n— essai à blanc : rien n’a été écrit —")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Importer une ancienne base Artworks.")
    parser.add_argument("--source", required=True, help="URL Postgres, fichier SQLite ou JSON")
    parser.add_argument("--limit", type=int, default=0, help="n’importer que les N premiers artistes")
    parser.add_argument("--dry-run", action="store_true", help="afficher sans rien écrire")
    parser.add_argument("--no-images", action="store_true", help="ne pas retélécharger les visuels")
    parser.add_argument(
        "--plan", default="decouverte", help="offre des comptes dont l’offre d’origine est inconnue"
    )
    parser.add_argument(
        "--plans",
        default="",
        help="correspondance des offres, « source=cible » séparées par des virgules. "
        f"Par défaut : {', '.join(f'{k}={v}' for k, v in DEFAULT_PLANS.items())}. "
        "Le plafond de l’offre décide du nombre d’œuvres visibles : en abaisser "
        "une masque le reste de la salle.",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=1800,
        help="côté le plus long des visuels, en pixels (défaut 1800). Les "
        "visuels vivent dans la base : c’est ce réglage qui décide de son poids.",
    )
    parser.add_argument("--quality", type=int, default=85, help="qualité JPEG (défaut 85)")
    parser.add_argument(
        "--media-base",
        default="",
        help="adresse du bucket qui sert les visuels aujourd’hui, quand la base "
        "porte encore les URLs d’un projet disparu — ex. "
        "https://<ref>.supabase.co/storage/v1/object/public/uploads/",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        report = import_all(
            args.source,
            with_images=not args.no_images,
            limit=args.limit,
            dry_run=args.dry_run,
            plan=args.plan,
            media_base=args.media_base,
            max_side=args.max_side,
            quality=args.quality,
            plans=parse_plans(args.plans),
        )
    print(
        "\nRésultat — "
        f"{report['artists']} artiste(s), {report['works']} œuvre(s), "
        f"{report['images']} visuel(s) récupéré(s), {report['images_lost']} perdu(s), "
        f"{report['skipped']} ignoré(s)."
    )


if __name__ == "__main__":
    main()
