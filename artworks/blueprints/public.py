from flask import Blueprint, abort, g, jsonify, make_response, redirect, render_template, request, url_for

from artworks.extensions import db
from artworks.emails import notify_admin_contact, send_contact_receipt, send_new_message
from artworks.forms import ContactForm
from artworks.gate import site_is_open, try_unlock
from artworks.mailer import contact_inbox
from artworks.models import Artist, MailMessage, Work, utcnow
from artworks.search import (
    directory_facets,
    discipline_slug,
    disciplines_index,
    hung_works_by_artist,
    kin_rooms,
    open_rooms,
    public_work_counts,
    room_haystack,
    room_letter,
    room_previews,
    rooms_index,
    rooms_of_discipline,
    search_rooms,
    wall_works,
)
from artworks.seo import canonical_url


public_bp = Blueprint("public", __name__)

# La lettre est datée : les moteurs — et les moteurs génératifs surtout —
# rangent une annonce par sa fraîcheur. On avance cette date quand on
# réécrit la lettre, pas à chaque déploiement.
LETTER_PUBLISHED = "2025-11-18"
LETTER_MODIFIED = "2026-09-03"

# Une seule liste de questions : la lettre l'affiche, son JSON-LD la répète,
# et `/llms.txt` la sert aux moteurs génératifs. Trois copies mentiraient.
SITE_FAQ = (
    {
        "q": "Qu’est-ce qu’Artworksdigital ?",
        "a": (
            "Artworksdigital ouvre à chaque artiste une galerie qui lui appartient : "
            "un atelier privé pour préparer la salle, une adresse publique pour la "
            "montrer. Ce n’est ni une marketplace, ni une vitrine collective."
        ),
    },
    {
        "q": "Artworksdigital vend-il des œuvres ?",
        "a": (
            "Non. Il n’y a ni panier, ni catalogue partagé, ni commission. La galerie "
            "appartient à l’artiste ; un visiteur lui écrit directement depuis la salle."
        ),
    },
    {
        "q": "Comment ouvrir une galerie ?",
        "a": (
            "On crée un atelier, on accroche ses œuvres avec leur cartel, on écrit la "
            "note d’intention, puis on ouvre la salle. L’adresse publique est "
            "artworksdigital.fr/galerie/votre-nom."
        ),
    },
    {
        "q": "Combien coûte une galerie sur Artworksdigital ?",
        "a": (
            "L’offre Découverte est gratuite, jusqu’à cinq œuvres. Artiste coûte "
            "9,90 €/mois, Pro 19,90 €/mois, Studio 39,90 €/mois. Aucune commission "
            "sur les ventes : il n’y a pas de boutique."
        ),
    },
    {
        "q": "Artworksdigital est-il ouvert aujourd’hui ?",
        "a": (
            "Une nouvelle version se prépare, et la page d’accueil est pour l’instant "
            "une lettre. Les galeries déjà publiées restent visitables à leur adresse, "
            "et la liste des salles ouvertes est sur artworksdigital.fr/galeries."
        ),
    },
    {
        "q": "À qui s’adresse Artworksdigital ?",
        "a": (
            "Aux artistes qui veulent une adresse à eux : peinture, dessin, "
            "photographie, sculpture, art numérique. Il n’y a pas de compte galerie "
            "ni de compte collectionneur, pas de jury et pas de sélection."
        ),
    },
)


@public_bp.route("/", methods=["GET", "POST"])
def home():
    if not site_is_open():
        from artworks.plans import active_offers

        error = False
        if request.method == "POST":
            if try_unlock(request.form.get("key") or ""):
                return redirect(url_for("public.home"))
            error = True
        # Porte fermée, la lettre est la seule page que les moteurs lisent :
        # elle porte donc le site entier — la définition, les salles ouvertes,
        # les offres, les questions — et non un simple « à bientôt ».
        rooms = open_rooms()
        g.track_title = "Artworksdigital revient"
        return render_template(
            "public/coming_soon.html",
            gate_error=error,
            rooms=rooms,
            room_counts=public_work_counts(rooms),
            offers=active_offers(),
            faq=SITE_FAQ,
            letter_published=LETTER_PUBLISHED,
            letter_date=LETTER_MODIFIED,
        )
    rooms = open_rooms()
    counts = public_work_counts(rooms)
    previews = room_previews(rooms, per_room=4)

    # La salle à l'affiche : la première des salles mises en avant qui ait
    # de quoi être montrée. Une salle vide en tête d'accueil dirait que la
    # maison est vide.
    affiche = next(
        (
            artist
            for artist in rooms
            if artist.has_feature("featured") and counts.get(artist.id)
        ),
        next((artist for artist in rooms if counts.get(artist.id)), None),
    )

    g.track_title = "Artworksdigital"
    return render_template(
        "public/home.html",
        rooms=rooms,
        room_counts=counts,
        previews=previews,
        affiche=affiche,
        affiche_works=previews.get(affiche.id, []) if affiche else [],
        triptych=wall_works(rooms, limit=3, per_room=1),
        wall=wall_works(rooms, limit=12, per_room=2),
        disciplines=disciplines_index(rooms)[:8],
        faq=SITE_FAQ[:4],
    )


