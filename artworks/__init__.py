from io import BytesIO
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, send_file
from werkzeug.middleware.proxy_fix import ProxyFix

from artworks.analytics import attach_session_cookie, record_view, should_track
from artworks.config import Config, ensure_schema
from artworks.extensions import csrf, db, login_manager
from artworks.images import VARIANT_WIDTHS, asset_bytes, variant_bytes
from artworks.legacy_urls import destination as legacy_destination
from artworks.seo import (
    absolute_media,
    canonical_redirect,
    canonical_url,
    default_og_image,
    media_srcset,
    media_url,
    static_url,
)


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    (Path(app.instance_path) / "uploads").mkdir(exist_ok=True)

    # `SECRET_KEY` ne signe pas que la session : il signe aussi les liens de
    # réinitialisation de mot de passe. Laissé à sa valeur de repli, celle
    # qui est écrite dans le dépôt, n'importe qui sachant lire ce fichier
    # peut fabriquer un lien valide pour n'importe quel artiste. Le repli
    # reste, pour que `python run.py` marche sans rien configurer — mais il
    # ne doit plus pouvoir passer inaperçu au démarrage en production.
    if app.config.get("SECRET_KEY") == "dev-artworks-digital" and app.config.get(
        "CANONICAL_REDIRECT"
    ):
        app.logger.warning(
            "SECRET_KEY est resté sur sa valeur par défaut alors que le site "
            "tourne en posture de production : les sessions et les liens de "
            "réinitialisation de mot de passe sont falsifiables. Posez "
            "SECRET_KEY dans l'environnement."
        )

    # Même logique pour le webhook Stripe : il est désormais refusé sans
    # secret, donc l'oubli ne laisse plus de porte ouverte — mais il ferait
    # échouer silencieusement tout changement d'offre après paiement. Le
    # dire au démarrage, c'est la différence entre une variable oubliée
    # qu'on voit tout de suite et une facturation qui ne s'applique plus
    # sans que personne ne comprenne pourquoi.
    if app.config.get("STRIPE_SECRET_KEY") and not app.config.get("STRIPE_WEBHOOK_SECRET"):
        app.logger.warning(
            "Stripe est configuré mais STRIPE_WEBHOOK_SECRET est absent : les "
            "événements Stripe seront refusés faute de signature vérifiable, "
            "et les changements d'offre ne s'appliqueront pas automatiquement."
        )

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
            "media_url": media_url,
            "media_srcset": media_srcset,
            "static_url": static_url,
            "default_og_image": default_og_image(),
            "site_contact_email": app.config.get("SITE_CONTACT_EMAIL", ""),
            "site_same_as": [
                url.strip()
                for url in (app.config.get("SITE_SAME_AS") or "").split(",")
                if url.strip().startswith("http")
            ],
            "site_founded": app.config.get("SITE_FOUNDING_YEAR", ""),
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

        # Les en-têtes que tout site public devrait poser, et que les
        # audits — Lighthouse, Search Console, les moteurs génératifs —
        # lisent comme un signe de sérieux.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=(), interest-cohort=()"
        )
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

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

    def _serve(payload):
        if payload is None:
            abort(404)
        data, mime = payload
        response = send_file(BytesIO(data), mimetype=mime)
        # Le nom d'un visuel porte son empreinte : il ne change jamais de
        # contenu, donc un an de cache et pas de revalidation.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    def _safe_name(filename: str) -> str:
        if ".." in filename or "/" in filename or "\\" in filename:
            abort(404)
        return filename

    @app.route("/media/<path:filename>")
    def media(filename: str):
        return _serve(asset_bytes(_safe_name(filename)))

    @app.route("/media/w<int:width>/<path:filename>")
    def media_variant(width: int, filename: str):
        """Le même visuel, à la largeur demandée.

        Une vignette n'a pas besoin de deux mille pixels. Les largeurs
        acceptées sont closes — sinon n'importe qui fabriquerait mille
        tailles et remplirait le disque."""
        if width not in VARIANT_WIDTHS:
            abort(404)
        return _serve(variant_bytes(_safe_name(filename), width))

    @app.errorhandler(404)
    def not_found(_error):
        # Le site d’avant a laissé ses adresses dans les moteurs et dans les
        # marque-pages. Quand l’une d’elles désigne une salle qui existe, on
        # y mène plutôt que de refermer la porte.
        try:
            target = legacy_destination(request.path)
        except Exception:
            db.session.rollback()
            target = None
        if target and target != request.path:
            return redirect(target, code=301)
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("403.html"), 403

    with app.app_context():
        ensure_schema()

    return app
