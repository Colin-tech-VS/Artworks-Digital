"""Visuels pour les réseaux — composés ici, pas ailleurs.

Mistral écrit le texte et choisit la direction (mise en page, palette).
Ce module transforme cette intention en image réelle, au format que chaque
réseau attend, avec le lettrage du site.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"

SERIF = "CormorantGaramond-Regular.ttf"
SERIF_BOLD = "CormorantGaramond-SemiBold.ttf"
SANS = "Outfit-Light.ttf"
SANS_MEDIUM = "Outfit-Medium.ttf"
SANS_BOLD = "Outfit-SemiBold.ttf"

# Repli si le dossier de polices manque (déploiement partiel, image système).
FALLBACKS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
)

PALETTE = {
    "wall": "#f3efe6",
    "paper": "#faf7f1",
    "ink": "#161412",
    "quiet": "#6f675e",
    "line": "#d8d0c4",
    "bronze": "#5c4634",
}

FORMATS = {
    "square": (1080, 1080),        # Instagram — le format sûr partout
    "portrait": (1080, 1350),      # Instagram — occupe le plus d’écran
    "landscape": (1200, 630),      # Facebook, Open Graph
    "story": (1080, 1920),         # Stories / Reels couverture
}

LAYOUTS = ("gallery", "artwork", "editorial", "quote", "poster")


# ------------------------------------------------------------------ outils


@lru_cache(maxsize=64)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    for candidate in FALLBACKS:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def _rgb(value: str | tuple, default: str = "#161412") -> tuple[int, int, int]:
    if isinstance(value, tuple):
        return value[:3]
    text = (value or "").strip()
    if not text.startswith("#") or len(text) not in (4, 7):
        text = PALETTE.get(text, default)
    text = text.lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return _rgb(default, "#161412")


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * ratio) for x, y in zip(a, b))


def _luminance(color: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _readable_on(background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Encre lisible sur ce fond — le contraste prime sur la palette."""
    return _rgb("#161412") if _luminance(background) > 0.5 else _rgb("#faf7f1")


def _text_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: float = 0.0) -> int:
    if not text:
        return 0
    base = draw.textlength(text, font=font)
    return round(base + tracking * max(len(text) - 1, 0))


