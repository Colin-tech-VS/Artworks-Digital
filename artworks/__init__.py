from io import BytesIO
from pathlib import Path

from flask import Flask, abort, render_template, send_file

from artworks.config import Config, ensure_schema
from artworks.extensions import csrf, db, login_manager
from artworks.images import asset_bytes


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    (Path(app.instance_path) / "uploads").mkdir(exist_ok=True)

    if app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///artworks.db":
        db_path = Path(app.instance_path) / "artworks.db"
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.as_posix()}"

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from artworks import models  # noqa: F401
    from artworks.blueprints.atelier import atelier_bp
    from artworks.blueprints.auth import auth_bp
    from artworks.blueprints.public import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(atelier_bp)

    from artworks.gate import enforce_gate

    app.before_request(enforce_gate)

    @app.route("/media/<path:filename>")
    def media(filename: str):
        if ".." in filename or "/" in filename or "\\" in filename:
            abort(404)
        payload = asset_bytes(filename)
        if payload is None:
            abort(404)
        data, mime = payload
        return send_file(BytesIO(data), mimetype=mime)

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    with app.app_context():
        ensure_schema()

    return app
