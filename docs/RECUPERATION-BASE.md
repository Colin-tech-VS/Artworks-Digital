# Récupération des anciennes bases — état au 3 septembre 2026

Ce dossier fixe ce qu'il reste des bases Supabase d'avant, ce qui est
définitivement perdu, et par où passer si un export refait surface.

## 1. Les deux projets Supabase

| Rôle | Référence projet | Région | État vérifié |
|---|---|---|---|
| V1 production | `nxfkjsrgujboofnicxng` | eu-west-1 | **supprimé** |
| V2 staging/cible | `onifrjiwbsjnhejtmrpq` | — | **supprimé** |

Vérification faite le 3 septembre 2026 : les deux sous-domaines
`<ref>.supabase.co` répondent NXDOMAIN (statut 3) auprès d'un résolveur
public. Un projet en pause garde son enregistrement DNS ; l'absence
totale de résolution signe la suppression.

La documentation Supabase est sans ambiguïté : la suppression d'un projet
efface aussi les sauvegardes stockées en S3, l'opération est irréversible
et le support ne restaure pas un projet supprimé. Aucun ticket à ouvrir.

**La seule vérification qui reste, et qui demande le compte** : de
l'extérieur, un projet supprimé et un projet mis en pause se ressemblent —
NXDOMAIN ne tranche pas. Supabase libère l'adresse d'un projet resté en
pause, mais **garde ses données** : le tableau de bord le montre alors, et
ses sauvegardes restent téléchargeables. En pause moins de 90 jours, un
bouton « Restore » le relance entier, stockage compris ; au-delà, le bouton
disparaît mais la sauvegarde `.sql` se télécharge encore et se recharge dans
un projet neuf.

```bash
supabase login && supabase projects list
```

Ou directement le tableau de bord : si un projet Artworks y apparaît,
même grisé, tout est récupérable — et `scripts/import_legacy.py` reprend la
base telle quelle (voir §5). S'il n'apparaît nulle part, c'est réglé.

**Attention au piège des visuels** : une base restaurée garde les URLs
qu'elle avait. Si le projet a changé de référence en route, elles pointent
toutes dans le vide et l'import passerait chaque œuvre faute d'image.
`--media-base` les recolle sur le bucket vivant. L'essai à blanc rapatrie
les visuels sans rien écrire : il dit donc la vérité avant l'import.

## 1 bis. Les galeries de démonstration

Le site n'affiche plus de vitrine fabriquée. `artworks/seed.py` ne sème
plus rien : il ne garde que l'image de partage, la promotion des
administrateurs, et `purge_examples()`, appelé au démarrage, qui retire les
salles d'exemple déjà présentes en base — leurs œuvres, visuels, vues,
messages, abonnements et jetons compris. Le garde-fou est double : `is_example`
**et** une adresse en `@galerie.artworksdigital.fr`, pour qu'aucune salle
réelle ne parte avec. Le journal de K.A.E.L. est conservé : ses lignes
perdent leur jeton, pas leur trace. La fonction est idempotente et ne coûte
rien quand il n'y a rien à retirer.

Tant qu'aucun artiste réel ne s'est inscrit, `/galeries` affiche « Aucune
salle n'est encore ouverte. »

## 2. Ce que contenait la V1

Inventaire relevé en lecture seule le 23 mai 2026, avant la migration.
Postgres 17.6, 72 tables dans `public`.

| Table | Lignes |
|---|---:|
| `portfolio_artists` | 109 |
| `portfolio_paintings` | 587 |
| `blog_articles` | 47 |
| `seo_pages` | 117 |
| `site_settings` | 224 |
| `saas_sites` | 57 |
| `sites` | 32 |
| `portfolio_translations` | 63 |
| `portfolio_match_requests` | 53 |
| `paintings` (legacy) | 59 |
| `mailing_contacts` | 660 |
| `analytics_session_events` | 675 186 |

Stockage : un bucket public `artworks`, **995 fichiers pour 2,2 Go**, dont
952 fichiers sous `portfolio/{uuid}/`. Les URLs étaient publiques et
absolues, mais elles pointaient sur le domaine du projet supprimé : plus
rien ne répond.

## 3. Ce qui a été cherché, et n'a rien donné

- **Historique git complet** des quatre dépôts Artworks (`Artworks-Digital`,
  `staging-artworks-digital`, `ArtworksV3`, `Artworks_Digital`) : aucun
  dump, aucun export CSV ou JSON de la production n'a jamais été commité.
  Aucun objet git orphelin, aucun remisage.
- **Wayback Machine** : `artworksdigital.fr` n'a jamais été archivé, et les
  objets du bucket non plus. Aucune capture à exploiter.
- `Artworks_All` est un dépôt vide.
- Le seul enregistrement réel retrouvé est une fiche de test de décembre
  2025 (`artists_data/coco_cayre_at_gmail_com.json`, supprimée du suivi de
  version par la suite), dont les visuels pointaient sur `127.0.0.1:5000`.

**Conclusion : les 109 artistes, les 587 œuvres et les 2,2 Go de visuels
sont perdus.** La seule copie vivait dans les projets supprimés.

## 4. Ce qui survit, et qui vaut de l'or si on rebâtit

Rien de tout cela n'est dans ce dépôt-ci ; c'est dans `staging-artworks-digital`
(privé), qu'il ne faut pas supprimer :

- `db_supabase_schema.sql` — le schéma complet, 55 tables, rejouable tel quel.
- `MIGRATION_INVENTORY.md` — l'inventaire ci-dessus, table par table.
- `MIGRATION_MAPPING.md` — la correspondance colonne par colonne V1 → V2.
- `migration/` — l'ETL complet, idempotent et reprenable, avec sa table de
  correspondance d'identifiants et son `delta_sync.py`.

Dans `ArtworksV3` : `docs/supabase_v3_bootstrap.sql` et un jeu de données de
démonstration (sept artistes fictifs) dans `artworks_site/seed.py`.

## 5. Si un export refait surface

`scripts/import_legacy.py` reprend une base d'avant sans rien réécrire. Il
accepte trois formes de source et reconnaît les deux anciens schémas
(`portfolio_artists`/`portfolio_paintings` et `artists`/`artworks`) :

```bash
python scripts/import_legacy.py --source postgresql://…      # dump rechargé, addon vivant
python scripts/import_legacy.py --source ancienne.db --dry-run
python scripts/import_legacy.py --source export.json --no-images
```

Les empreintes de mot de passe viennent de Werkzeug des deux côtés : les
artistes se reconnectent avec leur mot de passe. Les visuels sont
retéléchargés depuis leur URL puis stockés en base. L'import est
idempotent — un e-mail déjà présent est ignoré.

## 6. Pour que cela n'arrive plus

La base actuelle est un addon PostgreSQL Scalingo, pas un projet Supabase.
Une sauvegarde régulière hors plateforme reste la seule protection réelle :

```bash
scalingo --app new-artworks-digital pgsql-backups:download --output sauvegarde.pgsql
```

Les visuels sont désormais stockés en base et non sur le disque éphémère :
un dump de la base emporte donc aussi les images.
