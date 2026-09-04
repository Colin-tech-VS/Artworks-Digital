"""Les écritures — ce que la suite ne regardait pas.

Tout ce qui existait vérifiait des lectures : une page rend, une salle
cachée reste cachée, un sitemap est du XML valide. Or la production ne
tombe presque jamais sur une lecture. Elle tombe quand quelqu'un
s'inscrit, accroche une œuvre, change son mot de passe ou publie sa
salle — c'est-à-dire sur les chemins qu'aucun test ne parcourait.

Un blueprint qui répond 200 ne prouve rien non plus : `/atelier/compte`
répond 200 même quand le formulaire est refusé en silence. Chaque test
d'ici va donc relire la base après le POST, parce que c'est le seul
endroit où l'on voit si l'écriture a vraiment eu lieu.
"""
from __future__ import annotations

import io

from PIL import Image

from artworks.models import Artist, MailMessage, Work
from tests.conftest import ARTIST_EMAIL, ARTIST_PASSWORD


def _visual(width=1400, height=900, fmt="JPEG"):
    """Un vrai fichier image : Pillow lit ses dimensions à l'accrochage."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 110)).save(buffer, fmt)
    buffer.seek(0)
    return buffer


class TestRegistration:
    """L'inscription — la première écriture du site, et la seule que le
    visiteur fait sans filet."""

    def test_signing_up_creates_an_artist_who_can_sign_in(self, client, db):
        response = client.post(
            "/inscription",
            data={
                "display_name": "Noa Perrin",
                "email": "noa@exemple.fr",
                "password": "motdepasse-solide",
                "confirm": "motdepasse-solide",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        artist = Artist.query.filter_by(email="noa@exemple.fr").first()
        assert artist is not None
        assert artist.check_password("motdepasse-solide")

    def test_signing_up_gives_the_room_an_address(self, client, db):
        client.post(
            "/inscription",
            data={
                "display_name": "Noa Perrin",
                "email": "noa@exemple.fr",
                "password": "motdepasse-solide",
                "confirm": "motdepasse-solide",
            },
            follow_redirects=True,
        )
        artist = Artist.query.filter_by(email="noa@exemple.fr").first()
        assert artist.slug

    def test_the_welcome_letter_is_kept_even_without_smtp(self, client, db):
        """Sans SMTP configuré, l'envoi échoue — mais la lettre doit rester
        lisible dans l'admin, sinon elle est perdue sans que personne ne le
        sache."""
        client.post(
            "/inscription",
            data={
                "display_name": "Noa Perrin",
                "email": "noa@exemple.fr",
                "password": "motdepasse-solide",
                "confirm": "motdepasse-solide",
            },
            follow_redirects=True,
        )
        assert MailMessage.query.filter_by(to_email="noa@exemple.fr").count() >= 1

    def test_an_email_already_taken_does_not_create_a_second_artist(self, client, artist):
        client.post(
            "/inscription",
            data={
                "display_name": "Quelqu'un d'autre",
                "email": ARTIST_EMAIL,
                "password": "un-autre-mot-de-passe",
                "confirm": "un-autre-mot-de-passe",
            },
            follow_redirects=True,
        )
        assert Artist.query.filter_by(email=ARTIST_EMAIL).count() == 1


class TestHangingAWork:
    """L'accrochage — le geste que l'artiste répète le plus."""

    def test_a_work_is_stored_with_its_visual(self, artist_client, artist, db):
        response = artist_client.post(
            "/atelier/oeuvres/nouvelle",
            data={
                "title": "Marée basse",
                "year": "2025",
                "medium": "Huile",
                "visible": "y",
                "image": (_visual(), "oeuvre.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200

        work = Work.query.filter_by(title="Marée basse").first()
        assert work is not None
        assert work.image_path

    def test_the_visual_dimensions_are_read_at_upload(self, artist_client, artist, db):
        """Sans elles, le gabarit ne réserve pas la place de l'image et la
        page saute au chargement."""
        artist_client.post(
            "/atelier/oeuvres/nouvelle",
            data={"title": "Marée basse", "visible": "y", "image": (_visual(1400, 900), "oeuvre.jpg")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        work = Work.query.filter_by(title="Marée basse").first()
        assert (work.image_w, work.image_h) == (1400, 900)

    def test_the_stored_visual_is_served_back(self, artist_client, artist, db):
        artist_client.post(
            "/atelier/oeuvres/nouvelle",
            data={"title": "Marée basse", "visible": "y", "image": (_visual(), "oeuvre.jpg")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        work = Work.query.filter_by(title="Marée basse").first()
        assert artist_client.get(f"/media/{work.image_path}").status_code == 200

    def test_editing_a_cartel_rewrites_it(self, artist_client, artist, db):
        work = artist.works.first()
        artist_client.post(
            f"/atelier/oeuvres/{work.id}",
            data={"title": "Aube corrigée", "visible": "y"},
            follow_redirects=True,
        )
        assert db.session.get(Work, work.id).title == "Aube corrigée"

    def test_removing_a_work_removes_it(self, artist_client, artist, db):
        work = artist.works.first()
        artist_client.post(f"/atelier/oeuvres/{work.id}/retirer", follow_redirects=True)
        assert db.session.get(Work, work.id) is None

    def test_an_artist_cannot_touch_a_work_that_is_not_theirs(self, artist_client, db, artist):
        """La porte la plus facile à laisser ouverte : l'identifiant d'une
        œuvre est un entier, il se devine en comptant."""
        other = Artist(
            email="autre@exemple.fr",
            display_name="Autre",
            slug="autre",
            published=True,
        )
        other.set_password("mot-de-passe")
        db.session.add(other)
        db.session.flush()
        stranger = Work(
            artist_id=other.id,
            title="Œuvre d'un autre",
            image_path="autre.png",
            image_w=800,
            image_h=600,
            visible=True,
        )
        db.session.add(stranger)
        db.session.commit()

        artist_client.post(f"/atelier/oeuvres/{stranger.id}/retirer", follow_redirects=True)
        assert db.session.get(Work, stranger.id) is not None


class TestPublishingTheRoom:
    def test_saving_the_room_publishes_it_at_its_address(self, artist_client, artist, db):
        response = artist_client.post(
            "/atelier/galerie",
            data={
                "display_name": "Camille Roux",
                "slug": "camille-roux",
                "discipline": "Peinture",
                "statement": "Ma note d'intention.",
                "hang_style": "grille",
                "published": "y",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert db.session.get(Artist, artist.id).published is True
        assert artist_client.get("/galerie/camille-roux").status_code == 200


class TestAccount:
    """Le compte — deux formulaires sur une même adresse, distingués par un
    champ caché. Poster sans ce champ ne doit rien changer."""

    def test_changing_the_password_applies_it(self, artist_client, artist, db):
        artist_client.post(
            "/atelier/compte",
            data={
                "form_name": "password",
                "current": ARTIST_PASSWORD,
                "password": "nouveau-mot-de-passe",
                "confirm": "nouveau-mot-de-passe",
            },
            follow_redirects=True,
        )
        refreshed = db.session.get(Artist, artist.id)
        assert refreshed.check_password("nouveau-mot-de-passe")
        assert not refreshed.check_password(ARTIST_PASSWORD)

    def test_a_wrong_current_password_changes_nothing(self, artist_client, artist, db):
        artist_client.post(
            "/atelier/compte",
            data={
                "form_name": "password",
                "current": "ce-n-est-pas-le-bon",
                "password": "nouveau-mot-de-passe",
                "confirm": "nouveau-mot-de-passe",
            },
            follow_redirects=True,
        )
        assert db.session.get(Artist, artist.id).check_password(ARTIST_PASSWORD)

    def test_changing_the_email_applies_it(self, artist_client, artist, db):
        artist_client.post(
            "/atelier/compte",
            data={"form_name": "email", "email": "camille.roux@exemple.fr"},
            follow_redirects=True,
        )
        assert db.session.get(Artist, artist.id).email == "camille.roux@exemple.fr"


class TestPasswordReset:
    def test_a_link_reopens_the_account_then_burns(self, client, artist, db, app):
        from artworks.tokens import make_reset_token

        assert client.post(
            "/mot-de-passe-oublie", data={"email": ARTIST_EMAIL}, follow_redirects=True
        ).status_code == 200

        with app.test_request_context():
            token = make_reset_token(artist)

        assert client.get(f"/mot-de-passe/{token}").status_code == 200
        client.post(
            f"/mot-de-passe/{token}",
            data={"password": "encore-un-autre-mdp", "confirm": "encore-un-autre-mdp"},
            follow_redirects=True,
        )
        assert db.session.get(Artist, artist.id).check_password("encore-un-autre-mdp")

        # Le hash entre dans la signature : le lien déjà servi ne vaut plus.
        assert client.get(f"/mot-de-passe/{token}").status_code != 200


class TestContact:
    def test_a_visitor_message_leaves_a_trace(self, client, db):
        """Sans SMTP, l'accusé de réception ne part pas — mais le message
        du visiteur doit rester lisible, sinon il est perdu."""
        before = MailMessage.query.count()
        response = client.post(
            "/contact",
            data={
                "name": "Jean Vasseur",
                "email": "jean@exemple.fr",
                "message": "Bonjour, je découvre votre travail.",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert MailMessage.query.count() > before


class TestAdminWrites:
    def test_a_wrong_password_does_not_open_the_admin(self, client):
        client.post(
            "/admin/login",
            data={"username": "admin-test", "password": "ce-n-est-pas-le-bon"},
            follow_redirects=True,
        )
        assert client.get("/admin/").status_code == 302

    def test_composing_an_email_records_it(self, admin_client, db):
        response = admin_client.post(
            "/admin/emails/nouveau",
            data={
                "to_email": "noa@exemple.fr",
                "subject": "Un mot",
                "body": "Le corps du message.",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert MailMessage.query.filter_by(subject="Un mot").first() is not None

    def test_assigning_a_plan_applies_it(self, admin_client, artist, db):
        response = admin_client.post(
            f"/admin/abonnements/{artist.id}",
            data={"plan_key": "studio"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert db.session.get(Artist, artist.id).plan_key == "studio"


class TestEmailTemplates:
    """Les neuf lettres automatiques. Une seule qui casse, et c'est un
    500 au moment précis où l'artiste attend son mot de passe."""

    KINDS = (
        "welcome",
        "password_reset",
        "password_changed",
        "email_changed",
        "gallery_published",
        "new_message",
        "contact_receipt",
        "plan_changed",
        "payment_failed",
    )

    def test_every_letter_renders(self, app):
        from artworks.emails import preview_html

        with app.test_request_context():
            for kind in self.KINDS:
                html = preview_html(kind)
                assert html and len(html) > 100, kind

    def test_the_admin_can_read_each_letter_without_sending_it(self, admin_client):
        for kind in self.KINDS:
            response = admin_client.get(f"/admin/emails/modeles/{kind}")
            assert response.status_code == 200, kind
