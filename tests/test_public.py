"""Ce que le public voit — et surtout ce qu'il ne doit pas voir.

Une salle non publiée qui apparaîtrait dans l'annuaire, le sitemap ou la
recherche serait une fuite silencieuse : rien ne planterait, personne ne
s'en apercevrait. D'où ces tests.
"""
from __future__ import annotations

from artworks.models import Artist, Work


def _hidden_room(db, slug="salle-privee"):
    artist = Artist(
        email=f"{slug}@example.com",
        display_name="Salle non publiée",
        slug=slug,
        published=False,
    )
    artist.set_password("mot-de-passe")
    db.session.add(artist)
    db.session.flush()
    db.session.add(
        Work(
            artist_id=artist.id,
            title="Œuvre cachée",
            image_path="cachee.png",
            image_w=800,
            image_h=600,
            visible=True,
        )
    )
    db.session.commit()
    return artist


class TestVisibility:
    def test_a_published_room_is_reachable(self, client, artist):
        response = client.get(f"/galerie/{artist.slug}")
        assert response.status_code == 200
        assert artist.display_name in response.get_data(as_text=True)

    def test_an_unpublished_room_is_a_404(self, client, db):
        hidden = _hidden_room(db)
        assert client.get(f"/galerie/{hidden.slug}").status_code == 404

    def test_an_unpublished_room_stays_out_of_the_directory(self, client, db, artist):
        hidden = _hidden_room(db)
        page = client.get("/galeries").get_data(as_text=True)
        assert artist.display_name in page
        assert hidden.display_name not in page

    def test_an_unpublished_room_stays_out_of_the_sitemap(self, client, db, artist):
        hidden = _hidden_room(db)
        sitemap = client.get("/sitemap.xml").get_data(as_text=True)
        assert f"/galerie/{artist.slug}" in sitemap
        assert f"/galerie/{hidden.slug}" not in sitemap

    def test_an_unpublished_room_stays_out_of_the_feed(self, client, db, artist):
        hidden = _hidden_room(db)
        feed = client.get("/galeries.json").get_data(as_text=True)
        assert artist.slug in feed
        assert hidden.slug not in feed

    def test_a_work_of_an_unpublished_room_is_a_404(self, client, db):
        hidden = _hidden_room(db)
        assert client.get(f"/galerie/{hidden.slug}/oeuvre/1").status_code == 404


class TestSearch:
    def test_a_query_finds_the_room_by_its_name(self, client, artist):
        page = client.get("/galeries?q=Camille").get_data(as_text=True)
        assert artist.display_name in page

    def test_a_query_that_matches_nothing_is_not_an_error(self, client, artist):
        response = client.get("/galeries?q=zzzzzzzz")
        assert response.status_code == 200


class TestFeeds:
    def test_robots_points_at_the_sitemap(self, client):
        body = client.get("/robots.txt").get_data(as_text=True)
        assert "sitemap" in body.lower()

    def test_the_sitemap_is_valid_xml(self, client, artist):
        from xml.etree import ElementTree

        body = client.get("/sitemap.xml").get_data(as_text=True)
        ElementTree.fromstring(body)  # lève si le XML est cassé

    def test_the_rooms_feed_is_valid_json(self, client, artist):
        response = client.get("/galeries.json")
        assert response.status_code == 200
        assert response.get_json() is not None
