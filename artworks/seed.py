import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import or_

from artworks.extensions import db
from artworks.images import remove_image
from artworks.models import (
    Artist,
    KaelAuditLog,
    KaelToken,
    MailMessage,
    PageView,
    SocialPost,
    SubscriptionEvent,
    Work,
)


# Les galeries d’exemple portaient toutes cette adresse : elle sert de garde-fou
# au ménage, pour qu’aucune salle d’artiste réel ne soit emportée par erreur.
EXAMPLE_DOMAIN = "@galerie.artworksdigital.fr"
TEST_DOMAINS = {"example.com", "example.net", "example.org", "artworks.test", "test.local"}
TEST_LABEL = re.compile(r"test", re.IGNORECASE)


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


def purge_examples() -> int:
    """Retire les galeries de démonstration et tout ce qui s’y rattache.

    Le site n’affiche plus de vitrine fabriquée : seules les salles d’artistes
    réels s’ouvrent. Le ménage tourne à chaque démarrage — il ne coûte rien
    quand il n’y a rien à retirer, et il nettoie les bases déjà semées, sur
    Scalingo comme en local.

    Le journal de K.A.E.L. est conservé : ses lignes perdent leur jeton, pas
    leur trace. Rend le nombre de salles retirées."""
    artists = Artist.query.filter(
        Artist.is_example.is_(True),
        Artist.email.like(f"%{EXAMPLE_DOMAIN}"),
    ).all()
    if not artists:
        return 0

    artist_ids = [artist.id for artist in artists]
    works = Work.query.filter(Work.artist_id.in_(artist_ids)).all()
    work_ids = [work.id for work in works]
    visuals = {artist.cover_path for artist in artists}
    visuals.update(work.image_path for work in works)
    visuals.discard(None)
    visuals.discard("")

    def _touching(model):
        """Les lignes qui pointent vers ces salles, directement ou par une œuvre."""
        clauses = [model.artist_id.in_(artist_ids)]
        if work_ids and hasattr(model, "work_id"):
            clauses.append(model.work_id.in_(work_ids))
        return or_(*clauses)

    try:
        PageView.query.filter(_touching(PageView)).delete(synchronize_session=False)
        SocialPost.query.filter(_touching(SocialPost)).delete(synchronize_session=False)
        MailMessage.query.filter(_touching(MailMessage)).delete(synchronize_session=False)
        SubscriptionEvent.query.filter(_touching(SubscriptionEvent)).delete(synchronize_session=False)

        token_ids = [
            row.id for row in KaelToken.query.filter(KaelToken.artist_id.in_(artist_ids)).all()
        ]
        if token_ids:
            KaelAuditLog.query.filter(KaelAuditLog.token_id.in_(token_ids)).update(
                {KaelAuditLog.token_id: None}, synchronize_session=False
            )
            KaelToken.query.filter(KaelToken.id.in_(token_ids)).delete(synchronize_session=False)

        Work.query.filter(Work.artist_id.in_(artist_ids)).delete(synchronize_session=False)
        Artist.query.filter(Artist.id.in_(artist_ids)).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return 0

    # Les visuels ne partent qu’une fois les lignes tombées : si le ménage
    # échoue, les salles restent entières plutôt qu’amputées de leurs images.
    for name in visuals:
        try:
            remove_image(name)
        except Exception:
            db.session.rollback()
    db.session.commit()
    return len(artist_ids)


def is_test_account(artist: Artist) -> bool:
    """Comptes de chantier : exemples, domaines factices, ou le mot « test »
    dans le nom ou l’adresse. Un vrai artiste n’y entre pas."""
    if artist.is_example:
        return True
    email = (artist.email or "").strip().lower()
    domain = email.split("@")[-1] if "@" in email else ""
    if domain in TEST_DOMAINS or domain.endswith(".test"):
        return True
    name = artist.display_name or ""
    slug = artist.slug or ""
    return bool(TEST_LABEL.search(name) or TEST_LABEL.search(slug))


def delete_artists(artists: list[Artist]) -> int:
    if not artists:
        return 0
    artist_ids = [artist.id for artist in artists]
    works = Work.query.filter(Work.artist_id.in_(artist_ids)).all()
    work_ids = [work.id for work in works]
    visuals = {artist.cover_path for artist in artists}
    visuals.update(work.image_path for work in works)
    visuals.discard(None)
    visuals.discard("")

    def _touching(model):
        clauses = [model.artist_id.in_(artist_ids)]
        if work_ids and hasattr(model, "work_id"):
            clauses.append(model.work_id.in_(work_ids))
        return or_(*clauses)

    PageView.query.filter(_touching(PageView)).delete(synchronize_session=False)
    SocialPost.query.filter(_touching(SocialPost)).delete(synchronize_session=False)
    MailMessage.query.filter(_touching(MailMessage)).delete(synchronize_session=False)
    SubscriptionEvent.query.filter(_touching(SubscriptionEvent)).delete(synchronize_session=False)
    token_ids = [row.id for row in KaelToken.query.filter(KaelToken.artist_id.in_(artist_ids)).all()]
    if token_ids:
        KaelAuditLog.query.filter(KaelAuditLog.token_id.in_(token_ids)).update(
            {KaelAuditLog.token_id: None}, synchronize_session=False
        )
        KaelToken.query.filter(KaelToken.id.in_(token_ids)).delete(synchronize_session=False)
    Work.query.filter(Work.artist_id.in_(artist_ids)).delete(synchronize_session=False)
    Artist.query.filter(Artist.id.in_(artist_ids)).delete(synchronize_session=False)
    db.session.commit()
    for name in visuals:
        try:
            remove_image(name)
        except Exception:
            db.session.rollback()
    db.session.commit()
    return len(artist_ids)


def purge_test_accounts() -> int:
    """Retire les ateliers de test — Famille Cayre Test, testplan, example.com.

    Tourne au démarrage comme le ménage des exemples : une base déjà semée
    se nettoie toute seule, sans emporter une salle réelle."""
    found = [artist for artist in Artist.query.all() if is_test_account(artist)]
    if not found:
        return 0
    try:
        return delete_artists(found)
    except Exception:
        db.session.rollback()
        return 0
