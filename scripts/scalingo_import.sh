#!/usr/bin/env bash
# Lance l'import du catalogue sur l'application de production, sans passer par
# le client Scalingo : un conteneur ponctuel, détaché, via l'API HTTPS.
#
#   SUPABASE_DSN="postgresql://…" bash scripts/scalingo_import.sh
#
# Rien n'est écrit en clair ici : la chaîne de connexion vient de
# l'environnement, le jeton d'API aussi. Le script ne les affiche jamais.
#
# Variables lues :
#   SUPABASE_DSN         obligatoire — la base d'où l'on reprend
#   SCALINGO_API_TOKEN   obligatoire — jeton Scalingo (tk-…)
#   APP                  défaut new-artworks-digital
#   REGION               défaut osc-fr1
#   DRY_RUN=1            essai à blanc : compte sans rien écrire
set -euo pipefail

APP="${APP:-new-artworks-digital}"
REGION="${REGION:-osc-fr1}"
MEDIA_BASE="${MEDIA_BASE:-https://onifrjiwbsjnhejtmrpq.supabase.co/storage/v1/object/public/uploads/}"

[ -n "${SUPABASE_DSN:-}" ]       || { echo "SUPABASE_DSN manquant." >&2; exit 1; }
[ -n "${SCALINGO_API_TOKEN:-}" ] || { echo "SCALINGO_API_TOKEN manquant." >&2; exit 1; }

bearer=$(curl -sS --max-time 40 -u ":$SCALINGO_API_TOKEN" \
  -X POST https://auth.scalingo.com/v1/tokens/exchange \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))')
[ -n "$bearer" ] || { echo "Authentification Scalingo refusée." >&2; exit 1; }

commande="python scripts/import_legacy.py --source \"$SUPABASE_DSN\" --media-base \"$MEDIA_BASE\""
[ "${DRY_RUN:-0}" = "1" ] && commande="$commande --dry-run"

charge=$(SC_CMD="$commande" python3 -c '
import json, os
print(json.dumps({"command": os.environ["SC_CMD"], "detached": True, "size": "L"}))')

echo "Application : $APP ($REGION)${DRY_RUN:+ — essai à blanc}"
curl -sS --max-time 90 \
  -H "Authorization: Bearer $bearer" -H "Content-Type: application/json" \
  -X POST "https://api.$REGION.scalingo.com/v1/apps/$APP/run" -d "$charge" \
| python3 -c '
import json, sys
d = json.load(sys.stdin)
if d.get("error"):
    print("Refusé :", d["error"]); raise SystemExit(1)
c = d.get("container") or {}
print("Conteneur lancé :", c.get("label") or c.get("id"), "— état", c.get("state"))
print("Suivre : scalingo --app '"$APP"' logs --lines 50")'
