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


class ForgotPasswordForm(FlaskForm):
    email = StringField(
        "E-mail du compte",
        validators=[DataRequired(), Email(message="Adresse e-mail invalide."), Length(max=180)],
    )


class ResetPasswordForm(FlaskForm):
    password = PasswordField("Nouveau mot de passe", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        "Confirmation",
        validators=[DataRequired(), EqualTo("password", message="Les mots de passe ne correspondent pas.")],
    )


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
    hang_style = SelectField(
        "Accrochage",
        choices=[("grille", "Grille"), ("salon", "Salon — plus d’air, plus grand")],
        default="grille",
        validators=[Optional()],
    )
    featured_work_id = SelectField("Œuvre en avant", validators=[Optional()])
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


class SocialPublishForm(FlaskForm):
    work_id = IntegerField("Œuvre", validators=[Optional()])
    title = StringField("Titre", validators=[Optional(), Length(max=120)])
    message = TextAreaField("Texte", validators=[DataRequired(), Length(min=4, max=2000)])
    link = StringField("Lien", validators=[Optional(), Length(max=400)])
    image_url = StringField("Image (URL)", validators=[Optional(), Length(max=400)])
    image_name = StringField("Visuel généré", validators=[Optional(), Length(max=80)])
    alt_text = StringField("Description de l’image", validators=[Optional(), Length(max=400)])
    prompt = StringField("Consigne d’origine", validators=[Optional(), Length(max=1000)])
    design_json = StringField("Brief visuel", validators=[Optional(), Length(max=2000)])
    facebook = BooleanField("Facebook", default=True)
    instagram = BooleanField("Instagram", default=True)
    pinterest = BooleanField("Pinterest")
    deviantart = BooleanField("DeviantArt")


class SocialComposeForm(FlaskForm):
    """Le prompt qui déclenche Mistral, et le cadre qu’on lui impose."""

    prompt = TextAreaField(
        "Consigne",
        validators=[DataRequired(), Length(min=4, max=1200)],
    )
    work_id = SelectField("Œuvre", validators=[Optional()])
    platform = SelectField(
        "Réseau visé",
        choices=[("instagram", "Instagram"), ("facebook", "Facebook"), ("pinterest", "Pinterest"), ("deviantart", "DeviantArt")],
        default="instagram",
    )
    fmt = SelectField(
        "Format",
        choices=[
            ("", "Automatique selon le réseau"),
            ("square", "Carré 1080×1080"),
            ("portrait", "Portrait 1080×1350"),
            ("landscape", "Paysage 1200×630"),
            ("story", "Story 1080×1920"),
        ],
        default="",
        validators=[Optional()],
    )
    layout = SelectField(
        "Mise en page",
        choices=[
            ("", "Laisser Mistral choisir"),
            ("gallery", "Œuvre encadrée + cartel"),
            ("artwork", "Œuvre plein cadre"),
            ("editorial", "Éditorial (sans image)"),
            ("quote", "Citation"),
            ("poster", "Affiche"),
        ],
        default="",
        validators=[Optional()],
    )
    use_artwork = BooleanField("Utiliser le visuel de l’œuvre", default=True)
    heavy = BooleanField("Modèle avancé (mistral-large)")


class AtelierAIForm(FlaskForm):
    """L’atelier : une consigne, une œuvre, un cadre."""

    prompt = TextAreaField("Consigne", validators=[DataRequired(), Length(min=4, max=1200)])
    work_id = SelectField("Œuvre", validators=[Optional()])
    fmt = SelectField(
        "Format",
        choices=[
            ("square", "Carré 1080×1080 — Instagram"),
            ("portrait", "Portrait 1080×1350 — Instagram"),
            ("landscape", "Paysage 1200×630 — Facebook"),
            ("story", "Story 1080×1920"),
        ],
        default="square",
    )
    layout = SelectField(
        "Mise en page",
        choices=[
            ("", "Laisser l’IA choisir"),
            ("gallery", "Œuvre encadrée + cartel"),
            ("artwork", "Œuvre plein cadre"),
            ("editorial", "Éditorial (sans image)"),
            ("quote", "Citation"),
            ("poster", "Affiche"),
        ],
        default="",
        validators=[Optional()],
    )
    platform = SelectField(
        "Réseau",
        choices=[
            ("instagram", "Instagram"),
            ("facebook", "Facebook"),
            ("pinterest", "Pinterest"),
        ],
        default="instagram",
        validators=[Optional()],
    )


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
