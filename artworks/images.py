from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from artworks.extensions import db
from artworks.models import Asset


def upload_dir() -> Path:
    folder = Path(current_app.instance_path) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_image(file: FileStorage, max_side: int = 2400) -> str:
    filename = secure_filename(file.filename or "")
    suffix = Path(filename).suffix.lower()
    if suffix not in current_app.config["UPLOAD_EXTENSIONS"]:
        raise ValueError("Format d’image non accepté.")

    name = f"{uuid4().hex}{suffix}"
    dest = upload_dir() / name

    image = Image.open(file.stream)
    image = image.convert("RGB") if image.mode not in ("RGB", "L") else image
    image.thumbnail((max_side, max_side))

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    payload = buffer.getvalue()
    dest.write_bytes(payload)

    existing = db.session.get(Asset, name)
    if existing:
        existing.data = payload
        existing.mime = "image/jpeg"
    else:
        db.session.add(Asset(id=name, mime="image/jpeg", data=payload))
    return name


def remove_image(name: str | None) -> None:
    if not name:
        return
    path = upload_dir() / name
    if path.exists():
        path.unlink()
    asset = db.session.get(Asset, name)
    if asset:
        db.session.delete(asset)


def asset_bytes(name: str) -> tuple[bytes, str] | None:
    path = upload_dir() / name
    if path.exists():
        return path.read_bytes(), "image/jpeg"
    asset = db.session.get(Asset, name)
    if asset:
        path.write_bytes(asset.data)
        return asset.data, asset.mime
    return None
