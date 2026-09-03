from datetime import timedelta
from io import BytesIO
import os
from pathlib import Path
from random import Random
from secrets import token_urlsafe

from PIL import Image, ImageDraw, ImageFont

from artworks.extensions import db
from artworks.images import save_bytes
from artworks.models import Artist, PageView, Work, utcnow


DEMO_DIR = Path(__file__).resolve().parent / "static" / "demo"


# Les galeries d’exemple viennent du catalogue de la V3 : sept artistes, leurs
# mots, leurs œuvres et leurs visuels. Un artiste tient une salle, et une seule.
EXAMPLES = (
    {
        "display_name": "Camille Vasseur",
        "slug": "camille-vasseur",
        "email": "camille.vasseur@galerie.artworksdigital.fr",
        "discipline": "Peinture abstraite · Huile",
        "location": "Marseille",
        "cover": "collection-abstraction.jpg",
        "statement": (
            "Je peins ce qui brûle juste avant de disparaître. La couleur n’est pas un décor : "
            "c’est une température, une matière qui se souvient du feu et de la terre. Chaque toile "
            "commence par un effacement — j’applique, je gratte, je recommence, jusqu’à ce que la "
            "surface respire d’elle-même."
        ),
        "works": (
            ("Embrasement", "2024", "Huile sur toile de lin", "120 × 90 × 4 cm",
             "Le rouge n’éclaire pas : il chauffe.", "art-01.jpg", "Abstraction"),
            ("Aube rouge", "2023", "Huile sur toile de lin", "70 × 95 cm",
             "Ce qui reste du feu au matin.", "oeuvre-main.jpg", "Abstraction"),
        ),
    },
    {
        "display_name": "Théo Lambert",
        "slug": "theo-lambert",
        "email": "theo.lambert@galerie.artworksdigital.fr",
        "discipline": "Color field · Acrylique",
        "location": "Nantes",
        "cover": "cover-color-field.jpg",
        "statement": (
            "Je cherche l’horizon : cette ligne où deux couleurs se rencontrent sans jamais se "
            "toucher. De grands aplats où la lumière semble retenue, et la lenteur d’une transition "
            "qui ne veut pas finir."
        ),
        "works": (
            ("Marée basse", "2023", "Acrylique sur toile", "100 × 140 cm",
             "Deux bleus qui se cèdent le passage.", "art-02.jpg", "Color field"),
        ),
    },
    {
        "display_name": "Inès Caron",
        "slug": "ines-caron",
        "email": "ines.caron@galerie.artworksdigital.fr",
        "discipline": "Photographie argentique",
        "location": "Paris",
        "cover": "collection-photographie.jpg",
        "statement": (
            "Le silence a une texture. Je la cherche dans le grain de l’argentique. Je photographie "
            "le vide et la matière en noir et blanc ; chaque tirage est fait à la main, à l’atelier."
        ),
        "works": (
            ("Silence n°7", "2024", "Tirage argentique sur papier baryté", "60 × 80 cm",
             "Le grain tient lieu de sujet.", "art-03.jpg", "Argentique"),
            ("Horizon", "2024", "Tirage argentique sur papier baryté", "50 × 70 cm",
             "Une ligne, et beaucoup de patience.", "art-10.jpg", "Argentique"),
        ),
    },
    {
        "display_name": "Marius Hadi",
        "slug": "marius-hadi",
        "email": "marius.hadi@galerie.artworksdigital.fr",
        "discipline": "Abstraction géométrique",
        "location": "Lyon",
        "cover": "cover-geometrie.jpg",
        "statement": (
            "La géométrie est une émotion qui a trouvé sa forme. Je compose des architectures de "
            "couleurs où l’équilibre tient à un fil, avec un vocabulaire puisé dans le Bauhaus et "
            "dans la musique."
        ),
        "works": (
            ("Géométrie douce", "2023", "Acrylique sur bois", "80 × 80 cm",
             "L’angle s’excuse presque.", "art-04.jpg", "Géométrie"),
            ("Contrepoint", "2023", "Acrylique sur toile", "75 × 100 cm",
             "Deux voix, une seule mesure.", "art-11.jpg", "Géométrie"),
            ("Carnaval", "2024", "Acrylique sur toile", "80 × 80 cm",
             "La règle prend un jour de congé.", "art-08.jpg", "Abstraction"),
        ),
    },
    {
        "display_name": "Salomé Drift",
        "slug": "salome-drift",
        "email": "salome.drift@galerie.artworksdigital.fr",
        "discipline": "Peinture abstraite · Huile",
        "location": "Arles",
        "cover": "banner.jpg",
        "statement": (
            "Je laboure la toile comme on retourne une terre : pour ce qu’elle garde en mémoire. "
            "Matière épaisse, pigments, sillons — des paysages abstraits qui viennent de la "
            "campagne provençale."
        ),
        "works": (
            ("Terres labourées", "2022", "Huile et pigments sur toile", "90 × 130 cm",
             "Le sillon avant la récolte.", "art-05.jpg", "Terres"),
            ("Sillage", "2024", "Huile sur toile", "60 × 40 cm",
             "Le petit format, là où la main se voit.", "art-12.jpg", "Terres"),
        ),
    },
    {
        "display_name": "Élena Roux",
        "slug": "elena-roux",
        "email": "elena.roux@galerie.artworksdigital.fr",
        "discipline": "Figuration",
        "location": "Bordeaux",
        "cover": "collection-emergents.jpg",
        "statement": (
            "Je peins des présences à la lisière de la lumière. Des intérieurs, des portraits, et "
            "le clair-obscur pour seule intimité."
        ),
        "works": (
            ("Femme à la fenêtre", "2024", "Huile sur toile", "65 × 80 cm",
             "Elle regarde dehors ; nous, dedans.", "art-06.jpg", "Figuration"),
        ),
    },
    {
        "display_name": "Atelier Nova",
        "slug": "atelier-nova",
        "email": "nova@galerie.artworksdigital.fr",
        "discipline": "Sculpture · Bronze",
        "location": "Genève",
        "cover": "collection-sculpture.jpg",
        "statement": (
            "Le bronze est une attente qui prend forme. Deux sculpteurs, des formes organiques "
            "patinées, quelque part entre la figure et l’abstraction."
        ),
        "works": (
            ("Veille", "2023", "Bronze patiné, pièce unique", "H. 48 cm",
             "Debout, sans rien attendre de précis.", "art-07.jpg", "Bronzes"),
        ),
    },
)


