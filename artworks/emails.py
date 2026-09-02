"""E-mails transactionnels — une seule mise en page, un seul ton.

Chaque envoi est aussi archivé dans ``MailMessage`` : l’admin retrouve dans sa
boîte tout ce que la plateforme a envoyé, même quand le SMTP est absent.
"""

from contextvars import ContextVar

from flask import render_template, url_for

from artworks.extensions import db
from artworks.mailer import contact_inbox, send_email
from artworks.models import Artist, MailMessage
from artworks.seo import canonical_url


# Pendant un aperçu, ``deliver`` met la page en mémoire au lieu de l’envoyer.
_capture: ContextVar[dict | None] = ContextVar("artworks_email_capture", default=None)


def site_url() -> str:
    return canonical_url("/").rstrip("/")


def _text_version(
    title: str,
    paragraphs: list[str],
    details: list[tuple[str, str]] | None,
    quote: str,
    cta_url: str,
    cta_label: str,
    outro: str,
) -> str:
    lines = [title, "=" * min(len(title), 60), ""]
    lines.extend(paragraphs)
    if details:
        lines.append("")
        lines.extend(f"{label} : {value}" for label, value in details)
    if quote:
        lines.extend(["", *(f"> {row}" for row in quote.splitlines())])
    if cta_url:
        lines.extend(["", f"{cta_label or 'Ouvrir'} : {cta_url}"])
    if outro:
        lines.extend(["", outro])
    lines.extend(["", "— L’équipe Artworksdigital", site_url()])
    return "\n".join(lines)


def deliver(
    to_email: str,
    subject: str,
    *,
    title: str,
    paragraphs: list[str],
    eyebrow: str = "",
    preheader: str = "",
    details: list[tuple[str, str]] | None = None,
    quote: str = "",
    cta_url: str = "",
    cta_label: str = "",
    cta_hint: str = "",
    outro: str = "",
    footer_note: str = "",
    reply_to: str = "",
    artist: Artist | None = None,
    kind: str = "system",
    to_name: str = "",
    log: bool = True,
) -> tuple[bool, str]:
    """Met en page, envoie, puis archive. Ne lève jamais : un e-mail raté ne
    doit pas casser l’inscription ou le paiement qui l’a déclenché."""
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "Destinataire manquant."

    html = ""
    try:
        html = render_template(
            "emails/message.html",
            title=title,
            eyebrow=eyebrow,
            preheader=preheader or (paragraphs[0] if paragraphs else title),
            paragraphs=paragraphs,
            details=details or [],
            quote=quote,
            cta_url=cta_url,
            cta_label=cta_label,
            cta_hint=cta_hint,
            outro=outro,
            footer_note=footer_note,
            site_url=site_url(),
        )
    except Exception:
        html = ""

    sink = _capture.get()
    if sink is not None:
        sink.setdefault("html", html)
        sink.setdefault("subject", subject)
        sink.setdefault("to_email", to_email)
        return True, ""

    text = _text_version(title, paragraphs, details, quote, cta_url, cta_label, outro)

    try:
        ok, error = send_email(to_email, subject, text, reply_to=reply_to, html=html)
    except Exception as exc:  # pragma: no cover - défense
        ok, error = False, str(exc)[:240]

    if log:
        try:
            row = MailMessage(
                artist_id=artist.id if artist else None,
                direction="out",
                kind=kind,
                status="sent" if ok else "failed",
                from_name="Artworksdigital",
                from_email=contact_inbox(),
                to_name=to_name or (artist.display_name if artist else ""),
                to_email=to_email.lower()[:180],
                subject=subject[:200],
                body=text[:8000],
                is_read=True,
            )
            db.session.add(row)
            db.session.commit()
        except Exception:
            db.session.rollback()
    return ok, error


# ---------------------------------------------------------------- comptes


def send_welcome(artist: Artist) -> None:
    deliver(
        artist.email,
        "Votre atelier est ouvert — Artworksdigital",
        eyebrow="Bienvenue",
        title=f"L’atelier de {artist.display_name} est ouvert.",
        paragraphs=[
            "Votre compte est créé. L’atelier est privé : vous y préparez la salle, "
            "puis vous décidez du moment où elle ouvre au public.",
            "Trois gestes suffisent pour commencer : nommer la salle, écrire la note "
            "d’intention, accrocher une première œuvre.",
        ],
        details=[
            ("Compte", artist.email),
            ("Offre", artist.offer.name if artist.offer else "Découverte"),
            ("Adresse publique", f"{site_url()}/galerie/{artist.slug}"),
        ],
        cta_url=canonical_url(url_for("atelier.overview")),
        cta_label="Entrer dans l’atelier",
        outro="Tant que la galerie n’est pas publiée, personne ne peut la voir.",
        artist=artist,
        kind="welcome",
    )


