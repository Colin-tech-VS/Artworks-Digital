"""Le socle des tests : une application réelle, une base jetable.

Rien n'est simulé ici. L'application est celle que Scalingo démarre, avec
ses blueprints, ses templates et ses modèles ; seule la base change — un
SQLite en mémoire, recréé pour chaque test, pour qu'aucun test n'hérite de
l'état d'un autre.

Deux réglages seulement s'écartent de la production, et pour une raison
précise :

* ``CANONICAL_REDIRECT`` est coupé. En production, tout ce qui n'arrive pas
  sur ``www.artworksdigital.fr`` part en 301 ; le client de test appelle
  ``localhost``, donc chaque requête serait une redirection avant même
  d'atteindre la vue.
* ``WTF_CSRF_ENABLED`` est coupé, parce qu'un jeton CSRF vérifie le
  formulaire, pas la vue qu'on veut mesurer.
"""
from __future__ import annotations

import pytest

from artworks import create_app
from artworks.extensions import db as _db
from artworks.models import Artist, Work

ADMIN_USERNAME = "admin-test"
ADMIN_PASSWORD = "mot-de-passe-admin"
ARTIST_EMAIL = "camille@example.com"
ARTIST_PASSWORD = "mot-de-passe-artiste"


@pytest.fixture
def app():
    # `artworks.config` lit os.environ au moment de l'import du module, pas
    # à la création de l'application : poser des variables d'environnement
    # ici arriverait trop tard. On écrit donc directement dans la config,
    # ce qui est de toute façon plus lisible.
    application = create_app()
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SECRET_KEY="clé-de-test",
        CANONICAL_REDIRECT=False,
        ADMIN_USERNAME=ADMIN_USERNAME,
        ADMIN_PASSWORD=ADMIN_PASSWORD,
        SITE_UNLOCK_PASSWORD="",
    )
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def artist(db):
    """Une salle publiée, avec une œuvre accrochée."""
    record = Artist(
        email=ARTIST_EMAIL,
        display_name="Camille Roux",
        slug="camille-roux",
        published=True,
    )
    record.set_password(ARTIST_PASSWORD)
    db.session.add(record)
    db.session.flush()
    db.session.add(
        Work(
            artist_id=record.id,
            title="Aube",
            image_path="oeuvre.png",
            image_w=1200,
            image_h=800,
            visible=True,
            position=1,
        )
    )
    db.session.commit()
    return record


@pytest.fixture
def studio_artist(db, artist):
    """La même salle, sur l'offre haute.

    Statistiques, IA et collections sont réservées aux offres payantes :
    sur l'offre gratuite, ces pages redirigent vers la facturation et leur
    gabarit n'est jamais rendu. Sans cet artiste-là, trois écrans de
    l'atelier resteraient hors de portée des tests.
    """
    artist.plan_key = "studio"
    db.session.commit()
    return artist


@pytest.fixture
def artist_client(client, artist):
    """Un client déjà connecté dans l'atelier."""
    response = client.post(
        "/connexion",
        data={"email": ARTIST_EMAIL, "password": ARTIST_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def studio_client(client, studio_artist):
    """Un client connecté sur l'offre Studio, tout ouvert."""
    response = client.post(
        "/connexion",
        data={"email": ARTIST_EMAIL, "password": ARTIST_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def admin_client(client):
    """Un client déjà connecté à l'administration."""
    response = client.post(
        "/admin/login",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return client
