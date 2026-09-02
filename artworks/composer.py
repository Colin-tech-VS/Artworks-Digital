"""Du prompt à la publication.

Une consigne en français entre ici ; il en sort un texte de post, des
hashtags, un visuel au bon format, stocké et servi en HTTPS — c’est-à-dire
tout ce que Facebook et Instagram réclament pour publier vraiment.
"""

from __future__ import annotations

import json

from flask import url_for

from artworks.design import FORMATS, normalize_spec, render_card
from artworks.extensions import db
from artworks.images import asset_bytes, save_bytes
from artworks.mistral import generate_social, mistral_ready
from artworks.models import SocialPost, Work
from artworks.seo import absolute_media, canonical_url

# Chaque réseau a son cadre de prédilection.
PLATFORM_FORMAT = {
    "instagram": "square",
    "facebook": "landscape",
    "pinterest": "portrait",
    "deviantart": "portrait",
}


def default_format(platforms: list[str]) -> str:
    for key in ("instagram", "facebook", "pinterest", "deviantart"):
        if key in platforms:
            return PLATFORM_FORMAT[key]
    return "square"


def work_link(work: Work) -> str:
    return canonical_url(url_for("public.artwork", slug=work.artist.slug, work_id=work.id))


def work_image(work: Work | None) -> bytes | None:
    if work is None or not work.image_path:
        return None
    payload = asset_bytes(work.image_path)
    return payload[0] if payload else None


def fallback_brief(prompt: str, *, work: Work | None, artist_name: str = "") -> dict:
    """Sans Mistral, on compose quand même — le visuel doit rester possible."""
    if work is not None:
        headline = work.title
        subline = " · ".join(filter(None, [work.cartel, artist_name or work.artist.display_name]))
        caption = (
            f"{work.title}"
            + (f" — {work.cartel}" if work.cartel else "")
            + f"\n{artist_name or work.artist.display_name} accroche cette pièce dans sa salle."
        )
        kicker = "Nouvel accrochage"
        layout = "gallery"
    else:
        headline = (prompt or "Artworksdigital").strip()[:110]
        subline = "Chaque artiste ouvre sa galerie."
        caption = (prompt or "").strip()
        kicker = "Artworksdigital"
        layout = "editorial"
    return {
        "caption": caption,
        "hashtags": ["#art", "#galerie", "#artworksdigital"],
        "alt": headline,
        "design": {
            "layout": layout,
            "kicker": kicker,
            "headline": headline,
            "subline": subline,
            "palette": {"bg": "#f3efe6", "ink": "#161412", "accent": "#5c4634"},
        },
    }


def compose(
    prompt: str,
    *,
    platforms: list[str] | None = None,
    work: Work | None = None,
    artist_name: str = "",
    link: str = "",
    fmt: str = "",
    layout: str = "",
    heavy: bool = False,
    use_artwork: bool = True,
) -> dict:
    """Génère texte + visuel. Retourne de quoi prévisualiser puis publier."""
    platforms = platforms or ["instagram"]
    fmt = fmt if fmt in FORMATS else default_format(platforms)
    artwork = work_image(work) if use_artwork else None
    if not link and work is not None:
        link = work_link(work)
    if not artist_name and work is not None:
        artist_name = work.artist.display_name

    warning = ""
    if mistral_ready():
        try:
            brief = generate_social(
                prompt,
                platform=platforms[0],
                artist_name=artist_name,
                work_title=work.title if work else "",
                work_cartel=work.cartel if work else "",
                work_note=(work.note or "") if work else "",
                link=link,
                has_image=artwork is not None,
                heavy=heavy,
            )
        except Exception as exc:
            brief = fallback_brief(prompt, work=work, artist_name=artist_name)
            warning = f"Mistral n’a pas répondu ({exc}). Brouillon composé sans IA."
    else:
        brief = fallback_brief(prompt, work=work, artist_name=artist_name)
        warning = "Clé Mistral absente — brouillon composé sans IA."

    spec = dict(brief.get("design") or {})
    if layout:
        spec["layout"] = layout
    if artwork is None and spec.get("layout") in ("gallery", "artwork"):
        spec["layout"] = "editorial"
    spec.setdefault("signature", link.replace("https://", "").replace("http://", "") or "artworksdigital.fr")
    spec = normalize_spec(spec, fallback_headline=(work.title if work else "Artworksdigital"))

    image_bytes = render_card(spec, fmt=fmt, artwork=artwork)
    name = save_bytes(image_bytes)
    db.session.commit()

    caption = (brief.get("caption") or "").strip()
    hashtags = brief.get("hashtags") or []
    message = caption
    if hashtags:
        message = f"{caption}\n\n{' '.join(hashtags)}".strip()

    return {
        "caption": caption,
        "hashtags": hashtags,
        "message": message,
        "alt": brief.get("alt") or spec["headline"],
        "design": spec,
        "format": fmt,
        "image_name": name,
        "image_url": absolute_media(name),
        "link": link,
        "warning": warning,
        "prompt": prompt,
    }


def log_publication(
    result: dict,
    *,
    platform: str,
    draft: dict,
    work: Work | None,
    artist_id: int | None = None,
) -> SocialPost:
    row = SocialPost(
        platform=platform,
        work_id=work.id if work else None,
        artist_id=artist_id,
        title=draft.get("design", {}).get("headline", "")[:180],
        body=draft.get("message", ""),
        image_url=draft.get("image_url", "")[:400],
        image_name=draft.get("image_name", "")[:80],
        alt_text=draft.get("alt", "")[:400],
        prompt=draft.get("prompt", "")[:1000],
        design_json=json.dumps(draft.get("design") or {}, ensure_ascii=False)[:2000],
        remote_id=str(result.get("id") or "")[:120],
        remote_url=str(result.get("url") or "")[:400],
        status="ok" if result.get("ok") else "error",
        error=str(result.get("error") or "")[:1000],
    )
    db.session.add(row)
    return row
