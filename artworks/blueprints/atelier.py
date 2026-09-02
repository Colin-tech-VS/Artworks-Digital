from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from markupsafe import Markup

from artworks.analytics import artist_series, sparkline_svg
from artworks.extensions import db
from artworks.forms import AccountForm, ComposeForm, GalleryForm, PasswordForm, WorkForm
from artworks.images import remove_image, save_image
from artworks.mailer import send_email
from artworks.models import Artist, MailMessage, Work
from artworks.plans import active_offers, get_offer
from artworks.slugs import unique_slug
from artworks.stripe_billing import cancel_to_free, checkout_url, portal_url, stripe_ready

atelier_bp = Blueprint("atelier", __name__, url_prefix="/atelier")


def _work_stats():
    works = current_user.works.order_by(Work.position.asc(), Work.id.desc()).all()
    return {
        "works": works,
        "hung": current_user.hung_count,
        "reserve": current_user.reserve_count,
        "views": current_user.views_total,
        "unread": current_user.unread_count,
        "offer": current_user.offer,
        "can_add": current_user.can_add_work(),
    }


@atelier_bp.route("/")
@login_required
def overview():
    stats = _work_stats()
    recent = stats["works"][:6]
    trend = artist_series(current_user.id, 14)
    return render_template(
        "atelier/overview.html",
        recent=recent,
        spark=Markup(sparkline_svg(trend)),
        trend_total=sum(trend),
        **stats,
    )


@atelier_bp.route("/accrochage")
@login_required
def studio():
    stats = _work_stats()
    return render_template("atelier/studio.html", **stats)


@atelier_bp.route("/publier", methods=["POST"])
@login_required
def toggle_publish():
    current_user.published = not current_user.published
    current_user.touch()
    db.session.commit()
    flash("Galerie ouverte." if current_user.published else "Galerie fermée au public.", "ok")
    return redirect(request.referrer or url_for("atelier.overview"))


@atelier_bp.route("/offre")
@login_required
def billing():
    return render_template(
        "atelier/billing.html",
        offers=active_offers(),
        current=current_user.offer,
        stripe_ok=stripe_ready(),
        unread=current_user.unread_count,
    )


@atelier_bp.route("/offre/prendre/<plan_key>", methods=["POST"])
@login_required
def billing_take(plan_key: str):
    offer = get_offer(plan_key)
    if offer is None or not offer.active:
        flash("Cette offre n’est plus proposée.", "info")
        return redirect(url_for("atelier.billing"))
    if offer.price_cents <= 0:
        ok, message = cancel_to_free(current_user)
        flash(message, "ok" if ok else "info")
        return redirect(url_for("atelier.billing"))
    if not stripe_ready() or not offer.stripe_price_id:
        flash("Le paiement Stripe n’est pas encore ouvert. Un admin peut activer l’offre à la main.", "info")
        return redirect(url_for("atelier.billing"))
    try:
        return redirect(checkout_url(current_user, offer))
    except Exception as exc:
        flash(str(exc), "info")
        return redirect(url_for("atelier.billing"))


@atelier_bp.route("/offre/portail", methods=["POST"])
@login_required
def billing_portal():
    try:
        return redirect(portal_url(current_user))
    except Exception as exc:
        flash(str(exc), "info")
        return redirect(url_for("atelier.billing"))


@atelier_bp.route("/offre/retour")
@login_required
def billing_return():
    flash("Paiement reçu. L’offre se met à jour dès la confirmation Stripe.", "ok")
    return redirect(url_for("atelier.billing"))


@atelier_bp.route("/stats")
@login_required
def stats():
    if not current_user.has_feature("stats"):
        flash("Les statistiques sont incluses à partir de l’offre Artiste.", "info")
        return redirect(url_for("atelier.billing"))
    trend = artist_series(current_user.id, 28 if current_user.has_feature("advanced_stats") else 14)
    return render_template(
        "atelier/stats.html",
        spark=Markup(sparkline_svg(trend, 520, 120)),
        trend=trend,
        trend_total=sum(trend),
        advanced=current_user.has_feature("advanced_stats"),
        unread=current_user.unread_count,
        offer=current_user.offer,
        views=current_user.views_total,
        hung=current_user.hung_count,
    )


