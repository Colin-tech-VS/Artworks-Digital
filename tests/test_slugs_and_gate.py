"""Deux mécanismes discrets : l'adresse d'une salle, et le rideau du site.

Un slug qui se répète écraserait l'adresse publique d'un artiste. Un rideau
mal posé enfermerait dehors l'artiste qui vient se connecter. Ni l'un ni
l'autre ne se voit tant qu'on ne l'essaie pas.
"""
from __future__ import annotations

from artworks.gate import site_is_open, try_unlock
from artworks.models import Artist
from artworks.slugs import slugify, unique_slug


class TestSlugify:
    def test_accents_and_spaces_become_an_address(self):
        assert slugify("Camille Roux") == "camille-roux"
        assert slugify("Élodie Ménard") == "elodie-menard"
        assert slugify("  Jean--Luc  ") == "jean-luc"

    def test_an_empty_name_still_yields_an_address(self):
        assert slugify("") == "galerie"
        assert slugify("!!!") == "galerie"
        assert slugify(None) == "galerie"

    def test_an_address_never_exceeds_the_column(self):
        assert len(slugify("a" * 200)) == 80


class TestUniqueSlug:
    def test_a_free_name_is_taken_as_is(self, db):
        assert unique_slug("Camille Roux") == "camille-roux"

    def test_a_taken_name_is_numbered(self, db, artist):
        assert unique_slug("Camille Roux") == "camille-roux-2"

    def test_an_artist_keeps_their_own_address(self, db, artist):
        """Renommer sans changer de nom ne doit pas ajouter un « -2 »."""
        assert unique_slug("Camille Roux", artist_id=artist.id) == "camille-roux"

    def test_numbering_climbs_until_it_is_free(self, db, artist):
        second = Artist(
            email="deux@example.com",
            display_name="Camille Roux",
            slug="camille-roux-2",
            published=True,
        )
        second.set_password("mot-de-passe")
        db.session.add(second)
        db.session.commit()
        assert unique_slug("Camille Roux") == "camille-roux-3"


class TestGate:
    """Le rideau, mesuré par le client réel plutôt que par ses rouages.

    Constat de ces tests : `SITE_UNLOCK_PASSWORD` ne ferme PAS le site. La
    liste `OPEN_ENDPOINTS`, plus les préfixes `kael.`/`atelier.`/`admin.` et
    les quatre routes d'authentification, laissent passer 70 des 71 routes.
    La seule que le rideau ferme réellement est `/inscription`. C'est donc
    un rideau sur les inscriptions, pas sur le site. Ces tests écrivent ce
    comportement noir sur blanc : si quelqu'un veut vraiment fermer le site,
    il verra ici ce qu'il doit changer, et si le comportement bouge par
    accident, il le saura.
    """

    def test_without_a_password_everything_is_open(self, app, client, artist):
        app.config["SITE_UNLOCK_PASSWORD"] = ""
        with app.test_request_context("/"):
            assert site_is_open()
        assert client.get("/inscription").status_code == 200

    def test_with_a_password_the_public_pages_stay_open(self, app, client, artist):
        app.config["SITE_UNLOCK_PASSWORD"] = "secret"
        for url in ("/", "/galeries", "/offres", "/contact", f"/galerie/{artist.slug}"):
            assert client.get(url).status_code == 200, url

    def test_with_a_password_the_sign_in_pages_stay_open(self, app, client, artist):
        """Un rideau qui enferme l'artiste dehors serait pire que pas de rideau."""
        app.config["SITE_UNLOCK_PASSWORD"] = "secret"
        for url in ("/connexion", "/mot-de-passe-oublie", "/admin/login"):
            assert client.get(url).status_code == 200, url

    def test_the_only_page_the_curtain_closes_is_registration(self, app, client):
        app.config["SITE_UNLOCK_PASSWORD"] = "secret"
        response = client.get("/inscription")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/")

    def test_the_right_password_reopens_registration(self, app, client):
        app.config["SITE_UNLOCK_PASSWORD"] = "secret"
        with client.session_transaction() as session:
            session["site_unlocked"] = True
        assert client.get("/inscription").status_code == 200

    def test_a_wrong_password_does_not_lift_the_curtain(self, app):
        app.config["SITE_UNLOCK_PASSWORD"] = "secret"
        with app.test_request_context("/"):
            assert not try_unlock("pas-secret")
            assert not site_is_open()

    def test_the_right_password_lifts_it(self, app):
        app.config["SITE_UNLOCK_PASSWORD"] = "secret"
        with app.test_request_context("/"):
            assert try_unlock("secret")
            assert site_is_open()
