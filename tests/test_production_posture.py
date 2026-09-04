"""Les réglages qui ne se voient qu'en production.

Ces trois-là ne cassent rien quand ils sont faux. Le site répond, les
pages rendent, les tests passent — et le cookie de connexion voyage en
clair, ou les liens de réinitialisation sont signés avec une clé écrite
dans le dépôt. Un défaut qui ne se manifeste jamais localement est
exactement celui qu'il faut tenir par un test.

`artworks.config` lit `os.environ` à l'import du module : pour observer
une autre posture que celle des tests, il faut le recharger avec un autre
environnement, ce que fait `_config_under`.
"""
from __future__ import annotations

import importlib
import os


def _config_under(**environment):
    """Recharge `artworks.config` sous l'environnement demandé."""
    import artworks.config

    previous = {key: os.environ.get(key) for key in environment}
    os.environ.update(environment)
    try:
        return importlib.reload(artworks.config).Config
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(artworks.config)


class TestSessionCookie:
    """Le cookie qui porte la connexion de l'artiste et celle de l'admin."""

    def test_it_is_secure_in_production(self):
        config = _config_under(CANONICAL_SCHEME="https", CANONICAL_REDIRECT="1")
        assert config.SESSION_COOKIE_SECURE is True
        assert config.REMEMBER_COOKIE_SECURE is True

    def test_it_is_not_secure_where_the_site_answers_in_clear(self):
        """Sinon le cookie ne reviendrait jamais et plus personne ne
        pourrait se connecter en local ni en préproduction."""
        config = _config_under(CANONICAL_SCHEME="https", CANONICAL_REDIRECT="0")
        assert config.SESSION_COOKIE_SECURE is False

    def test_it_is_never_readable_by_a_script(self):
        config = _config_under(CANONICAL_SCHEME="https", CANONICAL_REDIRECT="1")
        assert config.SESSION_COOKIE_HTTPONLY is True
        assert config.REMEMBER_COOKIE_HTTPONLY is True

    def test_it_does_not_follow_a_cross_site_request(self):
        config = _config_under(CANONICAL_SCHEME="https", CANONICAL_REDIRECT="1")
        assert config.SESSION_COOKIE_SAMESITE == "Lax"
        assert config.REMEMBER_COOKIE_SAMESITE == "Lax"


class TestSecretKey:
    """`SECRET_KEY` signe la session *et* les liens de réinitialisation."""

    def test_the_default_key_is_announced_in_production(self, caplog):
        from artworks import create_app
        from artworks.config import Config

        class _Production(Config):
            SECRET_KEY = "dev-artworks-digital"
            CANONICAL_REDIRECT = True

        with caplog.at_level("WARNING"):
            create_app(_Production)
        assert "SECRET_KEY" in caplog.text

    def test_a_real_key_says_nothing(self, caplog):
        from artworks import create_app
        from artworks.config import Config

        class _Production(Config):
            SECRET_KEY = "une-vraie-clé-posée-dans-l-environnement"
            CANONICAL_REDIRECT = True

        with caplog.at_level("WARNING"):
            create_app(_Production)
        assert "SECRET_KEY" not in caplog.text


class TestWebhookIsNotForgeable:
    """Le webhook Stripe est la seule route qui écrit sans session ni
    jeton : sa seule défense est la signature.

    Le cas dangereux n'est pas « Stripe éteint » — la route répond 503 et
    rien ne se passe. C'est « Stripe allumé, secret de webhook oublié » :
    là, un simple `POST` anonyme portant l'identifiant d'un artiste
    suffisait à lui attribuer l'offre haute sans paiement.
    """

    FORGED = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"plan_key": "studio"},
                "customer": "cus_forge",
                "subscription": "sub_forge",
            }
        },
    }

    def _forged_for(self, artist):
        event = {**self.FORGED}
        event["data"] = {
            "object": {
                **self.FORGED["data"]["object"],
                "metadata": {"artist_id": artist.id, "plan_key": "studio"},
            }
        }
        return event

    def test_an_event_is_refused_when_stripe_is_off(self, client, artist, db):
        from artworks.models import Artist

        response = client.post("/stripe/webhook", json=self._forged_for(artist))
        assert response.status_code == 503
        assert db.session.get(Artist, artist.id).plan_key != "studio"

    def test_an_unsigned_event_is_refused_even_with_stripe_on(self, app, client, artist, db):
        """Le test qui compte : la faille vivait exactement ici."""
        from artworks.models import Artist

        app.config.update(STRIPE_SECRET_KEY="sk_test_bidon", STRIPE_WEBHOOK_SECRET="")
        response = client.post("/stripe/webhook", json=self._forged_for(artist))
        assert response.status_code == 400
        assert db.session.get(Artist, artist.id).plan_key != "studio"

    def test_a_badly_signed_event_is_refused(self, app, client, artist, db):
        from artworks.models import Artist

        app.config.update(
            STRIPE_SECRET_KEY="sk_test_bidon", STRIPE_WEBHOOK_SECRET="whsec_bidon"
        )
        response = client.post(
            "/stripe/webhook",
            json=self._forged_for(artist),
            headers={"Stripe-Signature": "t=1,v1=signature-inventée"},
        )
        assert response.status_code == 400
        assert db.session.get(Artist, artist.id).plan_key != "studio"


class TestStartupWarnsAboutStripe:
    def test_stripe_without_a_webhook_secret_is_announced(self, caplog):
        from artworks import create_app
        from artworks.config import Config

        class _Half(Config):
            SECRET_KEY = "une-vraie-clé"
            STRIPE_SECRET_KEY = "sk_live_bidon"
            STRIPE_WEBHOOK_SECRET = ""

        with caplog.at_level("WARNING"):
            create_app(_Half)
        assert "STRIPE_WEBHOOK_SECRET" in caplog.text

    def test_a_complete_stripe_setup_says_nothing(self, caplog):
        from artworks import create_app
        from artworks.config import Config

        class _Full(Config):
            SECRET_KEY = "une-vraie-clé"
            STRIPE_SECRET_KEY = "sk_live_bidon"
            STRIPE_WEBHOOK_SECRET = "whsec_bidon"

        with caplog.at_level("WARNING"):
            create_app(_Full)
        assert "STRIPE_WEBHOOK_SECRET" not in caplog.text