@atelier_bp.route("/ia")
@login_required
def ai_tools():
    if not current_user.has_feature("ai"):
        flash("L’IA est incluse dans Pro et Studio.", "info")
        return redirect(url_for("atelier.billing"))
    works = current_user.works.order_by(Work.position.asc()).limit(8).all()
    draft = ""
    if works:
        titles = ", ".join(work.title for work in works[:4])
        draft = (
            f"{current_user.display_name} compose une salle autour de {titles}. "
            "L’accrochage cherche une tension minimale : matière, lumière, silence."
        )
    return render_template(
        "atelier/ai.html",
        unread=current_user.unread_count,
        offer=current_user.offer,
        advanced=current_user.has_feature("priority"),
        draft=draft,
        works=works,
    )


@atelier_bp.route("/collections")
@login_required
def collections():
    if not current_user.has_feature("collections"):
        flash("Les collections sont réservées à l’offre Studio.", "info")
        return redirect(url_for("atelier.billing"))
    groups = {}
    for work in current_user.works.order_by(Work.position.asc()):
        groups.setdefault(work.collection_name or "Sans collection", []).append(work)
    return render_template(
        "atelier/collections.html",
        groups=groups,
        unread=current_user.unread_count,
        offer=current_user.offer,
    )


@atelier_bp.route("/galerie", methods=["GET", "POST"])
@login_required
def gallery():
    form = GalleryForm(obj=current_user)
    if form.validate_on_submit():
        current_user.display_name = form.display_name.data.strip()
        current_user.slug = unique_slug(form.slug.data, artist_id=current_user.id)
        current_user.discipline = (form.discipline.data or "").strip()
        current_user.location = (form.location.data or "").strip()
        current_user.contact_email = (form.contact_email.data or "").strip()
        current_user.statement = (form.statement.data or "").strip()
        current_user.published = bool(form.published.data)
        current_user.touch()
        if form.cover.data:
            if not current_user.has_feature("customize"):
                form.cover.errors.append("La personnalisation de la salle est incluse à partir de l’offre Artiste.")
                return render_template("atelier/gallery.html", form=form, unread=current_user.unread_count)
            try:
                remove_image(current_user.cover_path)
                current_user.cover_path = save_image(form.cover.data, max_side=2800)
            except ValueError as exc:
                form.cover.errors.append(str(exc))
                return render_template("atelier/gallery.html", form=form, unread=current_user.unread_count)
        db.session.commit()
        flash("La salle est à jour.", "ok")
        return redirect(url_for("atelier.gallery"))
    return render_template("atelier/gallery.html", form=form, unread=current_user.unread_count)


@atelier_bp.route("/compte", methods=["GET", "POST"])
@login_required
def account():
    email_form = AccountForm(obj=current_user)
    password_form = PasswordForm()
    posted = request.form

    if request.method == "POST" and posted.get("form_name") == "email":
        if email_form.validate():
            email = email_form.email.data.strip().lower()
            taken = Artist.query.filter(Artist.email == email, Artist.id != current_user.id).first()
            if taken:
                email_form.email.errors.append("Cet e-mail est déjà utilisé.")
            else:
                current_user.email = email
                current_user.touch()
                db.session.commit()
                flash("E-mail mis à jour.", "ok")
                return redirect(url_for("atelier.account"))
    elif request.method == "POST" and posted.get("form_name") == "password":
        if password_form.validate():
            if not current_user.check_password(password_form.current.data):
                password_form.current.errors.append("Mot de passe actuel incorrect.")
            else:
                current_user.set_password(password_form.password.data)
                db.session.commit()
                flash("Mot de passe mis à jour.", "ok")
                return redirect(url_for("atelier.account"))

    return render_template(
        "atelier/account.html",
        email_form=email_form,
        password_form=password_form,
        unread=current_user.unread_count,
    )


@atelier_bp.route("/messages")
@login_required
def messages():
    inbox = (
        current_user.messages.filter_by(direction="in")
        .order_by(MailMessage.created_at.desc())
        .all()
    )
    sent = (
        current_user.messages.filter_by(direction="out")
        .order_by(MailMessage.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "atelier/messages.html",
        inbox=inbox,
        sent=sent,
        unread=current_user.unread_count,
    )


@atelier_bp.route("/messages/<int:message_id>", methods=["GET", "POST"])
@login_required
def message_detail(message_id: int):
    message = current_user.messages.filter_by(id=message_id).first_or_404()
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
            reply_to=current_user.contact_email or current_user.email,
        )
        reply = MailMessage(
            artist_id=current_user.id,
            direction="out",
            kind="contact",
            status="sent" if ok else "failed",
            from_name=current_user.display_name,
            from_email=current_user.contact_email or current_user.email,
            to_name=message.from_name,
            to_email=form.to_email.data.strip().lower(),
            subject=form.subject.data.strip(),
            body=form.body.data.strip(),
            is_read=True,
        )
        db.session.add(reply)
        db.session.commit()
        flash("Réponse envoyée." if ok else f"Réponse enregistrée. {error}", "ok" if ok else "info")
        return redirect(url_for("atelier.messages"))
    return render_template(
        "atelier/message.html",
        message=message,
        form=form,
        unread=current_user.unread_count,
    )


