from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from sqlalchemy import case

from artworks.extensions import db
from artworks.emails import notify_admin_contact, send_contact_receipt, send_new_message
from artworks.forms import ContactForm
from artworks.gate import site_is_open, try_unlock
from artworks.mailer import contact_inbox
from artworks.models import Artist, MailMessage, Work, utcnow
from artworks.seo import canonical_url


public_bp = Blueprint("public", __name__)


def _open_rooms():
    rank = case(
        (Artist.plan_key == "studio", 4),
        (Artist.plan_key == "pro", 3),
        (Artist.plan_key == "artiste", 2),
        else_=1,
    )
    return (
        Artist.query.filter_by(published=True)
        .order_by(rank.desc(), Artist.updated_at.desc(), Artist.created_at.desc())
        .all()
    )


@public_bp.route("/", methods=["GET", "POST"])
def home():
    if not site_is_open():
        error = False
        if request.method == "POST":
            if try_unlock(request.form.get("key") or ""):
                return redirect(url_for("public.home"))
            error = True
        return render_template("public/coming_soon.html", gate_error=error)
    g.track_title = "Artworksdigital"
    return render_template("public/home.html", rooms=_open_rooms())


@public_bp.route("/galeries")
def galleries():
    rooms = _open_rooms()
    g.track_title = "Galeries"
    return render_template("public/galleries.html", rooms=rooms)


@public_bp.route("/offres")
def offers():
    from artworks.plans import active_offers

    g.track_title = "Offres Artworksdigital"
    return render_template("public/offers.html", offers=active_offers())


@public_bp.route("/contact", methods=["GET", "POST"])
def contact():
    form = ContactForm()
    sent = False
    if form.validate_on_submit():
        body = form.message.data.strip()
        inbox = contact_inbox()
        message = MailMessage(
            direction="in",
            kind="site",
            status="inbox",
            from_name=form.name.data.strip(),
            from_email=form.email.data.strip().lower(),
            to_name="Artworksdigital",
            to_email=inbox,
            subject=f"Contact — {form.name.data.strip()}",
            body=body,
            is_read=False,
        )
        db.session.add(message)
        db.session.commit()
        notify_admin_contact(message.from_name, message.from_email, message.subject, body)
        send_contact_receipt(message.from_name, message.from_email, body)
        sent = True
        form = ContactForm()
    g.track_title = "Contact"
    return render_template("public/contact.html", form=form, sent=sent)


@public_bp.route("/galerie/<slug>", methods=["GET", "POST"])
def gallery(slug: str):
    artist = Artist.query.filter_by(slug=slug, published=True).first()
    if artist is None:
        abort(404)
    works = artist.public_works()
    groups = None
    if artist.has_feature("collections"):
        groups = {}
        for work in works:
            groups.setdefault(work.collection_name or "Accrochage", []).append(work)
    g.track_artist_id = artist.id
    g.track_title = artist.display_name
    form = ContactForm()
    if form.validate_on_submit():
        body = form.message.data.strip()
        message = MailMessage(
            artist_id=artist.id,
            direction="in",
            kind="contact",
            status="inbox",
            from_name=form.name.data.strip(),
            from_email=form.email.data.strip().lower(),
            to_name=artist.display_name,
            to_email=artist.contact_email or artist.email,
            subject=f"Message pour {artist.display_name}",
            body=body,
            is_read=False,
        )
        db.session.add(message)
        db.session.commit()
        send_new_message(artist, message.from_name, message.from_email, body)
        send_contact_receipt(message.from_name, message.from_email, body, artist=artist)
        return redirect(url_for("public.gallery", slug=artist.slug, sent=1))
    return render_template(
        "public/gallery.html",
        artist=artist,
        works=works,
        groups=groups,
        form=form,
        sent=request.args.get("sent") == "1",
    )


@public_bp.route("/galerie/<slug>/oeuvre/<int:work_id>")
def artwork(slug: str, work_id: int):
    artist = Artist.query.filter_by(slug=slug, published=True).first()
    if artist is None:
        abort(404)
    work = Work.query.filter_by(id=work_id, artist_id=artist.id, visible=True).first()
    if work is None:
        abort(404)
    work.view_count = (work.view_count or 0) + 1
    db.session.commit()
    g.track_artist_id = artist.id
    g.track_work_id = work.id
    g.track_title = f"{work.title} — {artist.display_name}"
    hung = artist.public_works()
    if not any(item.id == work.id for item in hung):
        abort(404)
    index = next((i for i, item in enumerate(hung) if item.id == work.id), 0)
    prev_work = hung[index - 1] if index > 0 else None
    next_work = hung[index + 1] if index + 1 < len(hung) else None
    return render_template(
        "public/artwork.html",
        artist=artist,
        work=work,
        prev_work=prev_work,
        next_work=next_work,
    )


@public_bp.route("/sitemap.xml")
def sitemap():
    """Plan du site, images comprises : les œuvres méritent d’être indexées
    comme images, pas seulement comme pages."""
    from artworks.seo import absolute_media

    pages = [
        {"loc": canonical_url("/"), "changefreq": "weekly", "priority": "1.0", "lastmod": utcnow(), "images": []},
        {"loc": canonical_url("/galeries"), "changefreq": "daily", "priority": "0.9", "lastmod": utcnow(), "images": []},
        {"loc": canonical_url("/offres"), "changefreq": "weekly", "priority": "0.8", "lastmod": utcnow(), "images": []},
        {"loc": canonical_url("/contact"), "changefreq": "monthly", "priority": "0.5", "lastmod": utcnow(), "images": []},
    ]
    for artist in Artist.query.filter_by(published=True).order_by(Artist.updated_at.desc()).all():
        works = artist.public_works()
        room_images = []
        if artist.cover_path:
            room_images.append({
                "loc": absolute_media(artist.cover_path),
                "title": artist.cover_alt,
                "caption": artist.cover_alt,
            })
        room_images.extend(
            {
                "loc": absolute_media(work.image_path),
                "title": work.title,
                "caption": work.image_alt,
            }
            for work in works[:20]
        )
        pages.append({
            "loc": canonical_url(url_for("public.gallery", slug=artist.slug)),
            "changefreq": "weekly",
            "priority": "0.8",
            "lastmod": artist.updated_at or artist.created_at,
            "images": room_images,
        })
        for work in works:
            pages.append({
                "loc": canonical_url(url_for("public.artwork", slug=artist.slug, work_id=work.id)),
                "changefreq": "monthly",
                "priority": "0.7",
                "lastmod": work.updated_at or work.created_at,
                "images": [{
                    "loc": absolute_media(work.image_path),
                    "title": work.title,
                    "caption": work.image_alt,
                }],
            })
    body = render_template("public/sitemap.xml", pages=pages)
    return body, 200, {"Content-Type": "application/xml; charset=utf-8"}


@public_bp.route("/robots.txt")
def robots():
    body = render_template("public/robots.txt", sitemap=canonical_url("/sitemap.xml"))
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}
