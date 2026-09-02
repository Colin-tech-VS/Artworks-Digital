from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from artworks.extensions import db
from artworks.forms import LoginForm, RegisterForm
from artworks.models import Artist
from artworks.slugs import unique_slug

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/inscription", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("atelier.overview"))

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if Artist.query.filter_by(email=email).first():
            form.email.errors.append("Cet e-mail a déjà un atelier.")
        else:
            artist = Artist(
                email=email,
                display_name=form.display_name.data.strip(),
                slug=unique_slug(form.display_name.data),
                contact_email=email,
            )
            artist.set_password(form.password.data)
            db.session.add(artist)
            db.session.commit()
            login_user(artist)
            flash("Atelier ouvert. Préparez la salle, puis publiez.", "ok")
            return redirect(url_for("atelier.gallery"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/connexion", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("atelier.overview"))

    form = LoginForm()
    if form.validate_on_submit():
        artist = Artist.query.filter_by(email=form.email.data.strip().lower()).first()
        if artist and artist.check_password(form.password.data):
            login_user(artist, remember=True)
            nxt = request.args.get("next")
            return redirect(nxt or url_for("atelier.overview"))
        form.password.errors.append("E-mail ou mot de passe incorrect.")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/deconnexion")
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.home"))
