"""Titres, descriptions et alt : ils tiennent dans l’extrait, et les images ont un nom."""

from __future__ import annotations

import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from artworks import create_app
from artworks.config import Config
from artworks.extensions import db
from artworks.models import Artist, Asset, Work
from artworks.seo import SITE_NAME, TITLE_LIMIT, meta_trim, page_title


class _HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = attrs.get("name") or attrs.get("property") or ""
            if name and "content" in attrs:
                self.meta[name] = attrs["content"]
        elif tag == "img":
            self.images.append(attrs.get("alt", None))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _parse(html: str) -> _HeadParser:
    parser = _HeadParser()
    parser.feed(html)
    return parser


class _SeoConfig(Config):
    TESTING = True
    SECRET_KEY = "test-seo"
    SITE_UNLOCK_PASSWORD = ""
    CANONICAL_REDIRECT = False
    CANONICAL_HOST = "www.artworksdigital.fr"
    WTF_CSRF_ENABLED = False
    KAEL_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {}


class SeoHelpersTest(unittest.TestCase):
    def test_page_title_keeps_under_limit(self):
        title = page_title("Claire Morel", f"galerie {SITE_NAME}")
        self.assertLessEqual(len(title), TITLE_LIMIT)
        self.assertIn("Claire Morel", title)
        self.assertIn(SITE_NAME, title)

    def test_page_title_trims_long_primary(self):
        long_name = "A" * 80
        title = page_title(long_name, f"galerie {SITE_NAME}")
        self.assertLessEqual(len(title), TITLE_LIMIT)
        self.assertTrue(title.endswith(SITE_NAME))
        self.assertIn("…", title)

    def test_page_title_drops_huge_suffix(self):
        title = page_title("Horizon", "B" * 80)
        self.assertLessEqual(len(title), TITLE_LIMIT)
        self.assertTrue(title.startswith("Horizon"))

    def test_meta_trim_cuts_on_a_word(self):
        text = meta_trim("Une phrase assez longue pour dépasser la limite imposée aux extraits.", 40)
        self.assertLessEqual(len(text), 40)
        self.assertTrue(text.endswith("…"))


class PublicSeoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "seo.db"

        class Cfg(_SeoConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"

        self.app = create_app(Cfg)
        self.client = self.app.test_client()
        with self.app.app_context():
            artist = Artist(
                email="claire@test.fr",
                display_name="Claire Morel",
                slug="claire-morel",
                statement="Toiles posées contre le jour.",
                location="Lyon",
                discipline="Peinture",
                published=True,
                cover_path="cover.jpg",
                plan_key="pro",
            )
            artist.set_password("secret-ok-1")
            db.session.add(artist)
            db.session.add(Asset(id="cover.jpg", mime="image/jpeg", data=b"cover"))
            db.session.add(Asset(id="work.jpg", mime="image/jpeg", data=b"work"))
            db.session.add(
                Work(
                    artist=artist,
                    title="Horizon",
                    year="2024",
                    medium="Huile sur toile",
                    dimensions="80 × 60 cm",
                    image_path="work.jpg",
                    visible=True,
                    image_w=800,
                    image_h=600,
                )
            )
            db.session.commit()
            self.artist_id = artist.id
            self.work_id = artist.works.first().id

    def tearDown(self):
        self._tmp.cleanup()

    def _assert_public_head(self, html: str, *, allow_empty_alt: bool = False):
        head = _parse(html)
        self.assertTrue(head.title.strip())
        self.assertLess(len(head.title.strip()), 60, head.title)
        desc = head.meta.get("description", "")
        self.assertTrue(desc, "méta-description absente")
        self.assertLess(len(desc), 160, desc)
        self.assertIn("Artworks Digital", head.title + desc + head.meta.get("og:site_name", ""))
        self.assertEqual(head.meta.get("og:title"), head.title.strip())
        self.assertTrue(head.meta.get("og:description"))
        if not allow_empty_alt:
            self.assertTrue(head.images, "aucune image à vérifier")
            for alt in head.images:
                self.assertIsNotNone(alt, "image sans attribut alt")
                self.assertTrue(alt.strip(), f"alt vide : {alt!r}")

    def test_home_title_and_description(self):
        html = self.client.get("/").get_data(as_text=True)
        self._assert_public_head(html, allow_empty_alt=True)
        head = _parse(html)
        self.assertEqual(head.title.strip(), "Artworks Digital — chaque artiste ouvre sa galerie")
        self.assertIn("galerie d’artiste", head.meta["description"])
        self.assertNotIn("Votre salle. Vos œuvres.", head.title)

    def test_coming_soon_title_when_gated(self):
        class Cfg(_SeoConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(Path(self._tmp.name) / 'gate.db').as_posix()}"
            SITE_UNLOCK_PASSWORD = "secret-gate"

        gated = create_app(Cfg)
        with gated.test_client() as client:
            html = client.get("/").get_data(as_text=True)
        head = _parse(html)
        self.assertEqual(head.title.strip(), "Artworks Digital revient — galerie d’artistes")
        self.assertLess(len(head.title.strip()), 60)
        self.assertLess(len(head.meta["description"]), 160)
        self.assertIn("galerie", head.meta["description"].lower())
        self.assertEqual(head.meta.get("og:description"), head.meta["description"])
        self.assertTrue(head.meta.get("og:image:alt"))
        self.assertTrue(head.meta.get("twitter:title"))
        self.assertIn("Artworksdigital <em>revient</em>", html)

    def test_listing_pages(self):
        for path in ("/galeries", "/offres", "/contact"):
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                allow_empty = path != "/galeries"
                self._assert_public_head(html, allow_empty_alt=allow_empty)

    def test_gallery_and_artwork_alts_name_the_work(self):
        gallery = self.client.get("/galerie/claire-morel").get_data(as_text=True)
        self._assert_public_head(gallery)
        self.assertIn('alt="Galerie de Claire Morel — Peinture"', gallery)
        self.assertIn("œuvre de Claire Morel", gallery)
        self.assertRegex(gallery, r"<title>[^<]*Claire Morel[^<]*</title>")

        artwork = self.client.get(f"/galerie/claire-morel/oeuvre/{self.work_id}").get_data(as_text=True)
        self._assert_public_head(artwork)
        self.assertIn("Horizon, 2024, œuvre de Claire Morel", artwork)
        head = _parse(artwork)
        self.assertLess(len(head.title), 60)
        self.assertIn("Horizon", head.title)

    def test_long_names_stay_in_the_snippet(self):
        with self.app.app_context():
            artist = db.session.get(Artist, self.artist_id)
            artist.display_name = "Marie-Hélène " + ("Dupont-Lefebvre " * 6)
            work = db.session.get(Work, self.work_id)
            work.title = "Composition monumentale sur le thème de la lumière du matin " * 3
            db.session.commit()
            self.assertLessEqual(len(artist.seo_title), TITLE_LIMIT)
            self.assertLessEqual(len(work.seo_title), TITLE_LIMIT)
            self.assertLessEqual(len(artist.seo_description), 158)
            self.assertLessEqual(len(work.seo_description), 158)
            self.assertLessEqual(len(work.image_alt), 125)

        gallery = self.client.get("/galerie/claire-morel").get_data(as_text=True)
        artwork = self.client.get(f"/galerie/claire-morel/oeuvre/{self.work_id}").get_data(as_text=True)
        self.assertLess(len(_parse(gallery).title), 60)
        self.assertLess(len(_parse(artwork).title), 60)
        self.assertLess(len(_parse(gallery).meta["description"]), 160)
        self.assertLess(len(_parse(artwork).meta["description"]), 160)

    def test_sitemap_captions_describe_images(self):
        xml = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("<image:caption>", xml)
        self.assertIn("œuvre de Claire Morel", xml)
        self.assertIn("Galerie de Claire Morel", xml)

    def test_editorial_letter_is_untouched(self):
        class Cfg(_SeoConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(Path(self._tmp.name) / 'letter.db').as_posix()}"
            SITE_UNLOCK_PASSWORD = "secret-gate"

        gated = create_app(Cfg)
        with gated.test_client() as client:
            html = client.get("/").get_data(as_text=True)
        self.assertIn("Nous vous devons une petite explication.", html)
        self.assertIn("Artworksdigital a été temporairement fermé.", html)


if __name__ == "__main__":
    unittest.main()
