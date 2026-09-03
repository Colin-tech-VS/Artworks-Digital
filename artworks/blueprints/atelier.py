from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from markupsafe import Markup

from artworks.analytics import (
    DEVICE_LABELS,
    SOURCE_LABELS,
    artist_breakdown,
    artist_cities,
    artist_series,
    artist_top_works,
    sparkline_svg,
)
from artworks.emails import (
    compose_letter,
    deliver as deliver_email,
    reading_html,
    send_email_changed,
    send_gallery_published,
    send_password_changed,
)
from artworks.extensions import db
from artworks.forms import AccountForm, AtelierAIForm, ComposeForm, GalleryForm, PasswordForm, WorkForm
from artworks.images import remove_image, save_image, save_image_sized
from artworks.models import Artist, MailMessage, PageView, Work
from artworks.plans import active_offers, get_offer
from artworks.slugs import unique_slug
from artworks.mistral import mistral_ready
from artworks.stripe_billing import cancel_to_free, checkout_url, confirm_checkout, portal_url, stripe_ready

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
    show_stats = current_user.has_feature("stats")
    trend = artist_series(current_user.id, 14) if show_stats else []
    return render_template(
        "atelier/overview.html",
        recent=recent,
        spark=Markup(sparkline_svg(trend)) if show_stats else "",
        trend_total=sum(trend) if show_stats else 0,
        show_stats=show_stats,
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
    if current_user.published:
        send_gallery_published(current_user)
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
    if not stripe_ready():
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
    session_id = (request.args.get("session_id") or "").strip()
    if session_id:
        ok, message = confirm_checkout(current_user, session_id)
        flash(message, "ok" if ok else "info")
    else:
        flash("Paiement reçu. L’offre se met à jour dès la confirmation Stripe.", "ok")
    return redirect(url_for("atelier.billing"))


@atelier_bp.route("/stats")
@login_required
def stats():
    if not current_user.has_feature("stats"):
        flash("Les statistiques sont incluses à partir de l’offre Artiste.", "info")
        return redirect(url_for("atelier.billing"))
    advanced = current_user.has_feature("advanced_stats")
    days = 28 if advanced else 14
    trend = artist_series(current_user.id, days)
    return render_template(
        "atelier/stats.html",
        spark=Markup(sparkline_svg(trend, 520, 120)),
        trend=trend,
        trend_total=sum(trend),
        advanced=advanced,
        unread=current_user.unread_count,
        offer=current_user.offer,
        views=current_user.views_total,
        hung=current_user.hung_count,
        sources=artist_breakdown(current_user.id, PageView.source, days, labels=SOURCE_LABELS) if advanced else [],
        devices=artist_breakdown(current_user.id, PageView.device, days, labels=DEVICE_LABELS) if advanced else [],
        cities=artist_cities(current_user.id, days) if advanced else [],
        top_works=artist_top_works(current_user.id, days) if advanced else [],
    )


@atelier_bp.route("/ia", methods=["GET", "POST"])
@login_required
def ai_tools():
    if not current_user.has_feature("ai"):
        flash("L’IA est incluse dans Pro et Studio.", "info")
        return redirect(url_for("atelier.billing"))

    from artworks.composer import compose
    from artworks.mistral import generate_cartel, generate_statement

    works = current_user.works.order_by(Work.position.asc()).limit(40).all()
    form = AtelierAIForm()
    form.work_id.choices = [("", "— sans œuvre —")] + [(str(work.id), work.title) for work in works]
    advanced = current_user.has_feature("priority")

    draft = None
    note = None
    cartel = None
    cartel_work_id = None
    action = request.form.get("action", "")

    if action == "note" and form.validate_on_submit():
        if not mistral_ready():
            flash("La clé Mistral n’est pas encore branchée.", "info")
        else:
            try:
                note = generate_statement(
                    current_user.display_name,
                    current_user.discipline,
                    [work.title for work in works],
                    form.prompt.data.strip(),
                    heavy=advanced,
                )
            except Exception as exc:
                flash(f"Génération impossible : {exc}", "info")
    elif action == "cartel" and advanced and form.validate_on_submit():
        work = current_user.works.filter_by(id=int(form.work_id.data)).first() if form.work_id.data else None
        if work is None:
            flash("Choisissez une œuvre pour le cartel.", "info")
        elif not mistral_ready():
            flash("La clé Mistral n’est pas encore branchée.", "info")
        else:
            try:
                cartel = generate_cartel(
                    work.title,
                    work.medium,
                    work.year,
                    work.dimensions,
                    form.prompt.data.strip(),
                    heavy=True,
                )
                cartel_work_id = work.id
            except Exception as exc:
                flash(f"Génération impossible : {exc}", "info")
    elif action == "visuel" and form.validate_on_submit():
        work = current_user.works.filter_by(id=int(form.work_id.data)).first() if form.work_id.data else None
        try:
            draft = compose(
                form.prompt.data.strip(),
                platforms=[form.platform.data or "instagram"] if advanced else ["instagram"],
                work=work,
                artist_name=current_user.display_name,
                fmt=form.fmt.data,
                layout=form.layout.data or "",
                heavy=advanced,
            )
        except Exception as exc:
            db.session.rollback()
            flash(f"Composition impossible : {exc}", "info")
        else:
            if draft["warning"]:
                flash(draft["warning"], "info")

    suggestion = ""
    if works:
        titles = ", ".join(work.title for work in works[:4])
        suggestion = (
            f"Écrire la note d’intention de la salle de {current_user.display_name}, "
            f"autour de {titles}."
        )

    return render_template(
        "atelier/ai.html",
        unread=current_user.unread_count,
        offer=current_user.offer,
        advanced=current_user.has_feature("priority"),
        form=form,
        draft=draft,
        note=note,
        cartel=cartel,
        cartel_work_id=cartel_work_id,
        suggestion=suggestion,
        works=works,
        mistral_ok=mistral_ready(),
    )


@atelier_bp.route("/ia/note", methods=["POST"])
@login_required
def ai_apply_note():
    if not current_user.has_feature("ai"):
        return redirect(url_for("atelier.billing"))
    text = (request.form.get("note") or "").strip()
    if text:
        current_user.statement = text[:4000]
        current_user.touch()
        db.session.commit()
        flash("Note d’intention enregistrée.", "ok")
    return redirect(url_for("atelier.gallery"))


@atelier_bp.route("/ia/cartel", methods=["POST"])
@login_required
def ai_apply_cartel():
    if not current_user.has_feature("priority"):
        return redirect(url_for("atelier.billing"))
    work = current_user.works.filter_by(id=int(request.form.get("work_id") or 0)).first()
    text = (request.form.get("cartel") or "").strip()
    if work and text:
        work.note = text[:2000]
        work.touch()
        current_user.touch()
        db.session.commit()
        flash("Note de cartel enregistrée.", "ok")
        return redirect(url_for("atelier.edit_work", work_id=work.id))
    return redirect(url_for("atelier.ai_tools"))


@atelier_bp.route("/kael", methods=["POST"])
@login_required
def kael_panel():
    """K.A.E.L. dans l’atelier — sur cet atelier-là, et rien d’autre.

    L’artiste ne parle pas au centre de commande de la plateforme : il
    déclenche les mêmes outils K.A.E.L., forcés sur son propre périmètre.
    Ce que voit un artiste ne peut jamais être celui d’un autre."""
    from artworks.kael import permissions
    from artworks.kael.registry import PermissionDenied
    from artworks.kael.runner import run
    from artworks.kael.tokens import Grant

    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip()
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    scopes = {permissions.READ}
    if current_user.has_feature("ai"):
        scopes.update({permissions.ANALYZE, permissions.WRITE})
    if current_user.has_feature("stats"):
        scopes.add(permissions.ANALYZE)
    grant = Grant(
        scopes=permissions.expand(scopes),
        artist_id=current_user.id,
        label=f"Atelier {current_user.display_name}",
    )

    allowed = {}
    if current_user.has_feature("ai"):
        allowed["analyze_portfolio"] = {"artist": str(current_user.id)}
        allowed["analyze_artwork"] = {}
        allowed["update_artwork"] = {}
    if current_user.has_feature("stats"):
        allowed["get_artist_stats"] = {"artist": str(current_user.id)}
    if action not in allowed:
        return jsonify({"ok": False, "error": "Cette action n’est pas incluse dans votre offre."}), 403
    if action == "update_artwork" and not current_user.has_feature("ai"):
        return jsonify({"ok": False, "error": "L’écriture assistée est incluse dans Pro et Studio."}), 403

    merged = {**params, **allowed[action]}
    try:
        return jsonify(run(action, merged, grant))
    except PermissionDenied as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception as exc:  # noqa: BLE001 — message rendu tel quel au panneau
        return jsonify({"ok": False, "error": str(exc)}), 400


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
    hung = current_user.hung_works
    form.featured_work_id.choices = [("", "— aucune —")] + [(str(work.id), work.title) for work in hung]
    if request.method == "GET":
        form.hang_style.data = current_user.hang_style or "grille"
        form.featured_work_id.data = str(current_user.featured_work_id or "")
    if form.validate_on_submit():
        was_published = current_user.published
        current_user.display_name = form.display_name.data.strip()
        current_user.slug = unique_slug(form.slug.data, artist_id=current_user.id)
        current_user.discipline = (form.discipline.data or "").strip()
        current_user.location = (form.location.data or "").strip()
        current_user.contact_email = (form.contact_email.data or "").strip()
        current_user.statement = (form.statement.data or "").strip()
        current_user.published = bool(form.published.data)
        if current_user.has_feature("present"):
            style = form.hang_style.data if form.hang_style.data in {"grille", "salon"} else "grille"
            current_user.hang_style = style
            raw_featured = form.featured_work_id.data or ""
            current_user.featured_work_id = int(raw_featured) if raw_featured.isdigit() else None
            if current_user.featured_work_id and not any(work.id == current_user.featured_work_id for work in hung):
                current_user.featured_work_id = None
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
        if current_user.published and not was_published:
            send_gallery_published(current_user)
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
                previous = current_user.email
                current_user.email = email
                current_user.touch()
                db.session.commit()
                send_email_changed(current_user, previous)
                flash("E-mail mis à jour.", "ok")
                return redirect(url_for("atelier.account"))
    elif request.method == "POST" and posted.get("form_name") == "password":
        if password_form.validate():
            if not current_user.check_password(password_form.current.data):
                password_form.current.errors.append("Mot de passe actuel incorrect.")
            else:
                current_user.set_password(password_form.password.data)
                db.session.commit()
                send_password_changed(current_user)
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
        blocks = [block.strip() for block in (form.body.data or "").split("\n\n") if block.strip()] or [
            (form.body.data or "").strip()
        ]
        html = compose_letter(
            title=form.subject.data.strip(),
            eyebrow=current_user.display_name,
            paragraphs=blocks,
            footer_note=f"Réponse envoyée depuis la galerie de {current_user.display_name}.",
        )
        ok, error = deliver_email(
            form.to_email.data.strip(),
            form.subject.data.strip(),
            eyebrow=current_user.display_name,
            title=form.subject.data.strip(),
            paragraphs=blocks,
            reply_to=current_user.contact_email or current_user.email,
            footer_note=f"Réponse envoyée depuis la galerie de {current_user.display_name}.",
            log=False,
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
            html_body=html,
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
        letter_html=reading_html(message),
        title=message.subject,
    )


@atelier_bp.route("/messages/<int:message_id>/page")
@login_required
def message_page(message_id: int):
    message = current_user.messages.filter_by(id=message_id).first_or_404()
    response = current_app.response_class(reading_html(message), mimetype="text/html")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; "
        "font-src https: data:; frame-ancestors 'self'"
    )
    return response


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
            path, width, height = save_image_sized(form.image.data)
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
            image_w=width,
            image_h=height,
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
                work.image_path, work.image_w, work.image_h = save_image_sized(form.image.data)
            except ValueError as exc:
                form.image.errors.append(str(exc))
                return render_template(
                    "atelier/work.html",
                    form=form,
                    work=work,
                    unread=current_user.unread_count,
                    kael_work_id=work.id,
                )
        db.session.commit()
        flash("Cartel mis à jour.", "ok")
        return redirect(url_for("atelier.studio"))
    return render_template(
        "atelier/work.html",
        form=form,
        work=work,
        unread=current_user.unread_count,
        kael_work_id=work.id,
    )


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
