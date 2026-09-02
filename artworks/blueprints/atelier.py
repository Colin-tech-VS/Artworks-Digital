from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from artworks.extensions import db
from artworks.forms import GalleryForm, WorkForm
from artworks.images import remove_image, save_image
from artworks.models import Work
from artworks.slugs import unique_slug

atelier_bp = Blueprint("atelier", __name__, url_prefix="/atelier")


@atelier_bp.route("/")
@login_required
def studio():
    works = current_user.works.all()
    return render_template("atelier/studio.html", works=works)


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