def _draw_tracked(draw, xy, text: str, font, fill, tracking: float = 0.0):
    """PIL ne connaît pas l’interlettrage : on pose les signes un par un."""
    if not tracking:
        draw.text(xy, text, font=font, fill=fill)
        return
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_lines(draw, text: str, name: str, max_width: int, max_height: int, start: int, minimum: int = 22):
    """Réduit le corps jusqu’à ce que le titre tienne dans la boîte."""
    size = start
    while size > minimum:
        font = _font(name, size)
        lines = _wrap(draw, text, font, max_width)
        line_height = round(size * 1.12)
        if len(lines) * line_height <= max_height:
            return font, lines, line_height
        size -= 2
    font = _font(name, minimum)
    return font, _wrap(draw, text, font, max_width), round(minimum * 1.12)


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Recadre au centre pour remplir la zone, sans déformer."""
    target_w, target_h = size
    ratio = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (max(round(image.width * ratio), target_w), max(round(image.height * ratio), target_h)),
        Image.LANCZOS,
    )
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(size, Image.LANCZOS)
    return copy


def _shade(size: tuple[int, int], strength: float = 0.82) -> Image.Image:
    """Dégradé sombre par le bas : le texte reste lisible sur toute image."""
    width, height = size
    mask = Image.new("L", (1, height))
    for y in range(height):
        position = y / max(height - 1, 1)
        value = 0 if position < 0.28 else (position - 0.28) / 0.72
        mask.putpixel((0, y), round(255 * strength * value**1.35))
    return mask.resize(size)


def _open_artwork(payload: bytes | None) -> Image.Image | None:
    if not payload:
        return None
    try:
        image = Image.open(BytesIO(payload))
        image.load()
        return image.convert("RGB")
    except Exception:
        return None


def _signature(draw, text: str, xy, color, size: int = 22):
    _draw_tracked(draw, xy, text.upper(), _font(SANS_MEDIUM, size), color, tracking=size * 0.16)


# --------------------------------------------------------------- gabarits


def _layout_gallery(canvas, draw, spec, art, box):
    """L’œuvre au mur : marge de papier généreuse, cartel dessous.

    Le cartel se compose du bas vers le haut — signature, sous-titre, titre,
    surtitre — pour qu’un texte long réduise l’image, jamais l’inverse."""
    width, height = canvas.size
    pad = box["pad"]
    ink = _rgb(spec["palette"]["ink"])
    accent = _rgb(spec["palette"]["accent"])
    quiet = _mix(ink, _rgb(spec["palette"]["bg"]), 0.45)

    gap = round(box["sub"] * 0.6)
    cursor = height - pad
    _signature(draw, spec["signature"], (pad, cursor - box["sign"]), quiet, box["sign"])
    cursor -= box["sign"] + round(box["sign"] * 1.4)

    sub_font = _font(SANS, box["sub"])
    sub_lines = _wrap(draw, spec["subline"], sub_font, width - pad * 2)[:2] if spec["subline"] else []
    sub_height = round(box["sub"] * 1.45)
    cursor -= len(sub_lines) * sub_height

    title_font, title_lines, line_height = _fit_lines(
        draw, spec["headline"], SERIF_BOLD, width - pad * 2, round(height * 0.16), round(box["title"] * 0.62)
    )
    title_lines = title_lines[:3]
    cursor -= len(title_lines) * line_height + gap
    title_top = cursor

    kicker_top = None
    if spec["kicker"]:
        cursor -= round(box["kicker"] * 2.1)
        kicker_top = cursor

    # Ce qui reste au-dessus du cartel revient à l’œuvre.
    frame_box = (width - pad * 2, max(cursor - pad - round(height * 0.045), round(height * 0.25)))
    if art is not None:
        picture = _contain(art, frame_box)
        x = (width - picture.width) // 2
        y = pad + (frame_box[1] - picture.height) // 2
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle(
            (x + 6, y + 10, x + picture.width + 6, y + picture.height + 12), fill=(0, 0, 0, 46)
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
        canvas.paste(picture, (x, y))
        draw.rectangle((x - 1, y - 1, x + picture.width, y + picture.height), outline=_mix(ink, quiet, 0.5), width=2)

    if kicker_top is not None:
        _draw_tracked(draw, (pad, kicker_top), spec["kicker"].upper(), _font(SANS_MEDIUM, box["kicker"]), accent, tracking=box["kicker"] * 0.2)

    y = title_top
    for line in title_lines:
        draw.text((pad, y), line, font=title_font, fill=ink)
        y += line_height
    y += gap
    for line in sub_lines:
        draw.text((pad, y), line, font=sub_font, fill=quiet)
        y += sub_height


def _layout_artwork(canvas, draw, spec, art, box):
    """L’œuvre en plein cadre, texte posé dessus."""
    width, height = canvas.size
    if art is None:
        return _layout_editorial(canvas, draw, spec, art, box)
    pad = box["pad"]
    picture = _cover(art, canvas.size).convert("RGBA")
    dark = Image.new("RGBA", canvas.size, (12, 10, 9, 255))
    picture = Image.composite(dark, picture, _shade(canvas.size))
    canvas.alpha_composite(picture)

    light = _rgb("#faf7f1")
    accent = _rgb(spec["palette"]["accent"])
    if _luminance(accent) < 0.45:
        accent = _mix(accent, light, 0.62)

    title_font, title_lines, line_height = _fit_lines(
        draw, spec["headline"], SERIF_BOLD, width - pad * 2, round(height * 0.26), round(box["title"] * 0.88)
    )
    title_lines = title_lines[:3]
    sub_font = _font(SANS, box["sub"])
    sub_lines = _wrap(draw, spec["subline"], sub_font, width - pad * 2)[:2] if spec["subline"] else []
    sub_height = round(box["sub"] * 1.45)
    kicker_height = round(box["kicker"] * 2.2) if spec["kicker"] else 0
    gap = round(box["sub"] * 0.6)

    block = kicker_height + len(title_lines) * line_height + gap + len(sub_lines) * sub_height
    y = height - pad - box["sign"] - round(box["sign"] * 1.6) - block

    if spec["kicker"]:
        _draw_tracked(draw, (pad, y), spec["kicker"].upper(), _font(SANS_MEDIUM, box["kicker"]), accent, tracking=box["kicker"] * 0.2)
        y += kicker_height

    for line in title_lines:
        draw.text((pad, y), line, font=title_font, fill=light)
        y += line_height
    y += gap
    for line in sub_lines:
        draw.text((pad, y), line, font=sub_font, fill=_mix(light, (0, 0, 0), 0.22))
        y += sub_height

    _signature(draw, spec["signature"], (pad, height - pad - box["sign"]), _mix(light, (0, 0, 0), 0.3), box["sign"])


def _layout_editorial(canvas, draw, spec, art, box):
    """Papier, filet fin, titre centré — la mise en page du site."""
    width, height = canvas.size
    pad = box["pad"]
    ink = _rgb(spec["palette"]["ink"])
    accent = _rgb(spec["palette"]["accent"])
    quiet = _mix(ink, _rgb(spec["palette"]["bg"]), 0.42)

    inset = round(pad * 0.55)
    draw.rectangle((inset, inset, width - inset, height - inset), outline=_mix(accent, _rgb(spec["palette"]["bg"]), 0.55), width=2)

    font, lines, line_height = _fit_lines(
        draw, spec["headline"], SERIF_BOLD, width - pad * 2.4, round(height * 0.34), round(box["title"] * 1.1)
    )
    sub = _font(SANS, box["sub"])
    sub_lines = _wrap(draw, spec["subline"], sub, round(width - pad * 3)) [:3] if spec["subline"] else []

    block = len(lines) * line_height + (round(box["sub"] * 1.6) * len(sub_lines)) + (round(box["kicker"] * 3) if spec["kicker"] else 0)
    y = (height - block) // 2

    if spec["kicker"]:
        text = spec["kicker"].upper()
        kick = _font(SANS_MEDIUM, box["kicker"])
        tracking = box["kicker"] * 0.22
        _draw_tracked(draw, ((width - _text_width(draw, text, kick, tracking)) // 2, y), text, kick, accent, tracking=tracking)
        y += round(box["kicker"] * 3)

    for line in lines:
        draw.text(((width - draw.textlength(line, font=font)) // 2, y), line, font=font, fill=ink)
        y += line_height

    if sub_lines:
        rule = round(width * 0.07)
        y += round(box["sub"] * 0.7)
        draw.line(((width - rule) // 2, y, (width + rule) // 2, y), fill=_mix(accent, _rgb(spec["palette"]["bg"]), 0.4), width=2)
        y += round(box["sub"] * 0.9)
        for line in sub_lines:
            draw.text(((width - draw.textlength(line, font=sub)) // 2, y), line, font=sub, fill=quiet)
            y += round(box["sub"] * 1.6)

    text = spec["signature"].upper()
    sign = _font(SANS_MEDIUM, box["sign"])
    tracking = box["sign"] * 0.16
    _draw_tracked(draw, ((width - _text_width(draw, text, sign, tracking)) // 2, height - pad - box["sign"]), text, sign, quiet, tracking=tracking)


def _layout_quote(canvas, draw, spec, art, box):
    """Une phrase, une barre d’accent. Rien d’autre."""
    width, height = canvas.size
    pad = box["pad"]
    ink = _rgb(spec["palette"]["ink"])
    accent = _rgb(spec["palette"]["accent"])
    quiet = _mix(ink, _rgb(spec["palette"]["bg"]), 0.42)

    bar_x = pad
    text_x = pad + round(width * 0.055)
    font, lines, line_height = _fit_lines(
        draw, f"« {spec['headline']} »", SERIF, width - text_x - pad, round(height * 0.46), round(box["title"] * 1.15)
    )
    block = len(lines) * line_height
    y = (height - block) // 2
    draw.rectangle((bar_x, y, bar_x + round(width * 0.008), y + block), fill=accent)

    for line in lines:
        draw.text((text_x, y), line, font=font, fill=ink)
        y += line_height

    if spec["subline"]:
        sub = _font(SANS, box["sub"])
        y += round(box["sub"] * 0.9)
        for line in _wrap(draw, spec["subline"], sub, width - text_x - pad)[:2]:
            draw.text((text_x, y), line, font=sub, fill=quiet)
            y += round(box["sub"] * 1.5)

    _signature(draw, spec["signature"], (text_x, height - pad - box["sign"]), quiet, box["sign"])


def _layout_poster(canvas, draw, spec, art, box):
    """Un aplat de couleur, un titre dedans. Le plus graphique des cinq."""
    width, height = canvas.size
    pad = box["pad"]
    accent = _rgb(spec["palette"]["accent"])
    background = _rgb(spec["palette"]["bg"])
    ink = _rgb(spec["palette"]["ink"])
    on_accent = _readable_on(accent)

    band = round(height * 0.62)
    draw.rectangle((0, 0, width, band), fill=accent)

    if art is not None:
        thumb = _cover(art, (width, band))
        veil = Image.new("RGBA", (width, band), accent + (150,))
        thumb = Image.alpha_composite(thumb.convert("RGBA"), veil)
        canvas.alpha_composite(thumb, (0, 0))

    y = pad
    if spec["kicker"]:
        _draw_tracked(draw, (pad, y), spec["kicker"].upper(), _font(SANS_MEDIUM, box["kicker"]), _mix(on_accent, accent, 0.25), tracking=box["kicker"] * 0.2)

    font, lines, line_height = _fit_lines(
        draw, spec["headline"], SERIF_BOLD, width - pad * 2, band - pad * 2 - round(box["kicker"] * 2.4), round(box["title"] * 1.25)
    )
    y = band - pad - len(lines) * line_height
    for line in lines:
        draw.text((pad, y), line, font=font, fill=on_accent)
        y += line_height

    y = band + round(pad * 0.9)
    if spec["subline"]:
        sub = _font(SANS, box["sub"])
        for line in _wrap(draw, spec["subline"], sub, width - pad * 2)[:3]:
            draw.text((pad, y), line, font=sub, fill=_mix(ink, background, 0.25))
            y += round(box["sub"] * 1.55)

    _signature(draw, spec["signature"], (pad, height - pad - box["sign"]), _mix(ink, background, 0.45), box["sign"])


RENDERERS = {
    "gallery": _layout_gallery,
    "artwork": _layout_artwork,
    "editorial": _layout_editorial,
    "quote": _layout_quote,
    "poster": _layout_poster,
}


# ------------------------------------------------------------------ entrée


def normalize_spec(raw: dict | None, *, fallback_headline: str = "Artworksdigital") -> dict:
    """Un brief venu de l’IA est du texte : on le ramène à des valeurs sûres."""
    raw = raw if isinstance(raw, dict) else {}
    palette = raw.get("palette") if isinstance(raw.get("palette"), dict) else {}
    layout = str(raw.get("layout") or "").strip().lower()
    if layout not in LAYOUTS:
        layout = "gallery"
    headline = str(raw.get("headline") or "").strip() or fallback_headline
    return {
        "layout": layout,
        "headline": headline[:120],
        "subline": str(raw.get("subline") or "").strip()[:180],
        "kicker": str(raw.get("kicker") or "").strip()[:40],
        "signature": str(raw.get("signature") or "artworksdigital.fr").strip()[:60],
        "palette": {
            "bg": _hex(palette.get("bg"), PALETTE["wall"]),
            "ink": _hex(palette.get("ink"), PALETTE["ink"]),
            "accent": _hex(palette.get("accent"), PALETTE["bronze"]),
        },
    }


def _hex(value, default: str) -> str:
    text = str(value or "").strip()
    if text.startswith("#") and len(text) in (4, 7):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return default


def render_card(spec: dict, *, fmt: str = "square", artwork: bytes | None = None) -> bytes:
    """Rend le visuel et retourne un JPEG prêt à publier."""
    spec = normalize_spec(spec)
    size = FORMATS.get(fmt, FORMATS["square"])
    width, height = size
    scale = min(width, height) / 1080

    box = {
        "pad": max(round(72 * scale), 34),
        "title": max(round(96 * scale), 34),
        "sub": max(round(31 * scale), 15),
        "kicker": max(round(22 * scale), 11),
        "sign": max(round(21 * scale), 11),
    }

    canvas = Image.new("RGBA", size, _rgb(spec["palette"]["bg"]) + (255,))
    draw = ImageDraw.Draw(canvas)
    art = _open_artwork(artwork)

    RENDERERS[spec["layout"]](canvas, draw, spec, art, box)

    buffer = BytesIO()
    canvas.convert("RGB").save(buffer, format="JPEG", quality=92, optimize=True, progressive=True)
    return buffer.getvalue()
