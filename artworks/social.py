import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import current_app, url_for

from artworks.extensions import db
from artworks.models import SocialToken, utcnow


GRAPH = "https://graph.facebook.com/v19.0"


def _cfg(name: str) -> str:
    return (current_app.config.get(name) or "").strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_form(url: str, params: dict, headers: dict | None = None) -> dict:
    body = urllib.parse.urlencode(params).encode("utf-8")
    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    merged.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=merged)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": raw[:400]}


def _post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json"}
    merged.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=merged)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": raw[:400]}


def token_row(platform: str) -> SocialToken | None:
    return db.session.get(SocialToken, platform)


def save_token(platform: str, access: str, refresh: str = "", expires_in: int = 0, username: str = "", account_id: str = "", scopes: str = "") -> None:
    row = token_row(platform) or SocialToken(platform=platform)
    row.access_token = access
    if refresh:
        row.refresh_token = refresh
    if expires_in:
        row.token_expires_at = _now() + timedelta(seconds=max(expires_in - 60, 60))
    if username:
        row.account_username = username
    if account_id:
        row.account_id = account_id
    if scopes:
        row.scopes = scopes
    row.updated_at = utcnow()
    db.session.add(row)
    db.session.commit()


def delete_token(platform: str) -> None:
    row = token_row(platform)
    if row:
        db.session.delete(row)
        db.session.commit()


class Facebook:
    @classmethod
    def configured(cls) -> bool:
        return bool(_cfg("FACEBOOK_PAGE_ACCESS_TOKEN") and _cfg("FACEBOOK_PAGE_ID"))

    @classmethod
    def status(cls) -> dict:
        if not cls.configured():
            return {"configured": False, "connected": False}
        try:
            data = _get_json(
                f"{GRAPH}/{_cfg('FACEBOOK_PAGE_ID')}?fields=name,fan_count&access_token={_cfg('FACEBOOK_PAGE_ACCESS_TOKEN')}"
            )
            return {"configured": True, "connected": True, "name": data.get("name"), "fans": data.get("fan_count")}
        except Exception as exc:
            return {"configured": True, "connected": False, "error": str(exc)[:180]}

    @classmethod
    def publish(cls, message: str, image_url: str = "", link: str = "") -> dict:
        if not cls.configured():
            return {"ok": False, "error": "Facebook non configuré"}
        token = _cfg("FACEBOOK_PAGE_ACCESS_TOKEN")
        page = _cfg("FACEBOOK_PAGE_ID")
        if image_url:
            res = _post_form(f"{GRAPH}/{page}/photos", {"url": image_url, "caption": message, "access_token": token})
        else:
            params = {"message": message, "access_token": token}
            if link:
                params["link"] = link
            res = _post_form(f"{GRAPH}/{page}/feed", params)
        if res.get("error"):
            return {"ok": False, "error": str(res.get("error"))[:300]}
        return {"ok": True, "id": str(res.get("post_id") or res.get("id") or ""), "url": ""}


