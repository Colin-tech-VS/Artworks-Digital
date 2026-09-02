import os
from datetime import timedelta

from sqlalchemy import inspect, text

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
    CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "www.artworksdigital.fr")
    CANONICAL_SCHEME = os.environ.get("CANONICAL_SCHEME", "https")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "Artworksdigital <hello@artworksdigital.fr>")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") != "0"


def _add_column(table: str, column: str, ddl: str) -> None:
    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns(table)}
    if column in columns:
        return
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    db.session.commit()


def ensure_schema() -> None:
    db.create_all()
    is_pg = db.engine.dialect.name == "postgresql"
    bool_false = "BOOLEAN DEFAULT FALSE" if is_pg else "BOOLEAN DEFAULT 0"
    dt_type = "TIMESTAMP" if is_pg else "DATETIME"

    _add_column("work", "view_count", "INTEGER DEFAULT 0")
    _add_column("work", "updated_at", dt_type)
    _add_column("artist", "is_admin", bool_false)
    _add_column("artist", "is_example", bool_false)
    _add_column("artist", "updated_at", dt_type)
    try:
        db.session.execute(text("UPDATE artist SET updated_at = created_at WHERE updated_at IS NULL"))
        db.session.execute(text("UPDATE work SET updated_at = created_at WHERE updated_at IS NULL"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    from artworks.seed import promote_admins, seed_examples

    promote_admins()
    seed_examples()
