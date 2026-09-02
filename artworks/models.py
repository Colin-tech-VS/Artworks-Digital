from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from artworks.extensions import db, login_manager


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def meta_trim(text: str, limit: int = 158) -> str:
    """Coupe une description au dernier mot entier : les moteurs n’affichent
    qu’environ 160 signes, autant choisir où la phrase s’arrête."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:–—-") + "…"


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
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_example = db.Column(db.Boolean, default=False, nullable=False)
    plan_key = db.Column(db.String(40), default="decouverte", nullable=False, index=True)
    plan_status = db.Column(db.String(30), default="active", nullable=False)
    plan_override = db.Column(db.Boolean, default=False, nullable=False)
    stripe_customer_id = db.Column(db.String(80), default="")
    stripe_subscription_id = db.Column(db.String(80), default="")
    plan_period_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    works = db.relationship(
        "Work",
        backref="artist",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="Work.position.asc(), Work.id.desc()",
    )
    messages = db.relationship(
        "MailMessage",
        backref="artist",
        lazy="dynamic",
        foreign_keys="MailMessage.artist_id",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def touch(self) -> None:
        self.updated_at = utcnow()

    @property
    def hung_works(self):
        return self.works.filter_by(visible=True).all()

    @property
    def hung_count(self) -> int:
        return self.works.filter_by(visible=True).count()

    @property
    def reserve_count(self) -> int:
        return self.works.filter_by(visible=False).count()

    @property
    def views_total(self) -> int:
        total = db.session.query(db.func.coalesce(db.func.sum(Work.view_count), 0)).filter(
            Work.artist_id == self.id
        ).scalar()
        return int(total or 0)

    @property
    def initial(self) -> str:
        name = (self.display_name or "?").strip()
        return name[:1].upper()

    @property
    def seo_description(self) -> str:
        bits = [f"Galerie de {self.display_name}"]
        if self.discipline:
            bits.append(self.discipline)
        if self.location:
            bits.append(self.location)
        text = (self.statement or "").strip()
        if text:
            return meta_trim(f"{' — '.join(bits)}. {text}")
        return meta_trim(f"{' — '.join(bits)} sur Artworksdigital.")

    @property
    def unread_count(self) -> int:
        return self.messages.filter_by(is_read=False, direction="in").count()

    @property
    def offer(self):
        from artworks.plans import get_offer

        return get_offer(self.plan_key)

    def has_feature(self, name: str) -> bool:
        offer = self.offer
        return bool(offer and offer.allows(name))

    def work_limit(self) -> int | None:
        offer = self.offer
        return None if offer is None else offer.max_works

    def can_add_work(self) -> bool:
        limit = self.work_limit()
        if not limit:
            return True
        return self.works.count() < limit

    def public_works(self):
        works = self.hung_works
        limit = self.work_limit()
        if limit:
            return works[:limit]
        return works

    @property
    def plan_rank(self) -> int:
        offer = self.offer
        return offer.sort if offer else 0


class Work(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    year = db.Column(db.String(12), default="")
    medium = db.Column(db.String(160), default="")
    dimensions = db.Column(db.String(120), default="")
    note = db.Column(db.Text, default="")
    image_path = db.Column(db.String(255), nullable=False)
    image_w = db.Column(db.Integer, default=0, nullable=False)
    image_h = db.Column(db.Integer, default=0, nullable=False)
    visible = db.Column(db.Boolean, default=True, nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)
    view_count = db.Column(db.Integer, default=0, nullable=False)
    collection_name = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    def touch(self) -> None:
        self.updated_at = utcnow()

    @property
    def cartel(self) -> str:
        parts = [p for p in (self.year, self.medium, self.dimensions) if p]
        return " · ".join(parts)

    @property
    def seo_description(self) -> str:
        parts = [self.title, self.artist.display_name]
        if self.cartel:
            parts.append(self.cartel)
        note = (self.note or "").strip()
        base = " — ".join(parts)
        if note:
            return meta_trim(f"{base}. {note}")
        return meta_trim(f"{base}. Œuvre présentée dans la galerie Artworksdigital.")


class Asset(db.Model):
    """Visuels persistés en base — le disque Scalingo est éphémère."""

    id = db.Column(db.String(80), primary_key=True)
    mime = db.Column(db.String(64), default="image/jpeg", nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class PageView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(300), nullable=False, index=True)
    title = db.Column(db.String(200), default="")
    referrer = db.Column(db.String(400), default="")
    source = db.Column(db.String(40), default="direct", index=True)
    device = db.Column(db.String(20), default="desktop")
    session_id = db.Column(db.String(40), index=True)
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=True, index=True)
    work_id = db.Column(db.Integer, db.ForeignKey("work.id"), nullable=True, index=True)
    is_bot = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


class Offer(db.Model):
    key = db.Column(db.String(40), primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    badge = db.Column(db.String(16), default="")
    audience = db.Column(db.String(180), default="")
    features_text = db.Column(db.Text, default="")
    price_cents = db.Column(db.Integer, default=0, nullable=False)
    max_works = db.Column(db.Integer, nullable=True)
    sort = db.Column(db.Integer, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    allow_stats = db.Column(db.Boolean, default=False, nullable=False)
    allow_customize = db.Column(db.Boolean, default=False, nullable=False)
    allow_share = db.Column(db.Boolean, default=False, nullable=False)
    allow_advanced_stats = db.Column(db.Boolean, default=False, nullable=False)
    allow_featured = db.Column(db.Boolean, default=False, nullable=False)
    allow_ai = db.Column(db.Boolean, default=False, nullable=False)
    allow_priority = db.Column(db.Boolean, default=False, nullable=False)
    allow_collections = db.Column(db.Boolean, default=False, nullable=False)
    stripe_product_id = db.Column(db.String(80), default="")
    stripe_price_id = db.Column(db.String(80), default="")

    def allows(self, name: str) -> bool:
        return bool(getattr(self, f"allow_{name}", False))

    @property
    def price_label(self) -> str:
        if not self.price_cents:
            return "0 €/mois"
        euros = self.price_cents / 100
        text = f"{euros:.2f}".replace(".", ",")
        return f"{text} €/mois"

    @property
    def works_label(self) -> str:
        if not self.max_works:
            return "Œuvres illimitées"
        return f"Jusqu’à {self.max_works} œuvres"

    @property
    def feature_lines(self) -> list[str]:
        return [line.strip() for line in (self.features_text or "").splitlines() if line.strip()]


class SubscriptionEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=True, index=True)
    plan_key = db.Column(db.String(40), default="")
    status = db.Column(db.String(40), default="")
    stripe_id = db.Column(db.String(80), default="")
    note = db.Column(db.String(240), default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


class SocialToken(db.Model):
    platform = db.Column(db.String(32), primary_key=True)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, default="")
    token_expires_at = db.Column(db.DateTime, nullable=True)
    account_username = db.Column(db.String(120), default="")
    account_id = db.Column(db.String(80), default="")
    scopes = db.Column(db.String(255), default="")
    updated_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class SocialPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(32), nullable=False, index=True)
    work_id = db.Column(db.Integer, db.ForeignKey("work.id"), nullable=True)
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=True, index=True)
    title = db.Column(db.String(180), default="")
    body = db.Column(db.Text, default="")
    image_url = db.Column(db.String(400), default="")
    image_name = db.Column(db.String(80), default="")
    alt_text = db.Column(db.String(400), default="")
    prompt = db.Column(db.Text, default="")
    design_json = db.Column(db.Text, default="")
    remote_id = db.Column(db.String(120), default="")
    remote_url = db.Column(db.String(400), default="")
    status = db.Column(db.String(20), default="ok")
    error = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


class MailMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=True, index=True)
    direction = db.Column(db.String(8), default="in", nullable=False, index=True)
    kind = db.Column(db.String(20), default="contact")
    status = db.Column(db.String(20), default="inbox")
    from_name = db.Column(db.String(120), default="")
    from_email = db.Column(db.String(180), default="")
    to_name = db.Column(db.String(120), default="")
    to_email = db.Column(db.String(180), default="")
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    external_id = db.Column(db.String(200), default="", index=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


class KaelToken(db.Model):
    """Un jeton d'accès de K.A.E.L. à Artworks Digital.

    Le secret n'est jamais stocké en clair : seule son empreinte l'est, et
    le préfixe sert à retrouver la ligne sans révéler le reste. Les portées
    sont attachées au jeton, pas à K.A.E.L. — révoquer un jeton suffit à
    refermer une porte."""

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(120), nullable=False)
    prefix = db.Column(db.String(16), unique=True, nullable=False, index=True)
    secret_hash = db.Column(db.String(255), nullable=False)
    scopes_text = db.Column(db.String(255), default="", nullable=False)
    # Un jeton peut être limité à un seul atelier : K.A.E.L. ne voit alors
    # que cet artiste, quelles que soient ses portées.
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=True, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    use_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    @property
    def scopes(self) -> list[str]:
        return [part for part in (self.scopes_text or "").split(",") if part]

    @scopes.setter
    def scopes(self, values) -> None:
        self.scopes_text = ",".join(values or [])


class KaelAuditLog(db.Model):
    """Tout ce que K.A.E.L. a tenté sur la plateforme, réussi ou non."""

    id = db.Column(db.Integer, primary_key=True)
    token_id = db.Column(db.Integer, db.ForeignKey("kael_token.id"), nullable=True, index=True)
    token_label = db.Column(db.String(120), default="")
    tool = db.Column(db.String(80), nullable=False, index=True)
    permission = db.Column(db.String(30), default="")
    params_json = db.Column(db.Text, default="")
    ok = db.Column(db.Boolean, default=True, nullable=False, index=True)
    summary = db.Column(db.String(400), default="")
    error = db.Column(db.Text, default="")
    confirmed = db.Column(db.Boolean, default=False, nullable=False)
    actor = db.Column(db.String(120), default="")
    subject_kind = db.Column(db.String(30), default="")
    subject_id = db.Column(db.String(40), default="")
    duration_ms = db.Column(db.Integer, default=0, nullable=False)
    remote_addr = db.Column(db.String(60), default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)


@login_manager.user_loader
def load_artist(artist_id: str):
    return db.session.get(Artist, int(artist_id))
