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

## Reprendre une ancienne base

```bash
python scripts/import_legacy.py --source postgresql://…   # restauration Supabase, dump rechargé, addon Scalingo
python scripts/import_legacy.py --source ancienne.db --dry-run
python scripts/import_legacy.py --source export.json --no-images
```

Les deux anciens schémas sont reconnus (`portfolio_artists`/`portfolio_paintings`
et `artists`/`artworks`). Les empreintes de mot de passe viennent de Werkzeug
des deux côtés : les artistes se reconnectent avec leur mot de passe. Les
visuels sont retéléchargés depuis leur URL et stockés en base. L’import est
idempotent — un e-mail déjà présent est ignoré.

## Déploiement Scalingo

App `new-artworks-digital` — [https://new-artworks-digital.osc-fr1.scalingo.io](https://new-artworks-digital.osc-fr1.scalingo.io)

Variables : `SECRET_KEY`, `DATABASE_URL` (addon **PostgreSQL** Starter 512). Les visuels sont aussi stockés en base : le disque Scalingo est éphémère.
