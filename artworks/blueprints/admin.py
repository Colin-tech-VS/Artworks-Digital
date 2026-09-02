from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from markupsafe import Markup

from artworks.admin_auth import admin_logout, require_admin, try_admin_login
from artworks.analytics import breakdown, kpis, series, sparkline_svg, top_paths
from artworks.extensions import db
from artworks.forms import AdminLoginForm, ComposeForm
from artworks.mailer import mail_configured, send_email
from artworks.models import Artist, MailMessage, PageView, Work


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        blocked = require_admin()
        if blocked is not None:
            return blocked
        return fn(*args, **kwargs)

    return wrapped


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
        ok, error = send_email(form.to_email.data.strip(), form.subject.data.strip(), form.body.data.strip())
        message = MailMessage(
            direction="out",
            kind="admin",
            status="sent" if ok else "failed",
            from_name="Artworksdigital",
            from_email="hello@artworksdigital.fr",
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
        ok, error = send_email(
            form.to_email.data.strip(),
            form.subject.data.strip(),
            form.body.data.strip(),
            reply_to="hello@artworksdigital.fr",
        )
        reply = MailMessage(
            artist_id=message.artist_id,
            direction="out",
            kind="admin",
            status="sent" if ok else "failed",
            from_name="Artworksdigital",
            from_email="hello@artworksdigital.fr",
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
