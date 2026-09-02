from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import BooleanField, PasswordField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional


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
    visible = BooleanField("Accrocher dans la galerie", default=True)

    def require_image(self) -> None:
        self.image.validators = [
            FileRequired("Un visuel est nécessaire pour accrocher l’œuvre."),
            FileAllowed(["jpg", "jpeg", "png", "webp"], "Image uniquement."),
        ]
