import os


def database_uri() -> str:
    uri = os.environ.get("DATABASE_URL", "sqlite:///artworks.db")
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return uri


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-artworks-digital")
    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
