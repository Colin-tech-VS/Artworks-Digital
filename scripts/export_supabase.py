"""Lit une base Supabase par son API HTTPS et en fait un export JSON.

    python scripts/export_supabase.py --url https://<ref>.supabase.co \
        --key <clé service_role> --out export.json

À quoi cela sert : ``import_legacy.py`` se branche normalement en direct sur
Postgres. Quand le port 5432 n'est pas joignable — réseau fermé, conteneur
qui ne sort qu'en HTTPS — cette porte-là reste ouverte : PostgREST parle sur
443 et rend les mêmes lignes.

Le fichier produit est exactement ce qu'attend l'import :

    {"artists": [...], "works": [...]}

    python scripts/import_legacy.py --source export.json

Les deux anciens schémas sont reconnus, comme à l'import : « portfolio »
(``portfolio_artists`` / ``portfolio_paintings``) et V1/V2 (``artists`` /
``artworks``). La clé n'est jamais écrite dans le fichier ni affichée.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# (table artistes, table œuvres) — le premier couple présent gagne.
SHAPES = (
    ("portfolio_artists", "portfolio_paintings"),
    ("artists", "artworks"),
)
PAGE = 1000


def _get(url: str, key: str, timeout: int = 60) -> list[dict]:
    request = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            # Une trace de pile n’apprend rien ici : le problème est la clé.
            sys.exit(
                "Clé refusée par le projet (HTTP "
                f"{error.code}). Prendre la clé « service_role » dans "
                "Dashboard → Settings → API keys ; la clé anon ne traverse "
                "pas les politiques RLS."
            )
        raise


def read_table(base: str, key: str, table: str) -> list[dict]:
    """Rapatrie une table entière, page après page."""
    rows: list[dict] = []
    while True:
        url = f"{base}/rest/v1/{urllib.parse.quote(table)}?select=*&limit={PAGE}&offset={len(rows)}"
        page = _get(url, key)
        rows.extend(page)
        print(f"  {table} : {len(rows)} lignes", end="\r", flush=True)
        if len(page) < PAGE:
            break
    print(f"  {table} : {len(rows)} lignes      ")
    return rows


def table_exists(base: str, key: str, table: str) -> bool:
    try:
        _get(f"{base}/rest/v1/{urllib.parse.quote(table)}?select=*&limit=1", key)
        return True
    except urllib.error.HTTPError as error:
        if error.code in (404, 400, 406):
            return False
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporter une base Supabase via son API HTTPS.")
    parser.add_argument("--url", required=True, help="https://<ref>.supabase.co")
    parser.add_argument("--key", required=True, help="clé service_role (jamais écrite dans la sortie)")
    parser.add_argument("--out", default="export.json", help="fichier JSON produit")
    parser.add_argument("--table-artists", default="", help="forcer la table des artistes")
    parser.add_argument("--table-works", default="", help="forcer la table des œuvres")
    args = parser.parse_args()

    base = args.url.rstrip("/")

    if args.table_artists:
        shape = (args.table_artists, args.table_works or "")
    else:
        shape = next(
            ((a, w) for a, w in SHAPES if table_exists(base, args.key, a)),
            None,
        )
        if shape is None:
            noms = " ou ".join(a for a, _ in SHAPES)
            sys.exit(f"Aucune table d’artistes reconnue ({noms}).")

    artists_table, works_table = shape
    print(f"Schéma « {artists_table} » retenu.")
    artists = read_table(base, args.key, artists_table)
    works = read_table(base, args.key, works_table) if works_table else []

    destination = Path(args.out)
    destination.write_text(
        json.dumps({"artists": artists, "works": works}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    poids = destination.stat().st_size / 1024
    print(f"\n{len(artists)} artiste(s), {len(works)} œuvre(s) → {destination} ({poids:.0f} Ko)")
    print("Suite : python scripts/import_legacy.py --source", destination, "--dry-run")


if __name__ == "__main__":
    main()
