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


def save_bytes(payload: bytes, mime: str = "image/jpeg") -> str:
    name = f"{uuid4().hex}.jpg"
    dest = upload_dir() / name
    dest.write_bytes(payload)
    existing = db.session.get(Asset, name)
    if existing:
        existing.data = payload
        existing.mime = mime
    else:
        db.session.add(Asset(id=name, mime=mime, data=payload))
    return name


def save_image(file: FileStorage, max_side: int = 2400) -> str:
    return save_image_sized(file, max_side=max_side)[0]


def save_image_sized(file: FileStorage, max_side: int = 2400) -> tuple[str, int, int]:
    """Comme ``save_image``, mais rend aussi les dimensions finales : les gabarits
    peuvent réserver la place de l’image et éviter le saut de mise en page."""
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
    return name, image.width, image.height


def remove_image(name: str | None) -> None:
    if not name:
        return
    folder = upload_dir()
    path = folder / name
    if path.exists():
        path.unlink()
    # Les déclinaisons du visuel partent avec lui : sans cela, le disque
    # garde des vignettes d'œuvres décrochées depuis longtemps.
    for width in VARIANT_WIDTHS:
        variant = folder / variant_key(name, width)
        if variant.exists():
            variant.unlink()
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


# ── Les tailles servies ────────────────────────────────────────────────────
#
# Un visuel est stocké une fois, en grand (2400 px au plus). Le servir tel
# quel dans une vignette de 300 px, c'est faire télécharger un mégaoctet
# pour en afficher trente kilos : la page rame, et les moteurs le mesurent.
#
# Les déclinaisons sont fabriquées à la demande, puis gardées sur le disque
# de l'instance — jamais en base. La base porte l'original, qui doit
# survivre au redémarrage ; une déclinaison se refait en cinquante
# millisecondes et n'a pas à peser sur l'addon Postgres.
VARIANT_WIDTHS = (480, 960, 1600)


def variant_key(name: str, width: int) -> str:
    return f"w{width}__{name}"


def variant_bytes(name: str, width: int) -> tuple[bytes, str] | None:
    """Le visuel `name` réduit à `width` de large, ou None s'il n'existe pas.

    Un original déjà plus étroit que la demande est rendu tel quel : on ne
    grossit jamais une image, cela n'ajoute que du poids."""
    if width not in VARIANT_WIDTHS:
        return None

    cached = upload_dir() / variant_key(name, width)
    if cached.exists():
        return cached.read_bytes(), "image/jpeg"

    original = asset_bytes(name)
    if original is None:
        return None

    try:
        with Image.open(BytesIO(original[0])) as image:
            if image.width <= width:
                return original
            image = image.convert("RGB") if image.mode not in ("RGB", "L") else image
            image.thumbnail((width, width * 4), Image.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=82, optimize=True, progressive=True)
    except Exception:
        # Un visuel illisible reste servi tel quel plutôt que de rendre 404 :
        # une image moche vaut mieux qu'un trou dans l'accrochage.
        return original

    payload = buffer.getvalue()
    try:
        cached.write_bytes(payload)
    except OSError:
        pass
    return payload, "image/jpeg"
