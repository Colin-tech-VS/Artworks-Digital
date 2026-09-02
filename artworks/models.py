from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from artworks.extensions import db, login_manager


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Artist(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    statement = db.Column(db.Text, default="")
    location = db.Column(db.String(120), default="")
    discipline = db.Column(db.String(120), default="")
    contact_email = db.Column(db.String(180), default="")
    cover_path = db.Column(db.String(255), default="")
    published = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    works = db.relationship(
        "Work",
        backref="artist",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="Work.position.asc(), Work.id.desc()",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def hung_works(self):
        return self.works.filter_by(visible=True).all()


class Work(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    year = db.Column(db.String(12), default="")
    medium = db.Column(db.String(160), default="")
    dimensions = db.Column(db.String(120), default="")
    note = db.Column(db.Text, default="")
    image_path = db.Column(db.String(255), nullable=False)
    visible = db.Column(db.Boolean, default=True, nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    @property
    def cartel(self) -> str:
        parts = [p for p in (self.year, self.medium, self.dimensions) if p]
        return " · ".join(parts)


@login_manager.user_loader
def load_artist(artist_id: str):
    return db.session.get(Artist, int(artist_id))
