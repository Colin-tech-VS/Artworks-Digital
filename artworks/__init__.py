from io import BytesIO
from pathlib import Path

from flask import Flask, abort, g, render_template, request, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

from artworks.analytics import attach_session_cookie, record_view, should_track
from artworks.config import Config, ensure_schema
from artworks.extensions import csrf, db, login_manager
from artworks.images import asset_bytes
from artworks.seo import absolute_media, canonical_redirect, canonical_url, default_og_image, static_url


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    (Path(app.instance_path) / "uploads").mkdir(exist_ok=True)

    if app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///artworks.db":
        db_path = Path(app.instance_path) / "artworks.db"
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.as_posix()}"

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from artworks import models  # noqa: F401
    from artworks.blueprints.admin import admin_bp
    from artworks.blueprints.atelier import atelier_bp
    from artworks.blueprints.auth import auth_bp
    from artworks.blueprints.billing import billing_bp
    from artworks.blueprints.kael import kael_bp
    from artworks.blueprints.public import public_bp
    from artworks.kael import tools as kael_tools  # noqa: F401 — enregistre les outils

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(atelier_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(kael_bp)

    from artworks.gate import enforce_gate

    app.before_request(canonical_redirect)
    app.before_request(enforce_gate)

    @app.context_processor
    def inject_seo():
        return {
            "canonical_url": canonical_url,
            "absolute_media": absolute_media,
            "static_url": static_url,
            "default_og_image": default_og_image(),
            "site_contact_email": app.config.get("SITE_CONTACT_EMAIL", ""),
            "kael_ready": bool(
                app.config.get("KAEL_ENABLED")
                and app.config.get("KAEL_API_URL")
                and (app.config.get("KAEL_API_KEY") or app.config.get("KAEL_API_TOKEN"))
            ),
        }

    @app.after_request
    def track_and_headers(response):
        endpoint = request.endpoint or ""
        if (
            endpoint.startswith("atelier.")
            or endpoint.startswith("admin.")
            or endpoint.startswith("auth.")
            or endpoint.startswith("kael.")
        ):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if response.status_code == 200 and should_track(request):
            artist_id = getattr(g, "track_artist_id", None)
            work_id = getattr(g, "track_work_id", None)
            title = getattr(g, "track_title", "")
            try:
                sid = record_view(request, title=title, artist_id=artist_id, work_id=work_id)
                attach_session_cookie(response, sid)
            except Exception:
                db.session.rollback()
        return response

    @app.route("/media/<path:filename>")
    def media(filename: str):
        if ".." in filename or "/" in filename or "\\" in filename:
            abort(404)
        payload = asset_bytes(filename)
        if payload is None:
            abort(404)
        data, mime = payload
        response = send_file(BytesIO(data), mimetype=mime)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("403.html"), 403

    with app.app_context():
        ensure_schema()

    return app
