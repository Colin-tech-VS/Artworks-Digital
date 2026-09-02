from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from artworks.emails import (
    notify_admin_new_artist,
    send_password_changed,
    send_password_reset,
    send_welcome,
)
from artworks.extensions import db
from artworks.forms import ForgotPasswordForm, LoginForm, RegisterForm, ResetPasswordForm
from artworks.models import Artist
from artworks.seo import canonical_url
from artworks.slugs import unique_slug
from artworks.tokens import make_reset_token, read_reset_token

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
                plan_key="decouverte",
            )
            artist.set_password(form.password.data)
            db.session.add(artist)
            db.session.commit()
            send_welcome(artist)
            notify_admin_new_artist(artist)
            login_user(artist)
            flash("Atelier ouvert sur l’offre Découverte. Préparez la salle, puis publiez.", "ok")
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
            if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("atelier.overview")
            return redirect(nxt)
        form.password.errors.append("E-mail ou mot de passe incorrect.")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/mot-de-passe-oublie", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("atelier.account"))

    form = ForgotPasswordForm()
    sent = False
    if form.validate_on_submit():
        artist = Artist.query.filter_by(email=form.email.data.strip().lower()).first()
        if artist is not None:
            link = canonical_url(url_for("auth.reset_password", token=make_reset_token(artist)))
            send_password_reset(artist, link)
        # Réponse identique dans les deux cas : on ne dit pas qui a un compte.
        sent = True
    return render_template("auth/forgot.html", form=form, sent=sent)


@auth_bp.route("/mot-de-passe/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    artist = read_reset_token(token)
    if artist is None:
        return render_template("auth/reset.html", form=None, expired=True), 400

    form = ResetPasswordForm()
    if form.validate_on_submit():
        artist.set_password(form.password.data)
        artist.touch()
        db.session.commit()
        send_password_changed(artist)
        flash("Mot de passe mis à jour. Vous pouvez entrer.", "ok")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form, expired=False, artist=artist)


@auth_bp.route("/deconnexion")
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.home"))
