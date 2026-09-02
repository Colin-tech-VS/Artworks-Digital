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

## Déploiement Scalingo

App Python, `Procfile` à la racine. Variables : `SECRET_KEY`, `DATABASE_URL` (Postgres en prod).
