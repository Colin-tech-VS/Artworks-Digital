import json
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from markupsafe import Markup
from sqlalchemy import func

from artworks.admin_auth import admin_logout, require_admin, try_admin_login
from artworks.analytics import breakdown, kpis, series, sparkline_svg, top_paths
from artworks.extensions import db
from artworks.forms import AdminLoginForm, ComposeForm, OfferForm, SocialComposeForm, SocialPublishForm
from artworks.emails import deliver as deliver_email
from artworks.mailer import contact_inbox, fetch_inbox, mail_configured
from artworks.mistral import mistral_ready
from artworks.models import Artist, MailMessage, Offer, PageView, SocialPost, SubscriptionEvent, Work
from artworks.seo import absolute_media, canonical_url
from artworks.social import DeviantArt, Pinterest, delete_token, platform_status, publish as publish_social
from artworks.plans import all_offers, get_offer
from artworks.stripe_billing import apply_plan, stripe_ready, sync_offers_to_stripe


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        blocked = require_admin()
        if blocked is not None:
            return blocked
        return fn(*args, **kwargs)

    return wrapped


def _loads(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _paragraphs(body: str) -> list[str]:
    """Un texte libre devient des paragraphes : les lignes vides séparent."""
    blocks = [block.strip() for block in (body or "").split("\n\n")]
    return [block for block in blocks if block] or [(body or "").strip()]


def _days() -> int:
    try:
        value = int(request.args.get("days", 28))
    except (TypeError, ValueError):
        value = 28
    return value if value in (7, 28, 90) else 28


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    form = AdminLoginForm()
    error = False
    if form.validate_on_submit():
        if try_admin_login(form.username.data or "", form.password.data or ""):
            nxt = request.args.get("next") or url_for("admin.overview")
            if not nxt.startswith("/admin"):
                nxt = url_for("admin.overview")
            return redirect(nxt)
        error = True
    return render_template("admin/login.html", form=form, login_error=error)


@admin_bp.route("/logout", methods=["GET", "POST"])
def logout():
    admin_logout()
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@admin_required
def overview():
    days = _days()
    metrics = kpis(days)
    chart = series(days)
    recent_mail = MailMessage.query.order_by(MailMessage.created_at.desc()).limit(6).all()
    artists = Artist.query.order_by(Artist.created_at.desc()).limit(8).all()
    unread = MailMessage.query.filter_by(direction="in", is_read=False).count()
    plan_counts = dict(
        db.session.query(Artist.plan_key, func.count(Artist.id))
        .filter(Artist.is_example.is_(False))
        .group_by(Artist.plan_key)
        .all()
    )
    catalog = all_offers()
    mrr_cents = sum((plan_counts.get(offer.key, 0) * (offer.price_cents or 0)) for offer in catalog)
    return render_template(
        "admin/overview.html",
        days=days,
        metrics=metrics,
        chart=chart,
        spark=Markup(sparkline_svg([row["views"] for row in chart], 520, 120)),
        recent_mail=recent_mail,
        artists=artists,
        unread=unread,
        rooms=Artist.query.filter_by(published=True).count(),
        total_artists=Artist.query.count(),
        total_works=Work.query.count(),
        mail_ok=mail_configured(),
        stripe_ok=stripe_ready(),
        mistral_ok=mistral_ready(),
        social=platform_status(),
        plan_counts=plan_counts,
        offers=catalog,
        mrr_label=f"{mrr_cents / 100:.2f}".replace(".", ",") + " €",
        paying=sum(plan_counts.get(offer.key, 0) for offer in catalog if offer.price_cents),
    )


@admin_bp.route("/analytics")
@admin_required
def analytics():
    days = _days()
    chart = series(days)
    return render_template(
        "admin/analytics.html",
        days=days,
        metrics=kpis(days),
        chart=chart,
        spark=Markup(sparkline_svg([row["views"] for row in chart], 720, 160)),
        users_spark=Markup(sparkline_svg([row["users"] for row in chart], 720, 120)),
        sources=breakdown(PageView.source, days),
        devices=breakdown(PageView.device, days),
        paths=top_paths(days),
        referrers=breakdown(PageView.referrer, days, limit=8),
    )


@admin_bp.route("/emails")
@admin_required
def emails():
    try:
        fetch_inbox()
    except Exception:
        db.session.rollback()
    folder = request.args.get("folder", "in")
    query = MailMessage.query.order_by(MailMessage.created_at.desc())
    if folder == "out":
        query = query.filter_by(direction="out")
    elif folder == "unread":
        query = query.filter_by(direction="in", is_read=False)
    else:
        folder = "in"
        query = query.filter_by(direction="in")
    messages = query.limit(80).all()
    return render_template(
        "admin/emails.html",
        messages=messages,
        folder=folder,
        unread=MailMessage.query.filter_by(direction="in", is_read=False).count(),
        mail_ok=mail_configured(),
    )


@admin_bp.route("/emails/nouveau", methods=["GET", "POST"])
@admin_required
def compose():
    form = ComposeForm()
    if request.args.get("to"):
        form.to_email.data = request.args.get("to")
    if form.validate_on_submit():
        ok, error = deliver_email(
            form.to_email.data.strip(),
            form.subject.data.strip(),
            eyebrow="Artworksdigital",
            title=form.subject.data.strip(),
            paragraphs=_paragraphs(form.body.data),
            log=False,
        )
        message = MailMessage(
            direction="out",
            kind="admin",
            status="sent" if ok else "failed",
            from_name="Artworksdigital",
            from_email=contact_inbox(),
            to_email=form.to_email.data.strip().lower(),
            subject=form.subject.data.strip(),
            body=form.body.data.strip(),
            is_read=True,
        )
        artist = Artist.query.filter_by(email=message.to_email).first()
        if artist:
            message.artist_id = artist.id
            message.to_name = artist.display_name
        db.session.add(message)
        db.session.commit()
        flash("Message envoyé." if ok else f"Enregistré sans envoi SMTP. {error}", "ok" if ok else "info")
        return redirect(url_for("admin.email_detail", message_id=message.id))
    return render_template("admin/compose.html", form=form, mail_ok=mail_configured())


@admin_bp.route("/emails/<int:message_id>", methods=["GET", "POST"])
@admin_required
def email_detail(message_id: int):
    message = db.session.get(MailMessage, message_id) or abort(404)
    if not message.is_read:
        message.is_read = True
        db.session.commit()
    form = ComposeForm()
    if request.method == "GET":
        form.to_email.data = message.from_email if message.direction == "in" else message.to_email
        form.subject.data = message.subject if message.subject.lower().startswith("re:") else f"Re: {message.subject}"
    if form.validate_on_submit():
        ok, error = deliver_email(
            form.to_email.data.strip(),
            form.subject.data.strip(),
            eyebrow="Réponse",
            title=form.subject.data.strip(),
            paragraphs=_paragraphs(form.body.data),
            reply_to=contact_inbox(),
            log=False,
        )
        reply = MailMessage(
            artist_id=message.artist_id,
            direction="out",
            kind="admin",
            status="sent" if ok else "failed",
            from_name="Artworksdigital",
            from_email=contact_inbox(),
            to_email=form.to_email.data.strip().lower(),
            to_name=message.from_name,
            subject=form.subject.data.strip(),
            body=form.body.data.strip(),
            is_read=True,
        )
        db.session.add(reply)
        db.session.commit()
        flash("Réponse envoyée." if ok else f"Réponse conservée. {error}", "ok" if ok else "info")
        return redirect(url_for("admin.email_detail", message_id=reply.id))
    return render_template("admin/email.html", message=message, form=form, mail_ok=mail_configured())


EMAIL_PREVIEWS = {
    "welcome": "Bienvenue — atelier ouvert",
    "password_reset": "Mot de passe oublié",
    "password_changed": "Mot de passe modifié",
    "email_changed": "E-mail de connexion modifié",
    "gallery_published": "Galerie publiée",
    "new_message": "Nouveau message reçu",
    "contact_receipt": "Accusé de réception visiteur",
    "plan_changed": "Changement d’offre",
    "payment_failed": "Paiement refusé",
}


@admin_bp.route("/emails/modeles")
@admin_required
def email_previews():
    return render_template("admin/email_previews.html", previews=EMAIL_PREVIEWS)


@admin_bp.route("/emails/modeles/<kind>")
@admin_required
def email_preview(kind: str):
    from artworks.emails import preview_html

    html = preview_html(kind)
    if html is None:
        abort(404)
    return html


@admin_bp.route("/emails/modeles/<kind>/test", methods=["POST"])
@admin_required
def email_preview_send(kind: str):
    from artworks.emails import send_preview

    target = (request.form.get("to") or contact_inbox()).strip()
    ok, error = send_preview(kind, target)
    flash(f"Aperçu envoyé à {target}." if ok else f"Envoi impossible. {error}", "ok" if ok else "info")
    return redirect(url_for("admin.email_previews"))


@admin_bp.route("/artistes")
@admin_required
def artists():
    rows = Artist.query.order_by(Artist.created_at.desc()).all()
    return render_template("admin/artists.html", artists=rows)


@admin_bp.route("/artistes/<int:artist_id>", methods=["POST"])
@admin_required
def artist_action(artist_id: int):
    artist = db.session.get(Artist, artist_id) or abort(404)
    action = request.form.get("action")
    if action == "publish":
        artist.published = not artist.published
        flash("Salle ouverte." if artist.published else "Salle fermée.", "ok")
    db.session.commit()
    return redirect(url_for("admin.artists"))


def _offer_form(offer: Offer) -> OfferForm:
    return OfferForm(
        name=offer.name,
        badge=offer.badge,
        audience=offer.audience,
        features_text=offer.features_text,
        price_cents=offer.price_cents,
        max_works=offer.max_works,
        active=offer.active,
        allow_stats=offer.allow_stats,
        allow_customize=offer.allow_customize,
        allow_share=offer.allow_share,
        allow_advanced_stats=offer.allow_advanced_stats,
        allow_featured=offer.allow_featured,
        allow_ai=offer.allow_ai,
        allow_priority=offer.allow_priority,
        allow_collections=offer.allow_collections,
    )


@admin_bp.route("/offres")
@admin_required
def offers():
    return render_template(
        "admin/offers.html",
        offers=all_offers(),
        stripe_ok=stripe_ready(),
    )


@admin_bp.route("/offres/sync", methods=["POST"])
@admin_required
def offers_sync():
    ok, message = sync_offers_to_stripe()
    flash(message, "ok" if ok else "info")
    return redirect(url_for("admin.offers"))


@admin_bp.route("/offres/<key>", methods=["GET", "POST"])
@admin_required
def offer_edit(key: str):
    offer = db.session.get(Offer, key) or abort(404)
    form = _offer_form(offer)
    if request.method == "POST":
        form = OfferForm()
        if form.validate_on_submit():
            offer.name = form.name.data.strip()
            offer.badge = (form.badge.data or "").strip()
            offer.audience = (form.audience.data or "").strip()
            offer.features_text = (form.features_text.data or "").strip()
            offer.price_cents = form.price_cents.data or 0
            offer.max_works = form.max_works.data
            offer.active = bool(form.active.data)
            offer.allow_stats = bool(form.allow_stats.data)
            offer.allow_customize = bool(form.allow_customize.data)
            offer.allow_share = bool(form.allow_share.data)
            offer.allow_advanced_stats = bool(form.allow_advanced_stats.data)
            offer.allow_featured = bool(form.allow_featured.data)
            offer.allow_ai = bool(form.allow_ai.data)
            offer.allow_priority = bool(form.allow_priority.data)
            offer.allow_collections = bool(form.allow_collections.data)
            db.session.commit()
            flash("Offre mise à jour.", "ok")
            return redirect(url_for("admin.offers"))
    return render_template("admin/offer.html", form=form, offer=offer, stripe_ok=stripe_ready())


@admin_bp.route("/abonnements")
@admin_required
def subscriptions():
    catalog = all_offers()
    return render_template(
        "admin/subscriptions.html",
        artists=Artist.query.order_by(Artist.created_at.desc()).all(),
        offers=catalog,
        events=SubscriptionEvent.query.order_by(SubscriptionEvent.created_at.desc()).limit(24).all(),
        stripe_ok=stripe_ready(),
    )


@admin_bp.route("/abonnements/<int:artist_id>", methods=["POST"])
@admin_required
def assign_plan(artist_id: int):
    artist = db.session.get(Artist, artist_id) or abort(404)
    offer = get_offer(request.form.get("plan_key") or "")
    if offer is None:
        flash("Offre inconnue.", "info")
        return redirect(url_for("admin.subscriptions"))
    artist.plan_override = True
    apply_plan(artist, offer.key, status="active", note="Assigné par admin")
    flash(f"{artist.display_name} est désormais sur {offer.name}.", "ok")
    return redirect(url_for("admin.subscriptions"))


@admin_bp.route("/social", methods=["GET", "POST"])
@admin_required
def social():
    from artworks.composer import compose, log_publication

    publish_form = SocialPublishForm()
    compose_form = SocialComposeForm()
    works = (
        Work.query.join(Artist)
        .filter(Work.visible.is_(True), Artist.published.is_(True))
        .order_by(Work.updated_at.desc())
        .limit(80)
        .all()
    )
    choices = [("", "— sans œuvre —")] + [
        (str(work.id), f"{work.artist.display_name} — {work.title}") for work in works
    ]
    compose_form.work_id.choices = choices
    draft = None
    action = request.form.get("action", "")

    if action == "generate" and compose_form.validate_on_submit():
        work = db.session.get(Work, int(compose_form.work_id.data)) if compose_form.work_id.data else None
        try:
            draft = compose(
                compose_form.prompt.data.strip(),
                platforms=[compose_form.platform.data],
                work=work,
                fmt=compose_form.fmt.data or "",
                layout=compose_form.layout.data or "",
                heavy=bool(compose_form.heavy.data),
                use_artwork=bool(compose_form.use_artwork.data),
            )
        except Exception as exc:
            db.session.rollback()
            flash(f"Génération impossible : {exc}", "info")
        else:
            if draft["warning"]:
                flash(draft["warning"], "info")
            # Le brouillon remplit le formulaire de publication, prêt à corriger.
            publish_form.process(
                data={
                    "work_id": work.id if work else None,
                    "title": draft["design"]["headline"],
                    "message": draft["message"],
                    "link": draft["link"],
                    "image_url": draft["image_url"],
                    "image_name": draft["image_name"],
                    "alt_text": draft["alt"],
                    "prompt": draft["prompt"],
                    "design_json": json.dumps(draft["design"], ensure_ascii=False),
                    "facebook": compose_form.platform.data == "facebook",
                    "instagram": compose_form.platform.data == "instagram",
                    "pinterest": compose_form.platform.data == "pinterest",
                    "deviantart": compose_form.platform.data == "deviantart",
                }
            )

    elif action != "generate" and publish_form.validate_on_submit():
        work = db.session.get(Work, publish_form.work_id.data) if publish_form.work_id.data else None
        image_url = (publish_form.image_url.data or "").strip()
        link = (publish_form.link.data or "").strip()
        title = (publish_form.title.data or "").strip()
        if work:
            image_url = image_url or absolute_media(work.image_path)
            link = link or canonical_url(url_for("public.artwork", slug=work.artist.slug, work_id=work.id))
            title = title or work.title
        platforms = [name for name, on in (
            ("facebook", publish_form.facebook.data),
            ("instagram", publish_form.instagram.data),
            ("pinterest", publish_form.pinterest.data),
            ("deviantart", publish_form.deviantart.data),
        ) if on]
        if not platforms:
            flash("Choisissez au moins un réseau.", "info")
        else:
            message = publish_form.message.data.strip()
            results = publish_social(platforms, title=title, message=message, image_url=image_url, link=link)
            payload = {
                "message": message,
                "image_url": image_url,
                "image_name": (publish_form.image_name.data or "").strip(),
                "alt": (publish_form.alt_text.data or "").strip(),
                "prompt": (publish_form.prompt.data or "").strip(),
                "design": _loads(publish_form.design_json.data) or {"headline": title},
            }
            for item in results:
                log_publication(item, platform=item["platform"], draft=payload, work=work)
            db.session.commit()
            ok = sum(1 for item in results if item.get("ok"))
            flash(f"{ok}/{len(results)} publication(s) réussie(s).", "ok" if ok else "info")
            for item in results:
                if not item.get("ok"):
                    flash(f"{item['platform']} : {item.get('error')}", "info")
            return redirect(url_for("admin.social"))

    return render_template(
        "admin/social.html",
        form=publish_form,
        compose_form=compose_form,
        draft=draft,
        works=works,
        mistral_ok=mistral_ready(),
        status=platform_status(),
        logs=SocialPost.query.order_by(SocialPost.created_at.desc()).limit(20).all(),
        boards=Pinterest.boards() if Pinterest.status().get("connected") else [],
    )


@admin_bp.route("/social/oauth/<platform>")
@admin_required
def social_oauth_start(platform: str):
    if platform == "deviantart":
        url, state, verifier = DeviantArt.authorize_url()
        session["oauth_platform"] = "deviantart"
        session["oauth_state"] = state
        session["oauth_verifier"] = verifier
        return redirect(url)
    if platform == "pinterest":
        url, state = Pinterest.authorize_url()
        session["oauth_platform"] = "pinterest"
        session["oauth_state"] = state
        return redirect(url)
    abort(404)


@admin_bp.route("/social/oauth/<platform>/callback")
@admin_required
def social_oauth_callback(platform: str):
    if session.get("oauth_platform") != platform or session.get("oauth_state") != request.args.get("state"):
        flash("OAuth interrompu. Recommencez la connexion.", "info")
        return redirect(url_for("admin.social"))
    code = request.args.get("code") or ""
    try:
        if platform == "deviantart":
            DeviantArt.exchange(code, session.get("oauth_verifier") or "")
        elif platform == "pinterest":
            Pinterest.exchange(code)
        else:
            abort(404)
        flash(f"{platform} connecté.", "ok")
    except Exception as exc:
        flash(str(exc), "info")
    session.pop("oauth_platform", None)
    session.pop("oauth_state", None)
    session.pop("oauth_verifier", None)
    return redirect(url_for("admin.social"))


@admin_bp.route("/social/disconnect/<platform>", methods=["POST"])
@admin_required
def social_disconnect(platform: str):
    delete_token(platform)
    flash(f"{platform} déconnecté.", "ok")
    return redirect(url_for("admin.social"))