def _directory(rooms, *, query="", discipline=None):
    """Le répertoire, dans sa forme complète ou restreint à une discipline."""
    shown = search_rooms(rooms, query) if query else rooms
    shown_ids = {artist.id for artist in shown}
    facets = directory_facets(rooms)
    letter_ids = {}
    for artist in rooms:
        letter = room_letter(artist.display_name)
        letter_ids.setdefault(letter, artist.id)
    return {
        "rooms": rooms,
        "shown": shown,
        "shown_ids": shown_ids,
        "query": query,
        "discipline": discipline,
        "room_counts": public_work_counts(rooms),
        "previews": room_previews(rooms),
        "letters": facets["letters"],
        "disciplines": disciplines_index(rooms),
        "letter_ids": letter_ids,
        "room_haystack": room_haystack,
        "room_letter": room_letter,
    }


@public_bp.route("/galeries")
def galleries():
    rooms = open_rooms()
    query = (request.args.get("q") or request.args.get("query") or "").strip()
    g.track_title = "Recherche de salles" if query else "Galeries"
    return render_template("public/galleries.html", **_directory(rooms, query=query))


@public_bp.route("/galeries/<slug>")
def discipline(slug: str):
    """Le répertoire d'une discipline — « les galeries de photographie ».

    Personne ne cherche « une galerie » : on cherche une galerie de
    peinture, de gravure, de photographie. Ces adresses-là existent donc
    pour de bon, avec leur propre titre et leur propre plan du site,
    plutôt que d'être un filtre en JavaScript qu'aucun moteur ne voit."""
    rooms = open_rooms()
    found = rooms_of_discipline(rooms, slug)
    if not found:
        abort(404)
    label = found[0].discipline
    g.track_title = f"Galeries — {label}"
    return render_template(
        "public/galleries.html",
        **_directory(found, discipline={"slug": slug, "name": label, "count": len(found)}),
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


@public_bp.route("/galeries.atom")
def rooms_atom():
    """Les salles ouvertes récemment, en Atom.

    Une galerie qui ouvre est une nouvelle. Un flux la fait voyager — vers
    un agrégateur, vers un lecteur, vers un robot qui repasse — sans que
    personne ait à recharger le répertoire pour voir ce qui a changé."""
    rooms = open_rooms()
    fresh = sorted(rooms, key=lambda a: a.updated_at or a.created_at, reverse=True)[:40]
    updated = max((a.updated_at or a.created_at for a in fresh), default=utcnow())
    body = render_template(
        "public/rooms.atom",
        rooms=fresh,
        counts=public_work_counts(fresh),
        updated=updated,
    )
    return body, 200, {
        "Content-Type": "application/atom+xml; charset=utf-8",
        "Cache-Control": "public, max-age=900",
    }


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
    rooms = open_rooms()
    return render_template(
        "public/gallery.html",
        artist=artist,
        works=hang,
        all_works=works,
        spotlight=spotlight,
        groups=groups,
        form=form,
        sent=request.args.get("sent") == "1",
        kin=kin_rooms(rooms, artist),
        kin_counts=public_work_counts(rooms),
        kin_previews=room_previews(rooms),
        discipline_href=(
            url_for("public.discipline", slug=discipline_slug(artist.discipline))
            if artist.discipline and rooms_of_discipline(rooms, discipline_slug(artist.discipline))
            else None
        ),
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
        position=index + 1,
        total=len(hung),
        # La suite de l'accrochage sous l'œuvre : la visite continue, et
        # les pages d'une même salle se tiennent par la main.
        siblings=[item for item in hung if item.id != work.id][:8],
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
        {"loc": canonical_url("/galeries.atom"), "changefreq": "daily", "priority": "0.3", "lastmod": freshest, "images": []},
    ]
    # Les répertoires par discipline : ce sont eux que l'on cherche —
    # « galerie de photographie », pas « galerie ».
    for row in disciplines_index(rooms):
        pages.append({
            "loc": canonical_url(url_for("public.discipline", slug=row["slug"])),
            "changefreq": "weekly",
            "priority": "0.75",
            "lastmod": freshest,
            "images": [],
        })
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
        feed=canonical_url("/galeries.atom"),
    )
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


@public_bp.route("/llms.txt")
def llms():
    """Fichier pour les moteurs génératifs : qui nous sommes, sans jargon.

    Un modèle qui cite Artworksdigital doit trouver ici de quoi le faire
    juste : la définition, les faits, les questions posées et les salles
    réellement ouvertes ce matin — pas une brochure figée.
    """
    from artworks.plans import active_offers

    rooms = open_rooms()
    body = render_template(
        "public/llms.txt",
        contact=contact_inbox(),
        rooms=rooms,
        room_counts=public_work_counts(rooms),
        disciplines=disciplines_index(rooms),
        offers=active_offers(),
        faq=SITE_FAQ,
        site_open=site_is_open(),
        updated=LETTER_MODIFIED,
    )
    return body, 200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
    }
