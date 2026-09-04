"""Ce que la refonte a ajouté, et qui doit tenir en production.

Trois familles de contrôles :

* les **déclinaisons d'images** — la page ne doit plus servir un visuel de
  deux mille pixels dans une vignette, et la liste des largeurs doit
  rester close, sinon n'importe quelle requête remplit le disque ;
* les **pages par discipline** — de vraies adresses, donc de vraies
  réponses : 404 quand la discipline n'existe pas, absence quand la salle
  n'est pas publiée ;
* le **balisage** — un JSON-LD invalide ne se voit pas à l'œil nu et ne
  casse aucune page ; il coûte simplement toute la lecture qu'un moteur
  aurait pu en faire. Autant le lire nous-mêmes à chaque exécution.
"""
from __future__ import annotations

import json
import re
from io import BytesIO
from xml.etree import ElementTree

import pytest
from PIL import Image

from artworks.extensions import db
from artworks.images import VARIANT_WIDTHS, save_bytes
from artworks.models import Artist, Work
from artworks.search import discipline_slug, kin_rooms, wall_works


JSONLD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def blocks_of(html: str) -> list[dict]:
    found = []
    for raw in JSONLD.findall(html):
        found.append(json.loads(raw))
    return found


@pytest.fixture
def painted(db, artist):
    """La salle de référence, avec un vrai visuel mesurable en base.

    Les autres fixtures posent un `image_path` qui ne désigne aucun octet :
    parfait pour vérifier qu'une page rend, inutile pour vérifier qu'une
    image est redimensionnée."""
    buffer = BytesIO()
    Image.new("RGB", (2000, 1400), (120, 90, 60)).save(buffer, format="JPEG")
    name = save_bytes(buffer.getvalue())
    artist.discipline = "Peinture"
    artist.location = "Marseille"
    work = artist.works.first()
    work.image_path = name
    work.image_w, work.image_h = 2000, 1400
    db.session.commit()
    return artist


class TestLesDeclinaisonsDImages:
    def test_a_variant_is_served_at_the_asked_width(self, client, painted):
        name = painted.works.first().image_path
        response = client.get(f"/media/w480/{name}")
        assert response.status_code == 200
        with Image.open(BytesIO(response.data)) as image:
            assert image.width == 480

    def test_every_declared_width_answers(self, client, painted):
        name = painted.works.first().image_path
        for width in VARIANT_WIDTHS:
            assert client.get(f"/media/w{width}/{name}").status_code == 200

    def test_an_undeclared_width_is_refused(self, client, painted):
        """Sinon un robot fabrique mille tailles et remplit le disque."""
        name = painted.works.first().image_path
        assert client.get(f"/media/w481/{name}").status_code == 404
        assert client.get(f"/media/w9999/{name}").status_code == 404

    def test_a_variant_weighs_less_than_the_original(self, client, painted):
        name = painted.works.first().image_path
        small = client.get(f"/media/w480/{name}").data
        full = client.get(f"/media/{name}").data
        assert len(small) < len(full)

    def test_an_unknown_visual_is_a_404_not_a_crash(self, client, painted):
        assert client.get("/media/w480/inconnu.jpg").status_code == 404

    def test_a_variant_never_enlarges_a_small_original(self, client, db):
        buffer = BytesIO()
        Image.new("RGB", (300, 200), (10, 10, 10)).save(buffer, format="JPEG")
        name = save_bytes(buffer.getvalue())
        db.session.commit()
        response = client.get(f"/media/w1600/{name}")
        with Image.open(BytesIO(response.data)) as image:
            assert image.width == 300

    def test_the_page_asks_for_a_variant_not_the_original(self, client, painted):
        html = client.get(f"/galerie/{painted.slug}").get_data(as_text=True)
        assert "/media/w" in html


class TestLesPagesParDiscipline:
    def test_a_discipline_with_a_room_has_its_own_address(self, client, painted):
        response = client.get("/galeries/peinture")
        assert response.status_code == 200
        assert painted.display_name in response.get_data(as_text=True)

    def test_an_unknown_discipline_is_a_404(self, client, painted):
        assert client.get("/galeries/macrame").status_code == 404

    def test_an_unpublished_room_does_not_open_a_discipline(self, client, db, artist):
        artist.discipline = "Gravure"
        artist.published = False
        db.session.commit()
        assert client.get("/galeries/gravure").status_code == 404

    def test_accents_and_spaces_become_an_address(self):
        assert discipline_slug("Art numérique") == "art-numerique"
        assert discipline_slug("Photographie") == "photographie"
        assert discipline_slug("  ") == ""

    def test_the_sitemap_lists_the_discipline(self, client, painted):
        body = client.get("/sitemap.xml").get_data(as_text=True)
        assert "/galeries/peinture" in body

    def test_the_directory_links_to_it(self, client, painted):
        assert "/galeries/peinture" in client.get("/galeries").get_data(as_text=True)


