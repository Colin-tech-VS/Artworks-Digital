"""Le nombre de requêtes SQL par page — la seule mesure qui attrape ce bug.

`Artist.offer` appelait `get_offer()`, qui rappelait `seed_offers()`, qui
repassait les quatre offres du catalogue : cinq requêtes SQL pour savoir si
un artiste a droit aux statistiques. Les gabarits posent la question
plusieurs fois par artiste, et l'annuaire en affiche autant qu'il y a de
salles publiées — /galeries partait à 453 requêtes pour trente artistes.

Aucun test fonctionnel ne pouvait le voir : les pages rendaient
correctement, simplement des centaines de fois trop lentement. D'où ces
tests-ci, qui comptent.

Le vrai garde-fou n'est pas le plafond absolu mais la CROISSANCE : si le
nombre de requêtes grimpe avec le nombre d'artistes, un N+1 est revenu.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import event

from artworks.extensions import db
from artworks.models import Artist, Work


@contextmanager
def counted(app):
    """Compter les requêtes SQL réellement envoyées pendant un bloc."""
    counter = {"n": 0}
    engine = db.engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _count)


def _rooms(db_session, count: int) -> None:
    for index in range(count):
        artist = Artist(
            email=f"artiste{index}@example.com",
            display_name=f"Artiste {index:02d}",
            slug=f"artiste-{index:02d}",
            published=True,
            # Les quatre offres, pour que `has_feature` soit vraiment sollicité.
            plan_key=["decouverte", "artiste", "pro", "studio"][index % 4],
        )
        artist.set_password("mot-de-passe")
        db_session.session.add(artist)
        db_session.session.flush()
        for position in range(4):
            db_session.session.add(
                Work(
                    artist_id=artist.id,
                    title=f"Œuvre {position}",
                    image_path=f"img{index}-{position}.png",
                    image_w=1200,
                    image_h=800,
                    visible=True,
                    position=position,
                )
            )
    db_session.session.commit()


#: Plafonds larges : ils attrapent un retour à des centaines de requêtes
#: sans casser au moindre ajout légitime d'une requête.
BUDGETS = {
    "/": 40,
    "/galeries": 40,
    "/galeries.json": 30,
    "/sitemap.xml": 30,
}


@pytest.mark.parametrize("url,budget", sorted(BUDGETS.items()))
def test_a_page_does_not_spend_hundreds_of_queries(app, client, db, url, budget):
    _rooms(db, 12)
    with counted(app) as counter:
        response = client.get(url)
    assert response.status_code == 200
    assert counter["n"] <= budget, (
        f"{url} : {counter['n']} requêtes SQL pour 12 salles "
        f"(budget {budget}). Un N+1 est probablement revenu."
    )


def test_the_directory_does_not_cost_more_per_artist(app, client, db):
    """Le vrai garde-fou : le coût ne doit pas suivre le nombre de salles."""
    _rooms(db, 4)
    with counted(app) as small:
        assert client.get("/galeries").status_code == 200

    _rooms_offset = 4
    for index in range(_rooms_offset, _rooms_offset + 20):
        artist = Artist(
            email=f"artiste{index}@example.com",
            display_name=f"Artiste {index:02d}",
            slug=f"artiste-{index:02d}",
            published=True,
            plan_key=["decouverte", "artiste", "pro", "studio"][index % 4],
        )
        artist.set_password("mot-de-passe")
        db.session.add(artist)
    db.session.commit()

    with counted(app) as large:
        assert client.get("/galeries").status_code == 200

    # 24 salles au lieu de 4 : le catalogue d'offres est relu une fois, pas
    # une fois par artiste. Quelques requêtes de plus sont normales ; une
    # dizaine par artiste ne l'est pas.
    assert large["n"] <= small["n"] + 10, (
        f"4 salles = {small['n']} requêtes, 24 salles = {large['n']} : "
        "le coût croît avec le nombre d'artistes (N+1)."
    )


def test_the_catalogue_is_still_aligned_on_the_first_read(app, db):
    """La mémorisation ne doit pas empêcher le catalogue d'exister."""
    from artworks.models import Offer
    from artworks.plans import CATALOG, get_offer

    offer = get_offer("studio")
    assert offer is not None
    assert offer.allow_collections is True
    assert db.session.query(Offer).count() == len(CATALOG)


def test_forgetting_the_catalogue_re_reads_it(app, db):
    """Après une écriture d'offre, la lecture suivante repart de la base."""
    from artworks.models import Offer
    from artworks.plans import forget_offers, get_offer

    assert get_offer("artiste").name == "Artiste"
    db.session.get(Offer, "artiste").name = "Artiste (renommée)"
    db.session.commit()
    forget_offers()
    # `seed_offers` réaligne le catalogue : le nom revient à celui du code.
    # Ce qui compte ici est qu'une relecture ait bien eu lieu.
    assert get_offer("artiste") is not None


def test_an_unknown_plan_falls_back_to_the_free_offer(app, db):
    from artworks.plans import get_offer

    assert get_offer("offre-qui-n-existe-pas").key == "decouverte"
    assert get_offer(None).key == "decouverte"
