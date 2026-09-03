from flask import Blueprint, abort, g, jsonify, make_response, redirect, render_template, request, url_for

from artworks.extensions import db
from artworks.emails import notify_admin_contact, send_contact_receipt, send_new_message
from artworks.forms import ContactForm
from artworks.gate import site_is_open, try_unlock
from artworks.mailer import contact_inbox
from artworks.models import Artist, MailMessage, Work, utcnow
from artworks.search import (
    directory_facets,
    hung_works_by_artist,
    open_rooms,
    public_work_counts,
    room_haystack,
    room_letter,
    rooms_index,
    search_rooms,
)
from artworks.seo import canonical_url


public_bp = Blueprint("public", __name__)


@public_bp.route("/", methods=["GET", "POST"])
def home():
    if not site_is_open():
        error = False
        if request.method == "POST":
            if try_unlock(request.form.get("key") or ""):
                return redirect(url_for("public.home"))
            error = True
        return render_template("public/coming_soon.html", gate_error=error)
    rooms = open_rooms()
    featured = [artist for artist in rooms if artist.has_feature("featured")][:6]
    g.track_title = "Artworksdigital"
    return render_template(
        "public/home.html",
        rooms=rooms,
        featured_rooms=featured,
        room_counts=public_work_counts(rooms),
    )


@public_bp.route("/galeries")
def galleries():
    rooms = open_rooms()
    query = (request.args.get("q") or request.args.get("query") or "").strip()
    shown = search_rooms(rooms, query) if query else rooms
    shown_ids = {artist.id for artist in shown}
    facets = directory_facets(rooms)
    letter_ids = {}
    for artist in rooms:
        letter = room_letter(artist.display_name)
        letter_ids.setdefault(letter, artist.id)
    g.track_title = "Recherche de salles" if query else "Galeries"
    return render_template(
        "public/galleries.html",
        rooms=rooms,
        shown=shown,
        shown_ids=shown_ids,
        query=query,
        room_counts=public_work_counts(rooms),
        letters=facets["letters"],
        disciplines=facets["disciplines"],
        letter_ids=letter_ids,
        room_haystack=room_haystack,
        room_letter=room_letter,
    )


@public_bp.route("/recherche")
def search():
    """Ancienne adresse et cible OpenSearch : tout mène au répertoire."""
    query = (request.args.get("q") or request.args.get("query") or "").strip()
    target = url_for("public.galleries", q=query) if query else url_for("public.galleries")
    return redirect(target, code=301)


@public_bp.route("/galeries.json")
def rooms_feed():
    rooms = open_rooms()
    body = jsonify({"rooms": rooms_index(rooms), "count": len(rooms)})
    body.headers["Cache-Control"] = "public, max-age=120"
    return body


@public_bp.route("/opensearch.xml")
def opensearch():
    body = render_template(
        "public/opensearch.xml",
        search_url=canonical_url("/galeries") + "?q={searchTerms}",
        suggest_url=canonical_url("/galeries.json"),
    )
    return body, 200, {"Content-Type": "application/opensearchdescription+xml; charset=utf-8"}


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
    spotlight = artist.featured_work(works)
    hang = [work for work in works if spotlight is None or work.id != spotlight.id]
    groups = None
    if artist.has_feature("collections"):
        groups = {}
        for work in hang:
            groups.setdefault(work.collection_name or "Accrochage", []).append(work)
        if not groups:
            groups = None
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
        works=hang,
        all_works=works,
        spotlight=spotlight,
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

    rooms = open_rooms()
    hung = hung_works_by_artist(rooms)
    freshest = max((artist.updated_at or artist.created_at for artist in rooms), default=utcnow())
    pages = [
        {"loc": canonical_url("/"), "changefreq": "daily", "priority": "1.0", "lastmod": freshest, "images": []},
        {"loc": canonical_url("/galeries"), "changefreq": "daily", "priority": "0.9", "lastmod": freshest, "images": []},
        {"loc": canonical_url("/offres"), "changefreq": "weekly", "priority": "0.8", "lastmod": utcnow(), "images": []},
        {"loc": canonical_url("/contact"), "changefreq": "monthly", "priority": "0.5", "lastmod": utcnow(), "images": []},
        {"loc": canonical_url("/llms.txt"), "changefreq": "monthly", "priority": "0.3", "lastmod": utcnow(), "images": []},
    ]
    for artist in rooms:
        works = hung.get(artist.id, [])
        room_images = []
        if artist.cover_path:
            room_images.append({
                "loc": absolute_media(artist.cover_path),
                "title": f"Galerie de {artist.display_name}",
                "caption": artist.seo_description,
            })
        room_images.extend(
            {
                "loc": absolute_media(work.image_path),
                "title": f"{work.title} — {artist.display_name}",
                "caption": " — ".join(part for part in (work.title, artist.display_name, work.cartel) if part),
            }
            for work in works[:40]
        )
        pages.append({
            "loc": canonical_url(url_for("public.gallery", slug=artist.slug)),
            "changefreq": "weekly",
            "priority": "0.95" if artist.has_feature("priority") else ("0.9" if artist.has_feature("featured") else "0.85"),
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
                    "title": f"{work.title} — {artist.display_name}",
                    "caption": " — ".join(part for part in (work.title, artist.display_name, work.cartel) if part),
                }],
            })
    response = make_response(render_template("public/sitemap.xml", pages=pages))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.headers["Cache-Control"] = "public, max-age=1800"
    return response


@public_bp.route("/robots.txt")
def robots():
    body = render_template(
        "public/robots.txt",
        sitemap=canonical_url("/sitemap.xml"),
        llms=canonical_url("/llms.txt"),
    )
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


@public_bp.route("/llms.txt")
def llms():
    """Fichier pour les moteurs génératifs : qui nous sommes, sans jargon."""
    body = render_template("public/llms.txt", contact=contact_inbox())
    return body, 200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
    }