@atelier_bp.route("/oeuvres/nouvelle", methods=["GET", "POST"])
@login_required
def new_work():
    if not current_user.can_add_work():
        flash(f"Plafond atteint ({current_user.offer.works_label}). Passez à une offre supérieure.", "info")
        return redirect(url_for("atelier.billing"))
    form = WorkForm()
    form.require_image()
    if form.validate_on_submit():
        try:
            path = save_image(form.image.data)
        except ValueError as exc:
            form.image.errors.append(str(exc))
            return render_template("atelier/work.html", form=form, work=None, unread=current_user.unread_count)

        last = current_user.works.order_by(Work.position.desc()).first()
        work = Work(
            artist_id=current_user.id,
            title=form.title.data.strip(),
            year=(form.year.data or "").strip(),
            medium=(form.medium.data or "").strip(),
            dimensions=(form.dimensions.data or "").strip(),
            note=(form.note.data or "").strip(),
            image_path=path,
            visible=bool(form.visible.data),
            collection_name=(form.collection_name.data or "").strip() if current_user.has_feature("collections") else "",
            position=(last.position + 1) if last else 0,
        )
        current_user.touch()
        db.session.add(work)
        db.session.commit()
        flash("Œuvre accrochée.", "ok")
        return redirect(url_for("atelier.studio"))
    return render_template("atelier/work.html", form=form, work=None, unread=current_user.unread_count)


@atelier_bp.route("/oeuvres/<int:work_id>", methods=["GET", "POST"])
@login_required
def edit_work(work_id: int):
    work = current_user.works.filter_by(id=work_id).first_or_404()
    form = WorkForm(obj=work)
    if form.validate_on_submit():
        work.title = form.title.data.strip()
        work.year = (form.year.data or "").strip()
        work.medium = (form.medium.data or "").strip()
        work.dimensions = (form.dimensions.data or "").strip()
        work.note = (form.note.data or "").strip()
        work.visible = bool(form.visible.data)
        if current_user.has_feature("collections"):
            work.collection_name = (form.collection_name.data or "").strip()
        work.touch()
        current_user.touch()
        if form.image.data:
            try:
                remove_image(work.image_path)
                work.image_path = save_image(form.image.data)
            except ValueError as exc:
                form.image.errors.append(str(exc))
                return render_template("atelier/work.html", form=form, work=work, unread=current_user.unread_count)
        db.session.commit()
        flash("Cartel mis à jour.", "ok")
        return redirect(url_for("atelier.studio"))
    return render_template("atelier/work.html", form=form, work=work, unread=current_user.unread_count)


@atelier_bp.route("/oeuvres/<int:work_id>/retirer", methods=["POST"])
@login_required
def delete_work(work_id: int):
    work = current_user.works.filter_by(id=work_id).first_or_404()
    remove_image(work.image_path)
    db.session.delete(work)
    current_user.touch()
    db.session.commit()
    flash("Œuvre retirée de l’accrochage.", "ok")
    return redirect(url_for("atelier.studio"))


@atelier_bp.route("/oeuvres/<int:work_id>/deplacer", methods=["POST"])
@login_required
def move_work(work_id: int):
    direction = request.form.get("dir", "up")
    works = current_user.works.order_by(Work.position.asc(), Work.id.asc()).all()
    index = next((i for i, item in enumerate(works) if item.id == work_id), None)
    if index is None:
        return redirect(url_for("atelier.studio"))
    swap = index - 1 if direction == "up" else index + 1
    if 0 <= swap < len(works):
        works[index].position, works[swap].position = works[swap].position, works[index].position
        current_user.touch()
        db.session.commit()
    return redirect(url_for("atelier.studio"))


@atelier_bp.route("/oeuvres/ordonner", methods=["POST"])
@login_required
def reorder_works():
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids") or []
    works = {work.id: work for work in current_user.works.all()}
    for position, work_id in enumerate(ids):
        try:
            key = int(work_id)
        except (TypeError, ValueError):
            continue
        if key in works:
            works[key].position = position
    current_user.touch()
    db.session.commit()
    return jsonify({"ok": True})
