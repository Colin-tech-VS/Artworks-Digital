from datetime import datetime, timedelta, timezone
from hashlib import sha1
from ipaddress import ip_address
from urllib.parse import urlparse
import json
import urllib.error
import urllib.request

from flask import Request, request
from sqlalchemy import func

from artworks.extensions import db
from artworks.models import PageView, utcnow

SOURCE_LABELS = {
    "direct": "Direct",
    "organic": "Recherche",
    "social": "Réseaux",
    "referral": "Sites",
    "email": "E-mail",
    "paid": "Payant",
}
DEVICE_LABELS = {
    "desktop": "Ordinateur",
    "mobile": "Mobile",
    "tablet": "Tablette",
}

_GEO_CACHE: dict[str, tuple[float, dict]] = {}
_GEO_TTL = 60 * 60 * 24
_GEO_CACHE_MAX = 2000

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


def _source(referrer: str, host: str, req: Request | None = None) -> str:
    if req is not None:
        medium = (req.args.get("utm_medium") or "").lower()
        utm = (req.args.get("utm_source") or "").lower()
        if medium in {"email", "e-mail", "newsletter", "mail"} or utm in {"newsletter", "email", "mail"}:
            return "email"
        if medium in {"cpc", "ppc", "paid", "ads", "display"} or utm in {"ads", "adwords", "googleads", "metaads"}:
            return "paid"
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


def _referrer_host(referrer: str, host: str) -> str:
    if not referrer:
        return ""
    try:
        netloc = urlparse(referrer).netloc.lower().replace("www.", "")
    except Exception:
        return ""
    if not netloc or netloc == host.replace("www.", ""):
        return ""
    return netloc[:120]


def _client_ip(req: Request) -> str:
    forwarded = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return (req.headers.get("X-Real-IP") or req.remote_addr or "").strip()


def _is_private_ip(raw: str) -> bool:
    try:
        return ip_address(raw).is_private or ip_address(raw).is_loopback or ip_address(raw).is_reserved
    except ValueError:
        return True


def _geo_from_headers(req: Request) -> dict:
    city = (req.headers.get("CF-IPCity") or req.headers.get("X-AppEngine-City") or "").replace("_", " ").strip()
    country_code = (
        req.headers.get("CF-IPCountry")
        or req.headers.get("CloudFront-Viewer-Country")
        or ""
    ).strip().upper()
    if country_code in {"", "XX", "T1"}:
        country_code = ""
    if not city and not country_code:
        return {}
    return {"city": city[:80], "country": "", "country_code": country_code[:8]}


def _geo_lookup(ip: str) -> dict:
    now = utcnow().timestamp()
    cached = _GEO_CACHE.get(ip)
    if cached and now - cached[0] < _GEO_TTL:
        return cached[1]
    place = {"city": "", "country": "", "country_code": ""}
    try:
        url = f"https://ipwho.is/{ip}?fields=success,city,country,country_code"
        with urllib.request.urlopen(url, timeout=0.7) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("success"):
            place = {
                "city": str(data.get("city") or "")[:80],
                "country": str(data.get("country") or "")[:80],
                "country_code": str(data.get("country_code") or "")[:8],
            }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        place = {"city": "", "country": "", "country_code": ""}
    if len(_GEO_CACHE) >= _GEO_CACHE_MAX:
        _GEO_CACHE.pop(next(iter(_GEO_CACHE)))
    _GEO_CACHE[ip] = (now, place)
    return place


def locate(req: Request) -> dict:
    headed = _geo_from_headers(req)
    if headed.get("city"):
        return headed
    ip = _client_ip(req)
    if not ip or _is_private_ip(ip):
        return headed
    looked = _geo_lookup(ip)
    if headed.get("country_code") and not looked.get("country_code"):
        looked["country_code"] = headed["country_code"]
    return looked


def source_label(key: str) -> str:
    return SOURCE_LABELS.get(key or "", key or "Direct")


def device_label(key: str) -> str:
    return DEVICE_LABELS.get(key or "", key or "—")


def place_label(city: str = "", country: str = "") -> str:
    city = (city or "").strip()
    country = (country or "").strip()
    if city and country and country.lower() not in {"france", "france métropolitaine"}:
        return f"{city} · {country}"
    return city or country or "Lieu inconnu"


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
    if endpoint in ("static", "media", "public.sitemap", "public.robots", "public.rooms_feed", "public.opensearch") or endpoint.startswith("atelier.") or endpoint.startswith("admin.") or endpoint.startswith("billing."):
        return False
    if req.path.startswith("/static") or req.path.startswith("/media"):
        return False
    return True


