"""Connexion, mots de passe repris, et liens de réinitialisation.

Deux mécanismes valaient d'être tenus par des tests, parce qu'ils se
cassent en silence : la lecture des mots de passe hérités d'une base
antérieure, et l'invalidation des liens de réinitialisation.
"""
from __future__ import annotations

import bcrypt
import pytest

from artworks.models import Artist
from artworks.tokens import make_reset_token, read_reset_token

from tests.conftest import ARTIST_EMAIL, ARTIST_PASSWORD


class TestPasswords:
    def test_a_current_password_is_read(self, artist):
        assert artist.check_password(ARTIST_PASSWORD)
        assert not artist.check_password("mauvais")

    def test_a_bcrypt_password_from_the_old_base_still_opens(self, db, artist):
        """Les artistes repris ne doivent pas refaire leur mot de passe."""
        legacy = bcrypt.hashpw(b"ancien-secret", bcrypt.gensalt(rounds=4)).decode()
        artist.password_hash = legacy
        db.session.commit()
        assert artist.check_password("ancien-secret")

    def test_reading_it_once_rewrites_it_in_the_current_format(self, db, artist):
        """L'empreinte ancienne disparaît d'elle-même à la première connexion."""
        legacy = bcrypt.hashpw(b"ancien-secret", bcrypt.gensalt(rounds=4)).decode()
        artist.password_hash = legacy
        db.session.commit()
        artist.check_password("ancien-secret")
        assert not artist.password_hash.startswith(("$2a$", "$2b$", "$2y$"))
        assert artist.check_password("ancien-secret")

    def test_a_wrong_bcrypt_password_is_refused_and_not_rewritten(self, db, artist):
        legacy = bcrypt.hashpw(b"ancien-secret", bcrypt.gensalt(rounds=4)).decode()
        artist.password_hash = legacy
        db.session.commit()
        assert not artist.check_password("pas-le-bon")
        assert artist.password_hash == legacy

    def test_a_corrupted_hash_is_refused_instead_of_raising(self, db, artist):
        artist.password_hash = "$2b$pas-du-tout-un-hash"
        db.session.commit()
        assert not artist.check_password("quoi que ce soit")


class TestResetTokens:
    def test_a_fresh_token_names_its_artist(self, artist):
        assert read_reset_token(make_reset_token(artist)) is artist

    def test_changing_the_password_burns_every_link_already_sent(self, db, artist):
        """C'est la promesse du module : un lien ancien ne rouvre pas un compte."""
        token = make_reset_token(artist)
        artist.set_password("un-tout-nouveau-mot-de-passe")
        db.session.commit()
        assert read_reset_token(token) is None

    def test_a_forged_token_is_refused(self, artist):
        assert read_reset_token("n-importe-quoi") is None
        assert read_reset_token("") is None

    def test_a_token_for_a_deleted_artist_is_refused(self, db, artist):
        token = make_reset_token(artist)
        db.session.delete(artist)
        db.session.commit()
        assert read_reset_token(token) is None


class TestSignIn:
    def test_the_right_password_opens_the_atelier(self, client, artist):
        response = client.post(
            "/connexion",
            data={"email": ARTIST_EMAIL, "password": ARTIST_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/atelier" in response.headers["Location"]

    def test_a_wrong_password_does_not_open_it(self, client, artist):
        client.post(
            "/connexion",
            data={"email": ARTIST_EMAIL, "password": "mauvais"},
            follow_redirects=True,
        )
        assert client.get("/atelier/").status_code == 302

    def test_an_unknown_email_does_not_open_it(self, client, artist):
        client.post(
            "/connexion",
            data={"email": "personne@example.com", "password": ARTIST_PASSWORD},
            follow_redirects=True,
        )
        assert client.get("/atelier/").status_code == 302
