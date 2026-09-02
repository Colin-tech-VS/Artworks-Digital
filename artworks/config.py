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


def ensure_schema() -> None:
    db.create_all()
    inspector = inspect(db.engine)
    if "work" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("work")}
    if "view_count" not in columns:
        db.session.execute(text("ALTER TABLE work ADD COLUMN view_count INTEGER DEFAULT 0"))
        db.session.commit()