def send_password_reset(artist: Artist, reset_url: str) -> tuple[bool, str]:
    return deliver(
        artist.email,
        "Réinitialiser votre mot de passe — Artworksdigital",
        eyebrow="Sécurité",
        title="Un nouveau mot de passe.",
        paragraphs=[
            f"Bonjour {artist.display_name}, une réinitialisation a été demandée pour ce compte.",
            "Ce lien est valable une heure et ne fonctionne qu’une seule fois.",
        ],
        cta_url=reset_url,
        cta_label="Choisir un mot de passe",
        cta_hint="Si le bouton ne s’ouvre pas, copiez ce lien :",
        outro="Vous n’avez rien demandé ? Ignorez ce message : le mot de passe actuel reste valable.",
        artist=artist,
        kind="password_reset",
    )


def send_password_changed(artist: Artist) -> None:
    deliver(
        artist.email,
        "Votre mot de passe a été modifié — Artworksdigital",
        eyebrow="Sécurité",
        title="Mot de passe modifié.",
        paragraphs=[
            "Le mot de passe de votre atelier vient d’être changé.",
            "Si ce n’est pas vous, répondez à ce message immédiatement : nous refermons l’accès.",
        ],
        cta_url=canonical_url(url_for("auth.login")),
        cta_label="Se connecter",
        reply_to=contact_inbox(),
        artist=artist,
        kind="security",
    )


def send_email_changed(artist: Artist, previous_email: str) -> None:
    for address, note in ((artist.email, "nouvelle adresse"), (previous_email, "ancienne adresse")):
        if not address:
            continue
        deliver(
            address,
            "Votre e-mail de connexion a changé — Artworksdigital",
            eyebrow="Sécurité",
            title="Adresse de connexion mise à jour.",
            paragraphs=[
                "L’adresse utilisée pour entrer dans l’atelier vient d’être modifiée.",
                "Ce message part sur les deux adresses pour que rien ne se perde.",
            ],
            details=[("Ancienne", previous_email or "—"), ("Nouvelle", artist.email)],
            outro=f"Envoyé à votre {note}. Si ce changement n’est pas le vôtre, répondez à ce message.",
            reply_to=contact_inbox(),
            artist=artist,
            kind="security",
        )


# ---------------------------------------------------------------- galerie


def send_gallery_published(artist: Artist) -> None:
    address = f"{site_url()}/galerie/{artist.slug}"
    deliver(
        artist.email,
        f"La galerie de {artist.display_name} est ouverte — Artworksdigital",
        eyebrow="Publication",
        title="La salle est ouverte.",
        paragraphs=[
            "Votre galerie est en ligne. Elle a une adresse à elle, indexable, partageable.",
            "Chaque œuvre accrochée obtient sa propre page — titre, cartel, note.",
        ],
        details=[
            ("Adresse", address),
            ("Œuvres accrochées", str(artist.hung_count)),
        ],
        cta_url=address,
        cta_label="Voir la galerie",
        artist=artist,
        kind="gallery",
    )


def send_contact_receipt(name: str, email: str, body: str, artist: Artist | None = None) -> None:
    """Accusé de réception pour la personne qui écrit depuis le site."""
    destination = artist.display_name if artist else "Artworksdigital"
    deliver(
        email,
        f"Votre message à {destination} est parti",
        eyebrow="Accusé de réception",
        title="Message reçu.",
        paragraphs=[
            f"Bonjour {name}, votre message a bien été transmis à {destination}.",
            "La réponse arrivera directement sur cette adresse.",
        ],
        quote=body[:900],
        cta_url=site_url(),
        cta_label="Découvrir les galeries",
        to_name=name,
        kind="receipt",
    )


def send_new_message(artist: Artist, from_name: str, from_email: str, body: str) -> None:
    """Prévient l’artiste qu’un visiteur lui a écrit."""
    deliver(
        artist.contact_email or artist.email,
        f"Nouveau message pour {artist.display_name}",
        eyebrow="Votre galerie",
        title="Quelqu’un vous écrit.",
        paragraphs=["Un visiteur a laissé un message depuis votre galerie."],
        details=[("De", from_name or "—"), ("E-mail", from_email or "—")],
        quote=body[:900],
        cta_url=canonical_url(url_for("atelier.messages")),
        cta_label="Répondre depuis l’atelier",
        reply_to=from_email,
        artist=artist,
        kind="notification",
    )


# ---------------------------------------------------------------- offres


def send_plan_changed(artist: Artist, offer_name: str, price_label: str) -> None:
    deliver(
        artist.email,
        f"Votre offre : {offer_name} — Artworksdigital",
        eyebrow="Abonnement",
        title=f"Vous êtes sur l’offre {offer_name}.",
        paragraphs=[
            "Le changement est actif immédiatement : les fonctionnalités correspondantes "
            "sont ouvertes dans votre atelier.",
        ],
        details=[("Offre", offer_name), ("Montant", price_label)],
        cta_url=canonical_url(url_for("atelier.billing")),
        cta_label="Voir mon offre",
        outro="La facturation se gère à tout moment depuis l’atelier.",
        artist=artist,
        kind="billing",
    )