def _photo(filename: str, max_side: int = 2000) -> tuple[str, int, int] | None:
    """Range un visuel de démonstration dans le magasin d’images du site.

    Les fichiers vivent dans ``static/demo``. Le seed les fait passer par le
    même chemin que les téléversements d’artistes : ils sont donc servis par
    ``/media`` comme le reste, et survivent au disque éphémère de Scalingo.
    Un fichier manquant ne fait pas tomber le seed — l’œuvre est simplement
    passée."""
    source = DEMO_DIR / filename
    if not source.is_file() or source.stat().st_size == 0:
        return None
    try:
        image = Image.open(source)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail((max_side, max_side))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=86, optimize=True)
    except OSError:
        return None
    return save_bytes(buffer.getvalue()), image.width, image.height


def _og_default() -> bytes:
    image = Image.new("RGB", (1200, 630), (243, 239, 230))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 630), outline=(92, 70, 52), width=0)
    draw.rectangle((80, 80, 1120, 550), outline=(216, 208, 196), width=1)
    try:
        font = ImageFont.truetype("arial.ttf", 72)
        small = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
        small = font
    draw.text((120, 230), "Artworksdigital", fill=(22, 20, 18), font=font)
    draw.text((120, 330), "La galerie appartient à l’artiste.", fill=(92, 70, 52), font=small)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=86, optimize=True)
    return buffer.getvalue()


def write_og_image() -> None:
    from pathlib import Path

    dest = Path(__file__).resolve().parent / "static" / "og-default.jpg"
    if dest.exists() and dest.stat().st_size > 1000:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_og_default())


def promote_admins() -> None:
    from flask import current_app

    admin_email = (current_app.config.get("ADMIN_EMAIL") or "").strip().lower()
    changed = False
    if admin_email:
        artist = Artist.query.filter_by(email=admin_email).first()
        if artist and not artist.is_admin:
            artist.is_admin = True
            changed = True
    if not Artist.query.filter_by(is_admin=True).first():
        for artist in Artist.query.filter_by(is_example=False).all():
            artist.is_admin = True
            changed = True
    if changed:
        db.session.commit()


