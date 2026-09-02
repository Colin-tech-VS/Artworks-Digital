from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from artworks.extensions import db
from artworks.forms import AccountForm, GalleryForm, PasswordForm, WorkForm
from artworks.images import remove_image, save_image
from artworks.models import Artist, Work
from artworks.slugs import unique_slug

atelier_bp = Blueprint("atelier", __name__, url_prefix="/atelier")


def _work_stats():
    works = current_user.works.order_by(Work.position.asc(), Work.id.desc()).all()
    return {
        "works": works,
        "hung": current_user.hung_count,
        "reserve": current_user.reserve_count,
        "views": current_user.views_total,
    }


@atelier_bp.route("/")
@login_required
def overview():
    stats = _work_stats()
    recent = stats["works"][:6]
    return render_template("atelier/overview.html", recent=recent, **stats)


@atelier_bp.route("/accrochage")
@login_required
def studio():
    stats = _work_stats()
    return render_template("atelier/studio.html", **stats)


@atelier_bp.route("/publier", methods=["POST"])
@login_required
def toggle_publish():
    current_user.published = not current_user.published
    db.session.commit()
    flash("Galerie ouverte." if current_user.published else "Galerie fermée au public.", "ok")
    return redirect(request.referrer or url_for("atelier.overview"))


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
        if form.cover.data:
            try:
                remove_image(current_user.cover_path)
                current_user.cover_path = save_image(form.cover.data, max_side=2800)
            except ValueError as exc:
                form.cover.errors.append(str(exc))
                return render_template("atelier/gallery.html", form=form)
        db.session.commit()
        flash("La salle est à jour.", "ok")
        return redirect(url_for("atelier.gallery"))
    return render_template("atelier/gallery.html", form=form)


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
    )


@atelier_bp.route("/oeuvres/nouvelle", methods=["GET", "POST"])
@login_required
def new_work():
    form = WorkForm()
    form.require_image()
    if form.validate_on_submit():
        try:
            path = save_image(form.image.data)
        except ValueError as exc:
            form.image.errors.append(str(exc))
            return render_template("atelier/work.html", form=form, work=None)

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
            position=(last.position + 1) if last else 0,
        )
        db.session.add(work)
        db.session.commit()
        flash("Œuvre accrochée.", "ok")
        return redirect(url_for("atelier.studio"))
    return render_template("atelier/work.html", form=form, work=None)


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
        if form.image.data:
            try:
                remove_image(work.image_path)
                work.image_path = save_image(form.image.data)
            except ValueError as exc:
                form.image.errors.append(str(exc))
                return render_template("atelier/work.html", form=form, work=work)
        db.session.commit()
        flash("Cartel mis à jour.", "ok")
        return redirect(url_for("atelier.studio"))
    return render_template("atelier/work.html", form=form, work=work)


@atelier_bp.route("/oeuvres/<int:work_id>/retirer", methods=["POST"])
@login_required
def delete_work(work_id: int):
    work = current_user.works.filter_by(id=work_id).first_or_404()
    remove_image(work.image_path)
    db.session.delete(work)
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
        db.session.commit()
    return redirect(url_for("atelier.studio"))