class TestLeFluxDesSalles:
    def test_the_feed_is_valid_xml(self, client, artist):
        response = client.get("/galeries.atom")
        assert response.status_code == 200
        root = ElementTree.fromstring(response.data)
        assert root.tag.endswith("feed")

    def test_a_published_room_is_an_entry(self, client, artist):
        assert artist.display_name in client.get("/galeries.atom").get_data(as_text=True)

    def test_an_unpublished_room_stays_out(self, client, db, artist):
        artist.published = False
        db.session.commit()
        assert artist.display_name not in client.get("/galeries.atom").get_data(as_text=True)


class TestLeBalisage:
    """Un JSON-LD cassé ne casse rien — il ne rapporte simplement rien."""

    @pytest.mark.parametrize(
        "url",
        ["/", "/galeries", "/galeries/peinture", "/offres", "/contact"],
    )
    def test_every_public_page_carries_readable_jsonld(self, client, painted, url):
        html = client.get(url).get_data(as_text=True)
        found = blocks_of(html)
        assert found, f"aucun JSON-LD sur {url}"

    def test_a_room_and_its_work_carry_readable_jsonld(self, client, painted):
        work = painted.works.first()
        for url in (f"/galerie/{painted.slug}", f"/galerie/{painted.slug}/oeuvre/{work.id}"):
            assert blocks_of(client.get(url).get_data(as_text=True))

    def test_the_work_page_names_its_artist_as_creator(self, client, painted):
        work = painted.works.first()
        html = client.get(f"/galerie/{painted.slug}/oeuvre/{work.id}").get_data(as_text=True)
        graph = [node for block in blocks_of(html) for node in block.get("@graph", [])]
        art = next(node for node in graph if node.get("@type") == "VisualArtwork")
        assert art["creator"]["name"] == painted.display_name
        assert art["copyrightNotice"].endswith(painted.display_name)

    def test_the_home_declares_the_wall_as_a_gallery(self, client, painted):
        graph = [node for block in blocks_of(client.get("/").get_data(as_text=True))
                 for node in block.get("@graph", [])]
        types = {node.get("@type") for node in graph}
        assert "ImageGallery" in types
        assert "FAQPage" in types

    def test_a_room_without_a_statement_still_carries_valid_jsonld(self, client, db, painted):
        """Le guillemet d'une note d'intention casserait le JSON s'il n'était
        pas échappé — et une note vide ne doit pas laisser un champ béant."""
        painted.statement = 'Une note « avec des guillemets » et un "double".'
        db.session.commit()
        assert blocks_of(client.get(f"/galerie/{painted.slug}").get_data(as_text=True))


class TestLesEnTetes:
    def test_a_public_page_carries_the_usual_protections(self, client, artist):
        headers = client.get("/").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Permissions-Policy" in headers

    def test_the_private_side_stays_out_of_the_engines(self, artist_client):
        assert "noindex" in artist_client.get("/atelier/").headers["X-Robots-Tag"]

    def test_a_visual_is_cached_for_a_year(self, client, painted):
        name = painted.works.first().image_path
        assert "immutable" in client.get(f"/media/{name}").headers["Cache-Control"]


class TestCeQueLAccueilMontre:
    def test_the_home_shows_real_works_not_only_names(self, client, painted):
        html = client.get("/").get_data(as_text=True)
        assert painted.works.first().title in html
        assert "/media/w" in html

    def test_an_empty_site_does_not_break_the_home(self, client, db):
        assert client.get("/").status_code == 200

    def test_the_wall_never_exceeds_its_limit(self, db, artist):
        for i in range(9):
            db.session.add(Work(artist_id=artist.id, title=f"Œuvre {i}",
                                image_path=f"{i}.png", visible=True, position=i))
        db.session.commit()
        rooms = [artist]
        assert len(wall_works(rooms, limit=4, per_room=3)) <= 4

    def test_the_wall_respects_the_plan_ceiling(self, db, artist):
        """L'offre Découverte plafonne à cinq œuvres publiques : la sixième
        n'a rien à faire sur le mur de l'accueil."""
        for i in range(9):
            db.session.add(Work(artist_id=artist.id, title=f"Œuvre {i}",
                                image_path=f"{i}.png", visible=True, position=i + 1))
        db.session.commit()
        picked = wall_works([artist], limit=20, per_room=20)
        assert len(picked) <= 5


class TestLesSallesVoisines:
    def test_a_room_is_never_its_own_neighbour(self, db, artist):
        assert all(other.id != artist.id for other in kin_rooms([artist], artist))

    def test_the_same_discipline_comes_first(self, db, artist):
        artist.discipline = "Peinture"
        near = Artist(email="a@b.fr", display_name="Voisine", slug="voisine",
                      discipline="Peinture", published=True)
        near.set_password("x")
        far = Artist(email="c@d.fr", display_name="Lointaine", slug="lointaine",
                     discipline="Sculpture", published=True)
        far.set_password("x")
        db.session.add_all([near, far])
        db.session.commit()
        assert kin_rooms([artist, far, near], artist)[0].id == near.id