def seed_examples() -> None:
    write_og_image()
    created = False
    try:
        for spec in EXAMPLES:
            if Artist.query.filter((Artist.slug == spec["slug"]) | (Artist.email == spec["email"])).first():
                continue
            artist = Artist(
                email=spec["email"],
                display_name=spec["display_name"],
                slug=spec["slug"],
                statement=spec["statement"],
                location=spec["location"],
                discipline=spec["discipline"],
                contact_email=spec["email"],
                published=True,
                is_example=True,
                is_admin=False,
                plan_key="studio",
            )
            artist.set_password(token_urlsafe(24))
            db.session.add(artist)
            db.session.flush()
            cover = _photo(spec["cover"])
            if cover:
                artist.cover_path = cover[0]
            position = 0
            for title, year, medium, dimensions, note, photo, collection in spec["works"]:
                visual = _photo(photo)
                if visual is None:
                    continue
                image_path, width, height = visual
                db.session.add(
                    Work(
                        artist_id=artist.id,
                        title=title,
                        year=year,
                        medium=medium,
                        dimensions=dimensions,
                        note=note,
                        image_path=image_path,
                        image_w=width,
                        image_h=height,
                        collection_name=collection,
                        visible=True,
                        position=position,
                    )
                )
                position += 1
            created = True
        if created:
            db.session.commit()
        for artist in Artist.query.filter_by(is_example=True).all():
            if artist.plan_key != "studio":
                artist.plan_key = "studio"
                artist.plan_status = "active"
                created = True
        if created:
            db.session.commit()
    except Exception:
        db.session.rollback()
    seed_demo_traffic()


def seed_demo_traffic() -> None:
    from flask import current_app

    if not current_app.debug and os.environ.get("SEED_DEMO_TRAFFIC") != "1":
        return
    if PageView.query.count() > 0:
        paint_demo_geo()
        return
    artists = Artist.query.filter_by(is_example=True, published=True).all()
    if not artists:
        return
    rng = Random("traffic")
    now = utcnow()
    rows = []
    for _ in range(72):
        artist = rng.choice(artists)
        works = artist.hung_works
        work = rng.choice(works) if works and rng.random() > 0.45 else None
        path = f"/galerie/{artist.slug}"
        title = artist.display_name
        work_id = None
        if work:
            path = f"/galerie/{artist.slug}/oeuvre/{work.id}"
            title = f"{work.title} — {artist.display_name}"
            work_id = work.id
        referrer = rng.choice(("", "https://www.google.fr/", "https://instagram.com/", "https://www.bing.com/"))
        city, country, code = rng.choice((
            ("Paris", "France", "FR"),
            ("Lyon", "France", "FR"),
            ("Marseille", "France", "FR"),
            ("Bordeaux", "France", "FR"),
            ("Bruxelles", "Belgique", "BE"),
            ("Genève", "Suisse", "CH"),
        ))
        host = ""
        if "google" in referrer:
            host = "google.fr"
        elif "instagram" in referrer:
            host = "instagram.com"
        elif "bing" in referrer:
            host = "bing.com"
        rows.append(
            PageView(
                path=path,
                title=title,
                referrer=referrer,
                referrer_host=host,
                source=rng.choice(("direct", "organic", "social", "referral")),
                device=rng.choice(("desktop", "mobile", "tablet")),
                city=city,
                country=country,
                country_code=code,
                session_id=token_urlsafe(8),
                artist_id=artist.id,
                work_id=work_id,
                is_bot=False,
                created_at=now - timedelta(days=rng.randint(0, 20), hours=rng.randint(0, 23)),
            )
        )
    db.session.add_all(rows)
    db.session.commit()
    paint_demo_geo()


def paint_demo_geo() -> None:
    """En local, les anciennes vues n’ont pas de ville : on leur en donne une."""
    from flask import current_app

    if not current_app.debug:
        return
    vacant = PageView.query.filter((PageView.city == "") | (PageView.city.is_(None))).all()
    if not vacant and PageView.query.filter(PageView.created_at >= utcnow() - timedelta(minutes=5)).count():
        return
    rng = Random("geo")
    places = (
        ("Paris", "France", "FR"),
        ("Lyon", "France", "FR"),
        ("Lille", "France", "FR"),
        ("Nantes", "France", "FR"),
        ("Bruxelles", "Belgique", "BE"),
    )
    for row in vacant:
        city, country, code = rng.choice(places)
        row.city = city
        row.country = country
        row.country_code = code
        if row.referrer and not row.referrer_host:
            if "google" in row.referrer:
                row.referrer_host = "google.fr"
            elif "instagram" in row.referrer:
                row.referrer_host = "instagram.com"
            elif "bing" in row.referrer:
                row.referrer_host = "bing.com"
    if not PageView.query.filter(PageView.created_at >= utcnow() - timedelta(minutes=5)).count():
        artists = Artist.query.filter_by(is_example=True, published=True).all()
        if artists:
            artist = rng.choice(artists)
            city, country, code = rng.choice(places)
            db.session.add(
                PageView(
                    path=f"/galerie/{artist.slug}",
                    title=artist.display_name,
                    source="organic",
                    referrer="https://www.google.fr/",
                    referrer_host="google.fr",
                    device="mobile",
                    city=city,
                    country=country,
                    country_code=code,
                    session_id=token_urlsafe(8),
                    artist_id=artist.id,
                    is_bot=False,
                    created_at=utcnow() - timedelta(seconds=rng.randint(20, 180)),
                )
            )
    db.session.commit()
