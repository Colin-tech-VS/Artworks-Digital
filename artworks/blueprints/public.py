from flask import Blueprint, abort, render_template

from artworks.extensions import db
from artworks.models import Artist, Work

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def home():
    rooms = (
        Artist.query.filter_by(published=True)
        .order_by(Artist.created_at.desc())
        .limit(8)
        .all()
    )
    return render_template("public/home.html", rooms=rooms)


@public_bp.route("/galerie/<slug>")
def gallery(slug: str):
    artist = Artist.query.filter_by(slug=slug, published=True).first()
    if artist is None:
        abort(404)
    works = artist.hung_works
    return render_template("public/gallery.html", artist=artist, works=works)


@public_bp.route("/galerie/<slug>/oeuvre/<int:work_id>")
def artwork(slug: str, work_id: int):
    artist = Artist.query.filter_by(slug=slug, published=True).first()
    if artist is None:
        abort(404)
    work = Work.query.filter_by(id=work_id, artist_id=artist.id, visible=True).first()
    if work is None:
        abort(404)
    work.view_count = (work.view_count or 0) + 1
    db.session.commit()
    hung = artist.hung_works
    index = next((i for i, item in enumerate(hung) if item.id == work.id), 0)
    prev_work = hung[index - 1] if index > 0 else None
    next_work = hung[index + 1] if index + 1 < len(hung) else None
    return render_template(
        "public/artwork.html",
        artist=artist,
        work=work,
        prev_work=prev_work,
        next_work=next_work,
    )
