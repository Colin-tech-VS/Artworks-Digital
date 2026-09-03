# Artworks Digital

Chaque artiste ouvre **sa** galerie. Pas de marketplace, pas de catalogue partagé, pas de boutique.

L’atelier prépare la salle. L’accrochage place les œuvres. La publication donne une adresse : `/galerie/votre-nom`.

## Local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Ouvrir [http://127.0.0.1:8080](http://127.0.0.1:8080).

## Concept

| Il y a | Il n’y a pas |
|---|---|
| Compte artiste | Comptes galerie / collectionneur |
| Salle + note d’intention | Matching, sourcing, commissions |
| Accrochage d’œuvres (cartel) | Panier, Stripe, ventes |
| Galerie publique à une adresse | Vitrine marketplace |

## E-mails transactionnels

Un seul gabarit met en page tous les envois automatiques
(`artworks/templates/emails/message.html`) : bienvenue, mot de passe oublié
et modifié, e-mail de connexion changé, galerie publiée, message reçu,
changement d’offre, paiement refusé, accusé de réception d’un visiteur.

`/admin/emails/modeles` affiche chaque modèle dans son rendu réel, sans
l’envoyer, et permet d’envoyer un test à une adresse.

Sans SMTP configuré, rien n’est perdu : l’envoi est archivé dans
`MailMessage` et visible dans la boîte de l’admin.

## Réseaux sociaux — du prompt à la publication

`/admin/social` prend une consigne en français. Mistral écrit la légende,
les hashtags et le brief du visuel (mise en page, palette, titre) ; le
visuel est composé en Pillow au format du réseau — carré 1080×1080,
portrait 1080×1350, paysage 1200×630, story 1080×1920 — avec le lettrage
du site. On relit, on corrige, on publie sur Facebook, Instagram,
Pinterest ou DeviantArt.

L’image générée est servie en HTTPS depuis `/media`, ce qu’Instagram exige.
Sans clé Mistral — ou si l’API tombe — un brouillon est composé quand même.

Les artistes des offres Pro et Studio disposent du même générateur dans
`/atelier/ia`, pour leurs propres œuvres, en téléchargement.

## K.A.E.L. — l’intelligence d’Artworks Digital

K.A.E.L. vit dans le centre de commande, pas ici. Artworks Digital ne
rejoue pas son cerveau : il lui ouvre une porte, et cette porte a des
serrures.

### La porte

```
GET  /api/kael/health                  état, sans jeton
GET  /api/kael/manifest                les outils, filtrés sur ce que le jeton peut faire
GET  /api/kael/context                 qui parle, d’où, sur quelle œuvre
POST /api/kael/tools/<nom>             exécute un outil
```

Authentification : `Authorization: Bearer <KAEL_API_KEY>`. La clé est
créée par K.A.E.L. et lue dans l’environnement Scalingo — Artworks ne
l’émet pas.

### Les serrures

| Portée | Ce qu’elle ouvre |
|---|---|
| `KAEL_READ` | lire artistes, œuvres, catalogue, audience, messages, offres |
| `KAEL_ANALYZE` | diagnostics d’œuvre, de portfolio, anomalies de plateforme |
| `KAEL_WRITE` | corriger un cartel, une note, l’ordre d’accrochage, la visibilité |
| `KAEL_PUBLISH` | composer et publier sur les réseaux, ouvrir une salle, envoyer un e-mail |
| `KAEL_ADMIN` | offres, suppressions, journal |

Un jeton peut être **limité à un seul atelier** : K.A.E.L. ne voit alors
que celui-là, quelles que soient ses portées.

### La main humaine

Cinq outils ne s’exécutent jamais seuls : `publish_social_post`,
`set_gallery_published`, `send_platform_email`, `assign_plan`,
`delete_artwork`. Ils répondent `409` avec une carte qui dit ce qui va se
passer, ce qui est irréversible, et un `confirm_token` valable dix minutes,
lié à ces paramètres-là. Changer un paramètre invalide la confirmation.

### La trace

Chaque appel laisse une ligne : outil, portée, paramètres (secrets masqués),
résultat, durée, confirmation éventuelle.

### Dans le site

Un panneau K.A.E.L. reste dans l’atelier : il déclenche les outils, forcés
sur l’atelier de l’artiste connecté. L’admin n’héberge plus K.A.E.L.

Variables : `KAEL_API_URL`, `KAEL_API_KEY`, `KAEL_AGENT`, `KAEL_ENABLED`.

## Reprendre une ancienne base

```bash
python scripts/import_legacy.py --source postgresql://…   # restauration Supabase, dump rechargé, addon Scalingo
python scripts/import_legacy.py --source ancienne.db --dry-run
python scripts/import_legacy.py --source export.json --no-images
```

Si la base a survécu mais que son projet a changé d’adresse, les URLs des
visuels pointent dans le vide et chaque œuvre serait passée faute d’image.
`--media-base` les recolle sur l’hôte qui les sert aujourd’hui :

```bash
python scripts/import_legacy.py --source postgresql://… \
    --media-base https://<ref>.supabase.co/storage/v1/object/public/uploads/
```

L’essai à blanc rapatrie les visuels sans rien écrire : c’est le seul moyen
de savoir, avant l’import, si les adresses répondent encore.

Les deux anciens schémas sont reconnus (`portfolio_artists`/`portfolio_paintings`
et `artists`/`artworks`). Les empreintes de mot de passe viennent de Werkzeug
des deux côtés : les artistes se reconnectent avec leur mot de passe. Les
visuels sont retéléchargés depuis leur URL et stockés en base. L’import est
idempotent — un e-mail déjà présent est ignoré.

## Déploiement Scalingo

App `new-artworks-digital` — [https://new-artworks-digital.osc-fr1.scalingo.io](https://new-artworks-digital.osc-fr1.scalingo.io)

Variables : `SECRET_KEY`, `DATABASE_URL` (addon **PostgreSQL** Starter 512). Les visuels sont aussi stockés en base : le disque Scalingo est éphémère.
