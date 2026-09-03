"""Aucune page ne doit rendre un 500. C'est le contrôle que personne ne faisait.

Un dépôt sans exécution automatique est un angle mort : un nom non défini
dans une vue, un template qui appelle un attribut disparu, un import mort
— rien de tout cela ne se voit depuis l'extérieur tant que la page n'est
pas ouverte. Ce module ouvre chaque page, une par une, avec des données
réelles en base, et lit le code HTTP.

La distinction qui compte : 404 et 302 sont des réponses, pas des pannes.
Seul un 5xx dit « le code a levé ».
"""
from __future__ import annotations

import pytest

PUBLIC_PAGES = [
    "/",
    "/galeries",
    "/galeries.json",
    "/offres",
    "/contact",
    "/connexion",
    "/inscription",
    "/mot-de-passe-oublie",
    "/recherche?q=aube",
    "/sitemap.xml",
    "/robots.txt",
    "/llms.txt",
    "/opensearch.xml",
]

ATELIER_PAGES = [
    "/atelier/",
    "/atelier/accrochage",
    "/atelier/compte",
    "/atelier/galerie",
    "/atelier/messages",
    "/atelier/oeuvres/nouvelle",
    "/atelier/offre",
]

#: Réservées aux offres payantes : sur l'offre gratuite elles redirigent
#: vers la facturation, et leur gabarit n'est jamais rendu.
PAID_ATELIER_PAGES = [
    "/atelier/collections",
    "/atelier/ia",
    "/atelier/stats",
]

ADMIN_PAGES = [
    "/admin/",
    "/admin/abonnements",
    "/admin/analytics",
    "/admin/analytics/live",
    "/admin/artistes",
    "/admin/emails",
    "/admin/emails/modeles",
    "/admin/offres",
    "/admin/social",
]


@pytest.mark.parametrize("url", PUBLIC_PAGES)
def test_public_pages_render(client, artist, url):
    response = client.get(url)
    assert response.status_code < 500, f"{url} lève une exception"
    assert response.status_code in {200, 301, 302}, f"{url} → {response.status_code}"


@pytest.mark.parametrize("url", ATELIER_PAGES)
def test_atelier_pages_render_for_a_signed_in_artist(artist_client, url):
    response = artist_client.get(url)
    assert response.status_code < 500, f"{url} lève une exception"
    assert response.status_code == 200, f"{url} → {response.status_code}"


@pytest.mark.parametrize("url", PAID_ATELIER_PAGES)
def test_paid_pages_render_on_the_studio_plan(studio_client, url):
    response = studio_client.get(url)
    assert response.status_code < 500, f"{url} lève une exception"
    assert response.status_code == 200, f"{url} → {response.status_code}"


@pytest.mark.parametrize("url", PAID_ATELIER_PAGES)
def test_paid_pages_send_a_free_artist_to_the_offers(artist_client, url):
    """La limite d'offre est une redirection, pas une erreur."""
    response = artist_client.get(url)
    assert response.status_code == 302
    assert "/atelier/offre" in response.headers["Location"]


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_admin_pages_render_for_the_administrator(admin_client, url):
    response = admin_client.get(url)
    assert response.status_code < 500, f"{url} lève une exception"
    assert response.status_code == 200, f"{url} → {response.status_code}"


def test_a_work_page_renders(client, artist):
    response = client.get(f"/galerie/{artist.slug}/oeuvre/1")
    assert response.status_code == 200
    assert "Aube" in response.get_data(as_text=True)


def test_every_get_route_is_reachable_without_a_500(client, artist):
    """Le filet : aucune route GET n'est oubliée par les listes ci-dessus.

    Une route ajoutée demain et jamais listée sera quand même ouverte ici.
    """
    from flask import current_app

    samples = {
        "slug": artist.slug,
        "work_id": "1",
        "artist_id": str(artist.id),
        "message_id": "1",
        "kind": "bienvenue",
        "key": "essentiel",
        "plan_key": "essentiel",
        "platform": "pinterest",
        "token": "jeton-invalide",
        "name": "ping",
        "filename": "absent.png",
    }
    failures = []
    for rule in current_app.url_map.iter_rules():
        if "GET" not in rule.methods:
            continue
        url = str(rule)
        for argument in rule.arguments:
            for token in (f"<int:{argument}>", f"<path:{argument}>", f"<{argument}>"):
                if token in url:
                    url = url.replace(token, samples.get(argument, "1"))
                    break
        if "<" in url:
            continue
        response = client.get(url)
        if response.status_code >= 500:
            failures.append(f"{url} → {response.status_code}")
    assert not failures, "routes en erreur : " + ", ".join(failures)
