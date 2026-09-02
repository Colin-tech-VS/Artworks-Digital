from datetime import datetime, timedelta, timezone
from hashlib import sha1
from urllib.parse import urlparse

from flask import Request, request
from sqlalchemy import func

from artworks.extensions import db
from artworks.models import PageView, utcnow

BOT_MARKERS = (
    "bot", "crawl", "spider", "slurp", "bingpreview", "facebookexternalhit",
    "embedly", "quora", "pinterest", "redditbot", "applebot", "semrush",
    "ahrefs", "duckduck", "yandex", "baidu", "httpie", "curl/", "wget",
)


def _device(ua: str) -> str:
    text = ua.lower()
    if "ipad" in text or ("android" in text and "mobile" not in text):
        return "tablet"
    if "mobi" in text or "iphone" in text or "android" in text:
        return "mobile"
    return "desktop"


def _is_bot(ua: str) -> bool:
    text = ua.lower()
    return any(marker in text for marker in BOT_MARKERS)


def _source(referrer: str, host: str) -> str:
    if not referrer:
        return "direct"
    try:
        netloc = urlparse(referrer).netloc.lower().replace("www.", "")
    except Exception:
        return "referral"
    if not netloc or netloc == host.replace("www.", ""):
        return "direct"
    social = ("instagram.", "facebook.", "fb.", "twitter.", "x.com", "linkedin.", "pinterest.", "tiktok.")
    if any(netloc.endswith(name) or name in netloc for name in social):
        return "social"
    search = ("google.", "bing.", "duckduckgo.", "yahoo.", "qwant.", "ecosia.")
    if any(name in netloc for name in search):
        return "organic"
    return "referral"


def session_id_from(req: Request) -> str:
    sid = req.cookies.get("aw_sid")
    if sid and len(sid) <= 40:
        return sid
    seed = f"{req.remote_addr}|{req.headers.get('User-Agent', '')}|{utcnow().timestamp()}"
    return sha1(seed.encode("utf-8")).hexdigest()[:24]


def should_track(req: Request) -> bool:
    if req.method != "GET":
        return False
    endpoint = req.endpoint or ""
    if endpoint in ("static", "media", "public.sitemap", "public.robots") or endpoint.startswith("atelier.") or endpoint.startswith("admin.") or endpoint.startswith("billing."):
        return False
    if req.path.startswith("/static") or req.path.startswith("/media"):
        return False
    return True


def record_view(req: Request, title: str = "", artist_id: int | None = None, work_id: int | None = None) -> str:
    ua = req.headers.get("User-Agent", "")
    referrer = (req.headers.get("Referer") or "")[:400]
    host = (req.host or "").split(":")[0].lower()
    sid = session_id_from(req)
    view = PageView(
        path=(req.path or "/")[:300],
        title=(title or "")[:200],
        referrer=referrer,
        source=_source(referrer, host),
        device=_device(ua),
        session_id=sid,
        artist_id=artist_id,
        work_id=work_id,
        is_bot=_is_bot(ua),
    )
    db.session.add(view)
    db.session.commit()
    return sid


def attach_session_cookie(response, sid: str):
    if request.cookies.get("aw_sid") == sid:
        return response
    response.set_cookie(
        "aw_sid",
        sid,
        max_age=60 * 60 * 24 * 180,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )
    return response


def since(days: int) -> datetime:
    return utcnow() - timedelta(days=days)


def public_filter():
    return PageView.is_bot.is_(False)


def series(days: int = 28) -> list[dict]:
    start = since(days)
    rows = (
        db.session.query(
            func.date(PageView.created_at).label("day"),
            func.count(PageView.id),
            func.count(func.distinct(PageView.session_id)),
        )
        .filter(PageView.created_at >= start, public_filter())
        .group_by(func.date(PageView.created_at))
        .all()
    )
    mapped = {str(day): (views, users) for day, views, users in rows}
    out = []
    for offset in range(days, -1, -1):
        day = (utcnow() - timedelta(days=offset)).date().isoformat()
        views, users = mapped.get(day, (0, 0))
        out.append({"day": day, "views": int(views or 0), "users": int(users or 0)})
    return out


def kpis(days: int = 28) -> dict:
    start = since(days)
    q = PageView.query.filter(PageView.created_at >= start, public_filter())
    views = q.count()
    users = q.with_entities(func.count(func.distinct(PageView.session_id))).scalar() or 0
    sessions = users
    pages_per = round(views / users, 2) if users else 0
    prev_start = since(days * 2)
    prev = PageView.query.filter(
        PageView.created_at >= prev_start,
        PageView.created_at < start,
        public_filter(),
    )
    prev_views = prev.count()
    prev_users = prev.with_entities(func.count(func.distinct(PageView.session_id))).scalar() or 0
    return {
        "views": views,
        "users": int(users),
        "sessions": int(sessions),
        "pages_per_session": pages_per,
        "views_delta": _delta(views, prev_views),
        "users_delta": _delta(users, prev_users),
    }


def _delta(current: int, previous: int) -> int:
    if previous == 0:
        return 100 if current else 0
    return round(((current - previous) / previous) * 100)


def breakdown(column, days: int = 28, limit: int = 8):
    start = since(days)
    rows = (
        db.session.query(column, func.count(PageView.id))
        .filter(PageView.created_at >= start, public_filter())
        .group_by(column)
        .order_by(func.count(PageView.id).desc())
        .limit(limit)
        .all()
    )
    return [{"label": (label or "—"), "value": int(count)} for label, count in rows]


def top_paths(days: int = 28, limit: int = 10):
    start = since(days)
    rows = (
        db.session.query(PageView.path, PageView.title, func.count(PageView.id))
        .filter(PageView.created_at >= start, public_filter())
        .group_by(PageView.path, PageView.title)
        .order_by(func.count(PageView.id).desc())
        .limit(limit)
        .all()
    )
    return [{"path": path, "title": title or path, "value": int(count)} for path, title, count in rows]


def artist_series(artist_id: int, days: int = 14) -> list[int]:
    start = since(days)
    rows = (
        db.session.query(func.date(PageView.created_at), func.count(PageView.id))
        .filter(PageView.artist_id == artist_id, PageView.created_at >= start, public_filter())
        .group_by(func.date(PageView.created_at))
        .all()
    )
    mapped = {str(day): int(count) for day, count in rows}
    values = []
    for offset in range(days, -1, -1):
        day = (utcnow() - timedelta(days=offset)).date().isoformat()
        values.append(mapped.get(day, 0))
    return values


def sparkline_svg(values: list[int], width: int = 220, height: int = 56) -> str:
    if not values:
        return ""
    peak = max(values) or 1
    step = width / max(len(values) - 1, 1)
    points = " ".join(
        f"{index * step:.1f},{height - (value / peak) * (height - 4) - 2:.1f}"
        for index, value in enumerate(values)
    )
    fill = f"0,{height} {points} {width},{height}"
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true">'
        f'<polygon points="{fill}" fill="rgba(92,70,52,0.12)"></polygon>'
        f'<polyline points="{points}" fill="none" stroke="#5c4634" stroke-width="2"></polyline>'
        f"</svg>"
    )
