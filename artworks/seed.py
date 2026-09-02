from datetime import timedelta
from io import BytesIO
import os
from random import Random
from secrets import token_urlsafe

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from artworks.extensions import db
from artworks.images import save_bytes
from artworks.models import Artist, PageView, Work, utcnow


PALETTES = (
    ((28, 24, 21), (196, 142, 92), (232, 214, 186), (90, 108, 92)),
    ((18, 32, 48), (214, 186, 140), (120, 86, 70), (240, 236, 228)),
    ((48, 28, 32), (220, 168, 148), (92, 64, 58), (236, 226, 214)),
    ((24, 36, 28), (168, 186, 148), (214, 196, 120), (244, 240, 230)),
)


EXAMPLES = (
    {
        "display_name": "Clara Morel",
        "slug": "clara-morel",
        "email": "clara.morel@galerie.artworksdigital.fr",
        "discipline": "Peinture",
        "location": "Lyon",
        "statement": (
            "Je peins des seuils : la lumière d’un atelier, le silence d’un mur, "
            "ce qui reste quand la figure s’efface. Chaque toile est une salle à elle seule."
        ),
        "works": (
            ("Seuil ochre", "2024", "Huile sur toile", "120 × 90 cm", "Un orange retenu, presque un enduit."),
            ("Mur de midi", "2023", "Huile sur toile", "100 × 80 cm", "La chaleur d’un atelier vide."),
            ("Les deux chaises", "2025", "Huile sur lin", "81 × 65 cm", "Personne n’est assis. L’espace tient."),
            ("Étude pour une fenêtre", "2024", "Huile sur papier", "50 × 40 cm", "Un rectangle de jour."),
        ),
    },
    {
        "display_name": "Malik Benyamin",
        "slug": "malik-benyamin",
        "email": "malik.benyamin@galerie.artworksdigital.fr",
        "discipline": "Photographie",
        "location": "Marseille",
        "statement": (
            "Je photographie le port comme on dessine : plans serrés, matières, halos. "
            "Pas de postcard. Juste le grain de la ville quand elle se tait."
        ),
        "works": (
            ("Quai 14, 6 h 12", "2024", "Tirage pigmentaire", "60 × 40 cm", "La mer n’est qu’une bande claire."),
            ("Câbles", "2023", "Tirage pigmentaire", "50 × 50 cm", "Une écriture horizontale."),
            ("Nuit au Panier", "2025", "Tirage pigmentaire", "70 × 50 cm", "Une fenêtre, puis plus rien."),
        ),
    },
    {
        "display_name": "Atelier Sèvre",
        "slug": "atelier-sevre",
        "email": "sevre@galerie.artworksdigital.fr",
        "discipline": "Céramique",
        "location": "Paris",
        "statement": (
            "Formes utiles, presque. Des pièces qui tiennent dans la main et sur un socle. "
            "L’émail est une lumière posée, jamais un décor."
        ),
        "works": (
            ("Jarre basse", "2024", "Grès émaillé", "H. 28 cm", "Un ventre, une ombre."),
            ("Coupe blanche", "2025", "Porcelaine", "Ø 32 cm", "Le bord est plus important que le fond."),
            ("Trois cylindres", "2023", "Grès", "H. 18 à 41 cm", "Une famille, pas une série."),
        ),
    },
    {
        "display_name": "Noa Eller",
        "slug": "noa-eller",
        "email": "noa.eller@galerie.artworksdigital.fr",
        "discipline": "Dessin",
        "location": "Bruxelles",
        "statement": (
            "Le dessin comme un accrochage : une feuille, un trait, beaucoup d’air. "
            "Je cherche la tension minimale pour qu’une figure tienne."
        ),
        "works": (
            ("Portrait sans siège", "2025", "Fusain sur papier", "70 × 50 cm", "Une présence, presque."),
            ("Main gauche", "2024", "Mine de plomb", "29,7 × 21 cm", "Étude."),
            ("La table", "2023", "Encre", "40 × 30 cm", "Un plateau, une ombre portée."),
            ("Sans titre (série 12)", "2025", "Fusain", "100 × 70 cm", "Le plus grand format. Le moins de traits."),
        ),
    },
)


def _blob(rng: Random, size: int, palette: tuple) -> bytes:
    image = Image.new("RGB", (size, size), palette[0])
    draw = ImageDraw.Draw(image, "RGBA")
    for _ in range(18):
        color = palette[rng.randint(1, len(palette) - 1)] + (rng.randint(70, 180),)
        x0, y0 = rng.randint(-80, size), rng.randint(-80, size)
        x1, y1 = x0 + rng.randint(120, 520), y0 + rng.randint(80, 480)
        kind = rng.choice(("ellipse", "rect", "arc"))
        if kind == "ellipse":
            draw.ellipse((x0, y0, x1, y1), fill=color)
        elif kind == "rect":
            draw.rectangle((x0, y0, x1, y1), fill=color)
        else:
            draw.arc((x0, y0, x1, y1), rng.randint(0, 180), rng.randint(180, 360), fill=color[:3], width=18)
    image = image.filter(ImageFilter.GaussianBlur(radius=1.2))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=84, optimize=True)
    return buffer.getvalue()


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
        for index, spec in enumerate(EXAMPLES):
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
            rng = Random(spec["slug"])
            palette = PALETTES[index % len(PALETTES)]
            artist.cover_path = save_bytes(_blob(rng, 1600, palette))
            for position, work in enumerate(spec["works"]):
                title, year, medium, dimensions, note = work
                image_path = save_bytes(_blob(Random(f"{spec['slug']}-{title}"), 1400, palette))
                db.session.add(
                    Work(
                        artist_id=artist.id,
                        title=title,
                        year=year,
                        medium=medium,
                        dimensions=dimensions,
                        note=note,
                        image_path=image_path,
                        visible=True,
                        position=position,
                    )
                )
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
        rows.append(
            PageView(
                path=path,
                title=title,
                referrer=rng.choice(("", "https://www.google.fr/", "https://instagram.com/", "https://www.bing.com/")),
                source=rng.choice(("direct", "organic", "social", "referral")),
                device=rng.choice(("desktop", "mobile", "tablet")),
                session_id=token_urlsafe(8),
                artist_id=artist.id,
                work_id=work_id,
                is_bot=False,
                created_at=now - timedelta(days=rng.randint(0, 20), hours=rng.randint(0, 23)),
            )
        )
    db.session.add_all(rows)
    db.session.commit()