def record_view(req: Request, title: str = "", artist_id: int | None = None, work_id: int | None = None) -> str:
    ua = req.headers.get("User-Agent", "")
    referrer = (req.headers.get("Referer") or "")[:400]
    host = (req.host or "").split(":")[0].lower()
    sid = session_id_from(req)
    place = locate(req) if not _is_bot(ua) else {}
    view = PageView(
        path=(req.path or "/")[:300],
        title=(title or "")[:200],
        referrer=referrer,
        referrer_host=_referrer_host(referrer, host),
        source=_source(referrer, host, req),
        device=_device(ua),
        city=place.get("city") or "",
        country=place.get("country") or "",
        country_code=place.get("country_code") or "",
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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


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


def breakdown(column, days: int = 28, limit: int = 8, hide_empty: bool = False, labels: dict | None = None):
    start = since(days)
    filters = [PageView.created_at >= start, public_filter()]
    if hide_empty:
        filters.extend([column.isnot(None), column != ""])
    rows = (
        db.session.query(column, func.count(PageView.id))
        .filter(*filters)
        .group_by(column)
        .order_by(func.count(PageView.id).desc())
        .limit(limit)
        .all()
    )
    out = []
    for label, count in rows:
        key = label or ""
        shown = (labels or {}).get(key, key) if labels is not None else (key or "—")
        out.append({"key": key, "label": shown or "—", "value": int(count)})
    return out


def city_breakdown(days: int = 28, limit: int = 8) -> list[dict]:
    start = since(days)
    rows = (
        db.session.query(PageView.city, PageView.country, func.count(PageView.id))
        .filter(PageView.created_at >= start, public_filter(), PageView.city != "")
        .group_by(PageView.city, PageView.country)
        .order_by(func.count(PageView.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {"label": place_label(city, country), "value": int(count), "city": city, "country": country}
        for city, country, count in rows
    ]


def live_snapshot(minutes: int = 5, pulse: int = 30, feed: int = 16) -> dict:
    now = utcnow()
    window = now - timedelta(minutes=minutes)
    pulse_start = now - timedelta(minutes=pulse)
    recent = (
        PageView.query.filter(PageView.created_at >= pulse_start, public_filter())
        .order_by(PageView.created_at.desc())
        .limit(500)
        .all()
    )
    active_ids = {
        row.session_id
        for row in recent
        if row.session_id and _as_utc(row.created_at) and _as_utc(row.created_at) >= window
    }
    views_now = sum(1 for row in recent if _as_utc(row.created_at) and _as_utc(row.created_at) >= window)
    buckets = [0] * pulse
    for row in recent:
        stamped = _as_utc(row.created_at)
        if stamped is None:
            continue
        age = int((now - stamped).total_seconds() // 60)
        if 0 <= age < pulse:
            buckets[pulse - 1 - age] += 1
    hits = []
    for row in recent[:feed]:
        stamped = _as_utc(row.created_at)
        hits.append({
            "path": row.path,
            "title": row.title or row.path,
            "city": row.city or "",
            "country": row.country or "",
            "place": place_label(row.city, row.country),
            "source": row.source or "direct",
            "channel": source_label(row.source or "direct"),
            "device": device_label(row.device or "desktop"),
            "at": stamped.isoformat() if stamped else "",
        })
    return {
        "active": len(active_ids),
        "views": views_now,
        "minutes": minutes,
        "pulse": buckets,
        "feed": hits,
    }


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


def artist_breakdown(artist_id: int, column, days: int = 28, limit: int = 8, hide_empty: bool = False, labels: dict | None = None):
    start = since(days)
    filters = [PageView.artist_id == artist_id, PageView.created_at >= start, public_filter()]
    if hide_empty:
        filters.extend([column.isnot(None), column != ""])
    rows = (
        db.session.query(column, func.count(PageView.id))
        .filter(*filters)
        .group_by(column)
        .order_by(func.count(PageView.id).desc())
        .limit(limit)
        .all()
    )
    out = []
    for label, count in rows:
        key = label or ""
        shown = (labels or {}).get(key, key) if labels is not None else (key or "—")
        out.append({"key": key, "label": shown or "—", "value": int(count)})
    return out


def artist_cities(artist_id: int, days: int = 28, limit: int = 8) -> list[dict]:
    start = since(days)
    rows = (
        db.session.query(PageView.city, PageView.country, func.count(PageView.id))
        .filter(
            PageView.artist_id == artist_id,
            PageView.created_at >= start,
            public_filter(),
            PageView.city != "",
        )
        .group_by(PageView.city, PageView.country)
        .order_by(func.count(PageView.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {"label": place_label(city, country), "value": int(count)}
        for city, country, count in rows
    ]


def artist_top_works(artist_id: int, days: int = 28, limit: int = 8) -> list[dict]:
    start = since(days)
    rows = (
        db.session.query(PageView.work_id, PageView.title, func.count(PageView.id))
        .filter(
            PageView.artist_id == artist_id,
            PageView.work_id.isnot(None),
            PageView.created_at >= start,
            public_filter(),
        )
        .group_by(PageView.work_id, PageView.title)
        .order_by(func.count(PageView.id).desc())
        .limit(limit)
        .all()
    )
    return [{"title": title or "Œuvre", "value": int(count)} for _work_id, title, count in rows]


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
