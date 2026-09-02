import os
import time
from datetime import timedelta

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from artworks.extensions import db


def database_uri() -> str:
    uri = os.environ.get("DATABASE_URL", "sqlite:///artworks.db")
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return uri


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-artworks-digital")
    SITE_UNLOCK_PASSWORD = os.environ.get("SITE_UNLOCK_PASSWORD", "")
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
    SEND_FILE_MAX_AGE_DEFAULT = 60 * 60 * 24 * 365
    CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "www.artworksdigital.fr")
    CANONICAL_REDIRECT = os.environ.get("CANONICAL_REDIRECT", "1") != "0"
    CANONICAL_SCHEME = os.environ.get("CANONICAL_SCHEME", "https")
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "https")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or "465")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "Artworksdigital <contact@artworksdigital.fr>")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "0") == "1"
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "1") != "0"
    MAIL_IMAP_HOST = os.environ.get("MAIL_IMAP_HOST", "")
    MAIL_IMAP_PORT = int(os.environ.get("MAIL_IMAP_PORT") or "993")
    SITE_CONTACT_EMAIL = os.environ.get("SITE_CONTACT_EMAIL", "contact@artworksdigital.fr")
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    FACEBOOK_PAGE_ACCESS_TOKEN = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID", "")
    INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    INSTAGRAM_USER_ID = os.environ.get("INSTAGRAM_USER_ID", "")
    DEVIANTART_CLIENT_ID = os.environ.get("DEVIANTART_CLIENT_ID", "")
    DEVIANTART_CLIENT_SECRET = os.environ.get("DEVIANTART_CLIENT_SECRET", "")
    DEVIANTART_REDIRECT_URI = os.environ.get("DEVIANTART_REDIRECT_URI", "")
    PINTEREST_CLIENT_ID = os.environ.get("PINTEREST_CLIENT_ID", "")
    PINTEREST_CLIENT_SECRET = os.environ.get("PINTEREST_CLIENT_SECRET", "")
    PINTEREST_REDIRECT_URI = os.environ.get("PINTEREST_REDIRECT_URI", "")
    PINTEREST_DEFAULT_BOARD_ID = os.environ.get("PINTEREST_DEFAULT_BOARD_ID", "")
    # K.A.E.L. — le centre de commande. Artworks Digital lui parle, il ne
    # l'héberge pas : l'URL et le jeton restent côté serveur.
    KAEL_API_URL = os.environ.get("KAEL_API_URL", "")
    KAEL_API_TOKEN = os.environ.get("KAEL_API_TOKEN", "")
    KAEL_AGENT = os.environ.get("KAEL_AGENT", "")
    KAEL_ENABLED = os.environ.get("KAEL_ENABLED", "1") != "0"
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
    MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
    MISTRAL_MODEL_HEAVY = os.environ.get("MISTRAL_MODEL_HEAVY", "mistral-large-latest")


def _add_column(table: str, column: str, ddl: str) -> None:
    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns(table)}
    if column in columns:
        return
    try:
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()


def ensure_schema() -> None:
    for _ in range(6):
        try:
            db.create_all()
            break
        except SQLAlchemyError:
            db.session.rollback()
            time.sleep(0.5)
    is_pg = db.engine.dialect.name == "postgresql"
    bool_false = "BOOLEAN DEFAULT FALSE" if is_pg else "BOOLEAN DEFAULT 0"
    dt_type = "TIMESTAMP" if is_pg else "DATETIME"

    _add_column("work", "view_count", "INTEGER DEFAULT 0")
    _add_column("work", "updated_at", dt_type)
    _add_column("artist", "is_admin", bool_false)
    _add_column("artist", "is_example", bool_false)
    _add_column("artist", "updated_at", dt_type)
    _add_column("artist", "plan_key", "VARCHAR(40) DEFAULT 'decouverte'")
    _add_column("artist", "plan_status", "VARCHAR(30) DEFAULT 'active'")
    _add_column("artist", "plan_override", bool_false)
    _add_column("artist", "stripe_customer_id", "VARCHAR(80) DEFAULT ''")
    _add_column("artist", "stripe_subscription_id", "VARCHAR(80) DEFAULT ''")
    _add_column("artist", "plan_period_end", dt_type)
    _add_column("work", "collection_name", "VARCHAR(120) DEFAULT ''")
    _add_column("mail_message", "external_id", "VARCHAR(200) DEFAULT ''")
    _add_column("work", "image_w", "INTEGER DEFAULT 0")
    _add_column("work", "image_h", "INTEGER DEFAULT 0")
    _add_column("social_post", "artist_id", "INTEGER")
    _add_column("social_post", "image_name", "VARCHAR(80) DEFAULT ''")
    _add_column("social_post", "alt_text", "VARCHAR(400) DEFAULT ''")
    _add_column("social_post", "prompt", "TEXT")
    _add_column("social_post", "design_json", "TEXT")
    _add_column("kael_token", "artist_id", "INTEGER")
    _add_column("kael_token", "use_count", "INTEGER DEFAULT 0")
    _add_column("page_view", "referrer_host", "VARCHAR(120) DEFAULT ''")
    _add_column("page_view", "city", "VARCHAR(80) DEFAULT ''")
    _add_column("page_view", "country", "VARCHAR(80) DEFAULT ''")
    _add_column("page_view", "country_code", "VARCHAR(8) DEFAULT ''")
    _add_column("mail_message", "html_body", "TEXT")
    try:
        db.session.execute(text("UPDATE artist SET updated_at = created_at WHERE updated_at IS NULL"))
        db.session.execute(text("UPDATE work SET updated_at = created_at WHERE updated_at IS NULL"))
        db.session.execute(text("UPDATE artist SET plan_key = 'decouverte' WHERE plan_key IS NULL OR plan_key = ''"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    from artworks.plans import seed_offers
    from artworks.seed import seed_examples

    try:
        seed_offers()
        seed_examples()
    except SQLAlchemyError:
        db.session.rollback()

    backfill_image_sizes()


def backfill_image_sizes(limit: int = 200) -> int:
    """Mesure les visuels enregistrés avant que les dimensions soient stockées.

    Sans elles, le gabarit ne peut pas réserver la place de l’image, et
    Open Graph annonce une taille fausse. Par lots, pour ne pas alourdir
    le démarrage."""
    from io import BytesIO

    from PIL import Image

    from artworks.models import Asset, Work

    try:
        rows = Work.query.filter((Work.image_w == 0) | (Work.image_w.is_(None))).limit(limit).all()
    except SQLAlchemyError:
        db.session.rollback()
        return 0

    done = 0
    for work in rows:
        asset = db.session.get(Asset, work.image_path) if work.image_path else None
        if asset is None:
            # Aucun visuel lisible : on marque pour ne pas repasser à chaque démarrage.
            work.image_w, work.image_h = -1, -1
            continue
        try:
            with Image.open(BytesIO(asset.data)) as image:
                work.image_w, work.image_h = image.width, image.height
            done += 1
        except Exception:
            work.image_w, work.image_h = -1, -1
    if rows:
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return 0
    return done