class Instagram:
    @classmethod
    def configured(cls) -> bool:
        return bool((_cfg("INSTAGRAM_ACCESS_TOKEN") or _cfg("FACEBOOK_PAGE_ACCESS_TOKEN")) and _cfg("INSTAGRAM_USER_ID"))

    @classmethod
    def token(cls) -> str:
        return _cfg("INSTAGRAM_ACCESS_TOKEN") or _cfg("FACEBOOK_PAGE_ACCESS_TOKEN")

    @classmethod
    def status(cls) -> dict:
        if not cls.configured():
            return {"configured": False, "connected": False}
        try:
            data = _get_json(
                f"{GRAPH}/{_cfg('INSTAGRAM_USER_ID')}?fields=username,name,followers_count&access_token={cls.token()}"
            )
            return {"configured": True, "connected": True, "name": data.get("username") or data.get("name")}
        except Exception as exc:
            return {"configured": True, "connected": False, "error": str(exc)[:180]}

    @classmethod
    def publish(cls, message: str, image_url: str = "", link: str = "") -> dict:
        if not cls.configured():
            return {"ok": False, "error": "Instagram non configuré"}
        if not image_url or not image_url.startswith("https://"):
            return {"ok": False, "error": "Instagram exige une image HTTPS publique"}
        caption = message[:2200]
        if link and link not in caption:
            caption = f"{caption}\n{link}"[:2200]
        created = _post_form(
            f"{GRAPH}/{_cfg('INSTAGRAM_USER_ID')}/media",
            {"image_url": image_url, "caption": caption, "access_token": cls.token()},
        )
        creation_id = created.get("id")
        if not creation_id:
            return {"ok": False, "error": str(created.get("error") or created)[:300]}
        published = _post_form(
            f"{GRAPH}/{_cfg('INSTAGRAM_USER_ID')}/media_publish",
            {"creation_id": creation_id, "access_token": cls.token()},
        )
        if published.get("error"):
            return {"ok": False, "error": str(published.get("error"))[:300]}
        return {"ok": True, "id": str(published.get("id") or ""), "url": ""}


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class DeviantArt:
    AUTH = "https://www.deviantart.com/oauth2/authorize"
    TOKEN = "https://www.deviantart.com/oauth2/token"
    API = "https://www.deviantart.com/api/v1/oauth2"
    SCOPES = "basic browse stash gallery"

    @classmethod
    def redirect_uri(cls) -> str:
        return _cfg("DEVIANTART_REDIRECT_URI") or url_for("admin.social_oauth_callback", platform="deviantart", _external=True)

    @classmethod
    def configured(cls) -> bool:
        return bool(_cfg("DEVIANTART_CLIENT_ID") and _cfg("DEVIANTART_CLIENT_SECRET"))

    @classmethod
    def connected(cls) -> bool:
        return token_row("deviantart") is not None

    @classmethod
    def authorize_url(cls) -> tuple[str, str, str]:
        state = secrets.token_urlsafe(16)
        verifier, challenge = _pkce()
        params = urllib.parse.urlencode(
            {
                "client_id": _cfg("DEVIANTART_CLIENT_ID"),
                "redirect_uri": cls.redirect_uri(),
                "scope": cls.SCOPES,
                "response_type": "code",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{cls.AUTH}?{params}", state, verifier

    @classmethod
    def exchange(cls, code: str, verifier: str) -> None:
        data = _post_form(
            cls.TOKEN,
            {
                "client_id": _cfg("DEVIANTART_CLIENT_ID"),
                "client_secret": _cfg("DEVIANTART_CLIENT_SECRET"),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cls.redirect_uri(),
                "code_verifier": verifier,
            },
        )
        if not data.get("access_token"):
            raise RuntimeError(str(data.get("error_description") or data.get("error") or data)[:200])
        username = ""
        try:
            who = _get_json(f"{cls.API}/user/whoami?access_token={data['access_token']}")
            username = who.get("username") or ""
        except Exception:
            pass
        save_token("deviantart", data["access_token"], data.get("refresh_token") or "", int(data.get("expires_in") or 3600), username, scopes=cls.SCOPES)

    @classmethod
    def access(cls) -> str:
        row = token_row("deviantart")
        if not row:
            return ""
        if row.token_expires_at and row.refresh_token:
            exp = row.token_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp - _now() < timedelta(minutes=5):
                data = _post_form(
                    cls.TOKEN,
                    {
                        "client_id": _cfg("DEVIANTART_CLIENT_ID"),
                        "client_secret": _cfg("DEVIANTART_CLIENT_SECRET"),
                        "grant_type": "refresh_token",
                        "refresh_token": row.refresh_token,
                    },
                )
                if data.get("access_token"):
                    save_token("deviantart", data["access_token"], data.get("refresh_token") or row.refresh_token, int(data.get("expires_in") or 3600), row.account_username)
                    return data["access_token"]
        return row.access_token

    @classmethod
    def status(cls) -> dict:
        row = token_row("deviantart")
        return {"configured": cls.configured(), "connected": bool(row), "name": (row.account_username if row else "")}

    @classmethod
    def publish(cls, message: str, image_url: str = "", link: str = "", title: str = "") -> dict:
        token = cls.access()
        if not token:
            return {"ok": False, "error": "DeviantArt non connecté"}
        if not image_url:
            return {"ok": False, "error": "Image requise"}
        try:
            img = urllib.request.urlopen(image_url, timeout=30).read()
        except Exception as exc:
            return {"ok": False, "error": f"Image illisible : {exc}"[:200]}
        boundary = "----artworks" + secrets.token_hex(8)
        chunks: list[bytes] = []

        def field(name: str, value: str) -> None:
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
            )

        field("title", (title or message or "Artworksdigital")[:50])
        field("artist_description", (message + (f"\n{link}" if link else ""))[:500])
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"art.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode("utf-8")
        )
        chunks.append(img)
        chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        req = urllib.request.Request(
            f"{cls.API}/stash/submit?access_token={token}",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                stash = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": exc.read().decode("utf-8", "replace")[:300]}
        itemid = stash.get("itemid")
        if not itemid:
            return {"ok": False, "error": str(stash)[:300]}
        pub = _post_form(
            f"{cls.API}/stash/publish?access_token={token}",
            {"itemid": itemid, "is_mature": "false", "agree_submission": "true", "agree_tos": "true"},
        )
        return {"ok": True, "id": str(pub.get("deviationid") or ""), "url": pub.get("url") or ""}


class Pinterest:
    AUTH = "https://www.pinterest.com/oauth/"
    TOKEN = "https://api.pinterest.com/v5/oauth/token"
    API = "https://api.pinterest.com/v5"
    SCOPES = "user_accounts:read,boards:read,boards:write,pins:read,pins:write"

    @classmethod
    def redirect_uri(cls) -> str:
        return _cfg("PINTEREST_REDIRECT_URI") or url_for("admin.social_oauth_callback", platform="pinterest", _external=True)

    @classmethod
    def configured(cls) -> bool:
        return bool(_cfg("PINTEREST_CLIENT_ID") and _cfg("PINTEREST_CLIENT_SECRET"))

    @classmethod
    def authorize_url(cls) -> tuple[str, str]:
        state = secrets.token_urlsafe(16)
        params = urllib.parse.urlencode(
            {
                "client_id": _cfg("PINTEREST_CLIENT_ID"),
                "redirect_uri": cls.redirect_uri(),
                "response_type": "code",
                "scope": cls.SCOPES,
                "state": state,
            }
        )
        return f"{cls.AUTH}?{params}", state

    @classmethod
    def exchange(cls, code: str) -> None:
        creds = base64.b64encode(f"{_cfg('PINTEREST_CLIENT_ID')}:{_cfg('PINTEREST_CLIENT_SECRET')}".encode()).decode()
        data = _post_form(
            cls.TOKEN,
            {"grant_type": "authorization_code", "code": code, "redirect_uri": cls.redirect_uri()},
            headers={"Authorization": f"Basic {creds}"},
        )
        if not data.get("access_token"):
            raise RuntimeError(str(data.get("error_description") or data.get("error") or data)[:200])
        username = ""
        try:
            who = _get_json(f"{cls.API}/user_account", headers={"Authorization": f"Bearer {data['access_token']}"})
            username = who.get("username") or ""
        except Exception:
            pass
        save_token("pinterest", data["access_token"], data.get("refresh_token") or "", int(data.get("expires_in") or 2592000), username, scopes=cls.SCOPES)

    @classmethod
    def access(cls) -> str:
        row = token_row("pinterest")
        if not row:
            return ""
        return row.access_token

    @classmethod
    def boards(cls) -> list[dict]:
        token = cls.access()
        if not token:
            return []
        try:
            data = _get_json(f"{cls.API}/boards", headers={"Authorization": f"Bearer {token}"})
            return [{"id": item["id"], "name": item["name"]} for item in data.get("items") or []]
        except Exception:
            return []

    @classmethod
    def status(cls) -> dict:
        row = token_row("pinterest")
        return {"configured": cls.configured(), "connected": bool(row), "name": (row.account_username if row else "")}

    @classmethod
    def publish(cls, message: str, image_url: str = "", link: str = "", title: str = "") -> dict:
        token = cls.access()
        if not token:
            return {"ok": False, "error": "Pinterest non connecté"}
        board = _cfg("PINTEREST_DEFAULT_BOARD_ID") or (token_row("pinterest").account_id if token_row("pinterest") else "")
        if not board:
            boards = cls.boards()
            if boards:
                board = boards[0]["id"]
                row = token_row("pinterest")
                if row:
                    row.account_id = board
                    db.session.commit()
        if not board:
            return {"ok": False, "error": "Aucun tableau Pinterest"}
        if not image_url:
            return {"ok": False, "error": "Image requise"}
        res = _post_json(
            f"{cls.API}/pins",
            {
                "board_id": board,
                "title": (title or message or "Artworksdigital")[:100],
                "description": message[:500],
                "link": link,
                "media_source": {"source_type": "image_url", "url": image_url},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if res.get("error"):
            return {"ok": False, "error": str(res.get("error"))[:300]}
        return {"ok": True, "id": str(res.get("id") or ""), "url": res.get("link") or ""}


PLATFORMS = {
    "facebook": Facebook,
    "instagram": Instagram,
    "pinterest": Pinterest,
    "deviantart": DeviantArt,
}


def platform_status() -> dict:
    return {key: cls.status() for key, cls in PLATFORMS.items()}


def publish(platforms: list[str], *, title: str, message: str, image_url: str = "", link: str = "") -> list[dict]:
    results = []
    for key in platforms:
        cls = PLATFORMS.get(key)
        if cls is None:
            results.append({"platform": key, "ok": False, "error": "inconnu"})
            continue
        extra = {}
        if key in {"pinterest", "deviantart"}:
            extra["title"] = title
        res = cls.publish(message, image_url=image_url, link=link, **extra) if extra else cls.publish(message, image_url=image_url, link=link)
        res["platform"] = key
        results.append(res)
    return results
