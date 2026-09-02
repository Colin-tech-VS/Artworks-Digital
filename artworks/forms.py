from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import BooleanField, IntegerField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional


class RegisterForm(FlaskForm):
    display_name = StringField(
        "Nom d’artiste",
        validators=[DataRequired(), Length(min=2, max=120)],
    )
    email = StringField(
        "E-mail",
        validators=[DataRequired(), Email(message="Adresse e-mail invalide."), Length(max=180)],
    )
    password = PasswordField("Mot de passe", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        "Confirmation",
        validators=[DataRequired(), EqualTo("password", message="Les mots de passe ne correspondent pas.")],
    )


class LoginForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email(message="Adresse e-mail invalide.")])
    password = PasswordField("Mot de passe", validators=[DataRequired()])


class GalleryForm(FlaskForm):
    display_name = StringField("Nom affiché", validators=[DataRequired(), Length(min=2, max=120)])
    slug = StringField(
        "Adresse de la galerie",
        validators=[DataRequired(), Length(min=2, max=80)],
    )
    discipline = StringField("Discipline", validators=[Optional(), Length(max=120)])
    location = StringField("Lieu", validators=[Optional(), Length(max=120)])
    contact_email = StringField(
        "E-mail de contact",
        validators=[Optional(), Email(message="Adresse e-mail invalide."), Length(max=180)],
    )
    statement = TextAreaField("Note d’intention", validators=[Optional(), Length(max=4000)])
    cover = FileField(
        "Image de salle",
        validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "webp"], "Image uniquement.")],
    )
    published = BooleanField("Publier la galerie")


class WorkForm(FlaskForm):
    title = StringField("Titre", validators=[DataRequired(), Length(max=180)])
    year = StringField("Année", validators=[Optional(), Length(max=12)])
    medium = StringField("Technique", validators=[Optional(), Length(max=160)])
    dimensions = StringField("Dimensions", validators=[Optional(), Length(max=120)])
    note = TextAreaField("Note", validators=[Optional(), Length(max=2000)])
    image = FileField("Visuel")
    collection_name = StringField("Collection", validators=[Optional(), Length(max=120)])
    visible = BooleanField("Accrocher dans la galerie", default=True)

    def require_image(self) -> None:
        self.image.validators = [
            FileRequired("Un visuel est nécessaire pour accrocher l’œuvre."),
            FileAllowed(["jpg", "jpeg", "png", "webp"], "Image uniquement."),
        ]


class AccountForm(FlaskForm):
    email = StringField(
        "E-mail de connexion",
        validators=[DataRequired(), Email(message="Adresse e-mail invalide."), Length(max=180)],
    )


class OfferForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=80)])
    badge = StringField("Badge", validators=[Optional(), Length(max=16)])
    audience = StringField("Pour qui", validators=[Optional(), Length(max=180)])
    features_text = TextAreaField("Contenu", validators=[Optional(), Length(max=2000)])
    price_cents = IntegerField("Prix (centimes)", validators=[DataRequired(), NumberRange(min=0)])
    max_works = IntegerField("Plafond d’œuvres (vide = illimité)", validators=[Optional(), NumberRange(min=1)])
    active = BooleanField("Offre active")
    allow_stats = BooleanField("Statistiques")
    allow_customize = BooleanField("Personnalisation")
    allow_share = BooleanField("Partage")
    allow_advanced_stats = BooleanField("Statistiques avancées")
    allow_featured = BooleanField("Mise en avant")
    allow_ai = BooleanField("IA")
    allow_priority = BooleanField("Visibilité prioritaire")
    allow_collections = BooleanField("Collections / multi-profils")


class AssignPlanForm(FlaskForm):
    plan_key = SelectField("Offre", validators=[DataRequired()])


class AdminLoginForm(FlaskForm):
    username = StringField("Identifiant", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Mot de passe", validators=[DataRequired(), Length(max=128)])


class ContactForm(FlaskForm):
    name = StringField("Votre nom", validators=[DataRequired(), Length(max=120)])
    email = StringField(
        "Votre e-mail",
        validators=[DataRequired(), Email(message="Adresse e-mail invalide."), Length(max=180)],
    )
    message = TextAreaField("Message", validators=[DataRequired(), Length(min=8, max=4000)])


class ComposeForm(FlaskForm):
    to_email = StringField(
        "Destinataire",
        validators=[DataRequired(), Email(message="Adresse e-mail invalide."), Length(max=180)],
    )
    subject = StringField("Objet", validators=[DataRequired(), Length(max=200)])
    body = TextAreaField("Message", validators=[DataRequired(), Length(min=4, max=8000)])


class PasswordForm(FlaskForm):
    current = PasswordField("Mot de passe actuel", validators=[DataRequired()])
    password = PasswordField("Nouveau mot de passe", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        "Confirmation",
        validators=[DataRequired(), EqualTo("password", message="Les mots de passe ne correspondent pas.")],
    )