def send_payment_failed(artist: Artist) -> None:
    deliver(
        artist.email,
        "Un paiement n’est pas passé — Artworksdigital",
        eyebrow="Abonnement",
        title="Le dernier paiement a échoué.",
        paragraphs=[
            "La banque a refusé le prélèvement de votre abonnement. La galerie reste "
            "en ligne pour l’instant.",
            "Mettre à jour le moyen de paiement suffit à tout remettre en ordre.",
        ],
        cta_url=canonical_url(url_for("atelier.billing")),
        cta_label="Mettre à jour le paiement",
        artist=artist,
        kind="billing",
    )


# ---------------------------------------------------------------- interne


def notify_admin_new_artist(artist: Artist) -> None:
    inbox = contact_inbox()
    if not inbox:
        return
    deliver(
        inbox,
        f"Nouvel atelier : {artist.display_name}",
        eyebrow="Interne",
        title="Un atelier vient d’ouvrir.",
        paragraphs=["Une inscription vient d’arriver sur la plateforme."],
        details=[
            ("Artiste", artist.display_name),
            ("E-mail", artist.email),
            ("Offre", artist.offer.name if artist.offer else "Découverte"),
        ],
        cta_url=canonical_url(url_for("admin.artists")),
        cta_label="Ouvrir l’admin",
        reply_to=artist.email,
        kind="internal",
        log=False,
    )


def notify_admin_contact(name: str, email: str, subject: str, body: str) -> tuple[bool, str]:
    return deliver(
        contact_inbox(),
        subject,
        eyebrow="Formulaire public",
        title="Message depuis le site.",
        paragraphs=["Un visiteur a écrit depuis /contact."],
        details=[("De", name), ("E-mail", email)],
        quote=body[:2000],
        cta_url=canonical_url(url_for("admin.emails")),
        cta_label="Voir la boîte",
        reply_to=email,
        kind="internal",
        log=False,
    )


# ---------------------------------------------------------------- aperçus


class _SampleOffer:
    name = "Artiste"
    price_label = "9,90 €/mois"


class _SampleArtist:
    """Artiste d’exemple pour les aperçus : aucun accès base, aucun envoi."""

    id = None
    email = "camille@exemple.fr"
    contact_email = "camille@exemple.fr"
    display_name = "Camille Roux"
    slug = "camille-roux"
    discipline = "Peinture"
    location = "Marseille"
    hung_count = 12
    offer = _SampleOffer()


def _sample_artist() -> _SampleArtist:
    return _SampleArtist()


_PREVIEW_BODY = (
    "Bonjour, je suis tombé sur votre salle hier soir et la série des grands "
    "formats m’a arrêté. Est-ce que les toiles de 2024 sont encore visibles ?"
)


def _preview_call(kind: str):
    """(fonction, arguments) pour chaque aperçu — sans effet de bord."""
    artist = _sample_artist()
    reset = canonical_url(url_for("auth.reset_password", token="apercu-de-jeton"))
    table = {
        "welcome": (send_welcome, (artist,)),
        "password_reset": (send_password_reset, (artist, reset)),
        "password_changed": (send_password_changed, (artist,)),
        "email_changed": (send_email_changed, (artist, "ancienne@exemple.fr")),
        "gallery_published": (send_gallery_published, (artist,)),
        "new_message": (send_new_message, (artist, "Jean Vasseur", "jean@exemple.fr", _PREVIEW_BODY)),
        "contact_receipt": (send_contact_receipt, ("Jean Vasseur", "jean@exemple.fr", _PREVIEW_BODY, artist)),
        "plan_changed": (send_plan_changed, (artist, "Artiste", "9,90 €/mois")),
        "payment_failed": (send_payment_failed, (artist,)),
    }
    return table.get(kind)


def preview_html(kind: str) -> str | None:
    """Rend l’e-mail sans l’envoyer ni l’archiver."""
    call = _preview_call(kind)
    if call is None:
        return None
    fn, args = call
    sink: dict[str, str] = {}
    token = _capture.set(sink)
    try:
        fn(*args)
    finally:
        _capture.reset(token)
    return sink.get("html")


def send_preview(kind: str, to_email: str) -> tuple[bool, str]:
    """Envoie un aperçu réel à une adresse, pour vérifier le rendu chez le client."""
    html = preview_html(kind)
    if html is None:
        return False, "Modèle inconnu."
    from artworks.mailer import send_email as raw_send

    text = f"Aperçu du modèle « {kind} » — Artworksdigital."
    return raw_send(to_email, f"[Aperçu] {kind} — Artworksdigital", text, html=html)
