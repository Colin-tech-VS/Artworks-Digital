"""Les outils de K.A.E.L. sur Artworks Digital.

Chacun s'appuie sur le schéma réel — Artist, Work, Offer, PageView,
MailMessage, SocialPost, SubscriptionEvent. Aucun n'ouvre de SQL libre :
K.A.E.L. passe par ces fonctions, ou il ne passe pas.
"""

from __future__ import annotations

from datetime import timedelta

from flask import url_for
from sqlalchemy import func, or_

from artworks.extensions import db
from artworks.kael import permissions as perm
from artworks.kael.registry import (
    CRITICAL,
    HIGH,
    LOW,
    MEDIUM,
    PermissionDenied,
    ToolError,
    tool,
)
from artworks.models import (
    Artist,
    KaelAuditLog,
    MailMessage,
    Offer,
    PageView,
    SocialPost,
    SubscriptionEvent,
    Work,
    utcnow,
)
from artworks.seo import absolute_media, canonical_url

STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


# ------------------------------------------------------------------ garde


def _artist_or_fail(grant, reference) -> Artist:
    """Retrouve un artiste par id ou par adresse, dans la limite du jeton."""
    if reference in (None, ""):
        raise ToolError("Indiquez l’artiste : son identifiant ou son slug.")
    artist = None
    if isinstance(reference, int) or str(reference).isdigit():
        artist = db.session.get(Artist, int(reference))
    if artist is None:
        artist = Artist.query.filter(
            or_(Artist.slug == str(reference), Artist.email == str(reference).lower())
        ).first()
    if artist is None:
        raise ToolError(f"Aucun artiste ne correspond à « {reference} ».")
    if grant.artist_id is not None and artist.id != grant.artist_id:
        raise PermissionDenied("Ce jeton ne donne accès qu’à un seul atelier.")
    return artist


def _work_or_fail(grant, work_id) -> Work:
    work = db.session.get(Work, int(work_id)) if str(work_id).isdigit() else None
    if work is None:
        raise ToolError(f"Aucune œuvre d’identifiant {work_id}.")
    if grant.artist_id is not None and work.artist_id != grant.artist_id:
        raise PermissionDenied("Ce jeton ne donne accès qu’à un seul atelier.")
    return work


def _scoped_artists(grant):
    query = Artist.query
    if grant.artist_id is not None:
        query = query.filter(Artist.id == grant.artist_id)
    return query


def _scoped_works(grant):
    query = Work.query
    if grant.artist_id is not None:
        query = query.filter(Work.artist_id == grant.artist_id)
    return query


# ------------------------------------------------------------- sérialisation


def _artist_brief(artist: Artist) -> dict:
    return {
        "id": artist.id,
        "display_name": artist.display_name,
        "slug": artist.slug,
        "discipline": artist.discipline or "",
        "location": artist.location or "",
        "published": bool(artist.published),
        "plan": artist.plan_key,
        "works": artist.works.count(),
        "hung": artist.hung_count,
        "views": artist.views_total,
        "url": canonical_url(url_for("public.gallery", slug=artist.slug)),
    }


def _artist_full(artist: Artist) -> dict:
    data = _artist_brief(artist)
    offer = artist.offer
    data.update(
        {
            "email": artist.email,
            "contact_email": artist.contact_email or artist.email,
            "statement": artist.statement or "",
            "cover": absolute_media(artist.cover_path) if artist.cover_path else None,
            "reserve": artist.reserve_count,
            "unread_messages": artist.unread_count,
            "is_example": bool(artist.is_example),
            "plan_status": artist.plan_status,
            "plan_override": bool(artist.plan_override),
            "offer": {
                "key": offer.key,
                "name": offer.name,
                "price_label": offer.price_label,
                "max_works": offer.max_works,
                "features": [name for name in (
                    "stats", "customize", "share", "advanced_stats",
                    "featured", "ai", "priority", "collections",
                ) if offer.allows(name)],
            } if offer else None,
            "created_at": artist.created_at.isoformat() if artist.created_at else None,
            "updated_at": artist.updated_at.isoformat() if artist.updated_at else None,
        }
    )
    return data


def _work_brief(work: Work) -> dict:
    return {
        "id": work.id,
        "title": work.title,
        "artist_id": work.artist_id,
        "artist": work.artist.display_name,
        "year": work.year or "",
        "medium": work.medium or "",
        "dimensions": work.dimensions or "",
        "cartel": work.cartel,
        "collection": work.collection_name or "",
        "visible": bool(work.visible),
        "position": work.position,
        "views": work.view_count or 0,
    }


def _work_full(work: Work) -> dict:
    data = _work_brief(work)
    data.update(
        {
            "note": work.note or "",
            "image": absolute_media(work.image_path),
            "image_size": [work.image_w or 0, work.image_h or 0],
            "seo_description": work.seo_description,
            "url": canonical_url(
                url_for("public.artwork", slug=work.artist.slug, work_id=work.id)
            ) if work.artist.published and work.visible else None,
            "created_at": work.created_at.isoformat() if work.created_at else None,
            "updated_at": work.updated_at.isoformat() if work.updated_at else None,
        }
    )
    return data


# ================================================================= LECTURE


@tool(
    "get_platform_stats",
    description="État général d’Artworks Digital : ateliers, salles ouvertes, œuvres, vues, revenu récurrent.",
    permission=perm.READ,
    category="lecture",
    returns="Compteurs de la plateforme et répartition par offre.",
    parameters=_schema({}),
)
def get_platform_stats(grant) -> dict:
    from artworks.plans import all_offers

    counts = dict(
        db.session.query(Artist.plan_key, func.count(Artist.id))
        .filter(Artist.is_example.is_(False))
        .group_by(Artist.plan_key)
        .all()
    )
    offers = all_offers()
    mrr = sum(counts.get(offer.key, 0) * (offer.price_cents or 0) for offer in offers)
    return {
        "artists": Artist.query.filter(Artist.is_example.is_(False)).count(),
        "example_rooms": Artist.query.filter(Artist.is_example.is_(True)).count(),
        "published_rooms": Artist.query.filter_by(published=True).count(),
        "works": Work.query.count(),
        "works_visible": Work.query.filter_by(visible=True).count(),
        "total_views": int(db.session.query(func.coalesce(func.sum(Work.view_count), 0)).scalar() or 0),
        "unread_messages": MailMessage.query.filter_by(direction="in", is_read=False).count(),
        "plan_counts": counts,
        "mrr_cents": mrr,
        "mrr_label": f"{mrr / 100:.2f} €".replace(".", ","),
        "paying": sum(counts.get(offer.key, 0) for offer in offers if offer.price_cents),
    }


@tool(
    "search_artists",
    description="Cherche des artistes par nom, slug, discipline, lieu ou e-mail.",
    permission=perm.READ,
    category="lecture",
    returns="Liste d’artistes en version courte.",
    parameters=_schema({
        "query": {**STR, "description": "Texte cherché dans le nom, le slug, la discipline, le lieu."},
        "published": {**BOOL, "description": "Ne garder que les salles ouvertes."},
        "plan": {**STR, "description": "Clé d’offre : decouverte, artiste, pro, studio."},
        "include_examples": {**BOOL, "description": "Inclure les salles d’exemple (exclues par défaut)."},
        "limit": {**INT, "description": "1 à 100, 25 par défaut."},
    }),
)
def search_artists(grant, query: str = "", published=None, plan: str = "",
                   include_examples: bool = False, limit: int = 25) -> dict:
    rows = _scoped_artists(grant)
    if not include_examples:
        rows = rows.filter(Artist.is_example.is_(False))
    if query:
        like = f"%{query.strip()}%"
        rows = rows.filter(
            or_(
                Artist.display_name.ilike(like),
                Artist.slug.ilike(like),
                Artist.discipline.ilike(like),
                Artist.location.ilike(like),
                Artist.email.ilike(like),
            )
        )
    if published is not None:
        rows = rows.filter(Artist.published.is_(bool(published)))
    if plan:
        rows = rows.filter(Artist.plan_key == plan.strip())
    limit = max(1, min(int(limit or 25), 100))
    found = rows.order_by(Artist.updated_at.desc()).limit(limit).all()
    return {"count": len(found), "artists": [_artist_brief(a) for a in found]}


@tool(
    "get_artist",
    description="Fiche complète d’un artiste : profil, offre, note d’intention, accrochage.",
    permission=perm.READ,
    category="lecture",
    returns="Le profil, ses droits d’offre et ses œuvres.",
    parameters=_schema({
        "artist": {**STR, "description": "Identifiant, slug ou e-mail."},
        "with_works": {**BOOL, "description": "Joindre les œuvres (vrai par défaut)."},
    }, ["artist"]),
)
def get_artist(grant, artist: str, with_works: bool = True) -> dict:
    row = _artist_or_fail(grant, artist)
    data = _artist_full(row)
    if with_works:
        data["works_list"] = [
            _work_brief(w) for w in row.works.order_by(Work.position.asc()).all()
        ]
    return data


@tool(
    "get_artist_stats",
    description="Audience d’un atelier : vues par jour, sources, œuvres les plus regardées.",
    permission=perm.READ,
    category="lecture",
    returns="Séries et classements pour cet artiste.",
    parameters=_schema({
        "artist": {**STR, "description": "Identifiant, slug ou e-mail."},
        "days": {**INT, "description": "Fenêtre en jours, 28 par défaut."},
    }, ["artist"]),
)
def get_artist_stats(grant, artist: str, days: int = 28) -> dict:
    from artworks.analytics import artist_series

    row = _artist_or_fail(grant, artist)
    days = max(1, min(int(days or 28), 365))
    trend = artist_series(row.id, days)
    since = utcnow() - timedelta(days=days)
    sources = (
        db.session.query(PageView.source, func.count(PageView.id))
        .filter(PageView.artist_id == row.id, PageView.created_at >= since, PageView.is_bot.is_(False))
        .group_by(PageView.source)
        .order_by(func.count(PageView.id).desc())
        .limit(10)
        .all()
    )
    top = row.works.order_by(Work.view_count.desc()).limit(10).all()
    return {
        "artist": _artist_brief(row),
        "days": days,
        "views_series": trend,
        "views_total_period": sum(trend),
        "views_all_time": row.views_total,
        "sources": [{"source": name or "direct", "views": count} for name, count in sources],
        "top_works": [{"id": w.id, "title": w.title, "views": w.view_count or 0} for w in top],
    }


@tool(
    "search_artworks",
    description="Cherche des œuvres par titre, technique, note, collection ou artiste.",
    permission=perm.READ,
    category="lecture",
    returns="Liste d’œuvres en version courte.",
    parameters=_schema({
        "query": {**STR, "description": "Texte cherché dans le titre, la technique, la note."},
        "artist": {**STR, "description": "Restreindre à un artiste (identifiant ou slug)."},
        "visible": {**BOOL, "description": "Vrai = accrochées, faux = en réserve."},
        "collection": {**STR, "description": "Nom de collection exact."},
        "limit": {**INT, "description": "1 à 100, 25 par défaut."},
    }),
)
def search_artworks(grant, query: str = "", artist: str = "", visible=None,
                    collection: str = "", limit: int = 25) -> dict:
    rows = _scoped_works(grant).join(Artist)
    if artist:
        rows = rows.filter(Work.artist_id == _artist_or_fail(grant, artist).id)
    if query:
        like = f"%{query.strip()}%"
        rows = rows.filter(
            or_(Work.title.ilike(like), Work.medium.ilike(like), Work.note.ilike(like))
        )
    if visible is not None:
        rows = rows.filter(Work.visible.is_(bool(visible)))
    if collection:
        rows = rows.filter(Work.collection_name == collection.strip())
    limit = max(1, min(int(limit or 25), 100))
    found = rows.order_by(Work.updated_at.desc()).limit(limit).all()
    return {"count": len(found), "artworks": [_work_brief(w) for w in found]}


@tool(
    "get_artwork",
    description="Fiche complète d’une œuvre : cartel, note, visuel, adresse publique, vues.",
    permission=perm.READ,
    category="lecture",
    returns="L’œuvre et son contexte.",
    parameters=_schema({"work_id": {**INT, "description": "Identifiant de l’œuvre."}}, ["work_id"]),
)
def get_artwork(grant, work_id: int) -> dict:
    work = _work_or_fail(grant, work_id)
    data = _work_full(work)
    data["artist_detail"] = _artist_brief(work.artist)
    return data


@tool(
    "get_catalogue",
    description="Le catalogue public : salles ouvertes et œuvres accrochées, avec ce qui reste en brouillon.",
    permission=perm.READ,
    category="lecture",
    returns="Vue d’ensemble publiée / non publiée, et les collections existantes.",
    parameters=_schema({
        "limit": {**INT, "description": "Nombre de salles listées, 50 par défaut."},
    }),
)
def get_catalogue(grant, limit: int = 50) -> dict:
    limit = max(1, min(int(limit or 50), 200))
    published = _scoped_artists(grant).filter_by(published=True).order_by(
        Artist.updated_at.desc()
    ).limit(limit).all()
    drafts = _scoped_artists(grant).filter_by(published=False).order_by(
        Artist.created_at.desc()
    ).limit(limit).all()
    collections = [
        {"name": name, "works": count}
        for name, count in db.session.query(Work.collection_name, func.count(Work.id))
        .filter(Work.collection_name != "")
        .group_by(Work.collection_name)
        .order_by(func.count(Work.id).desc())
        .limit(30)
        .all()
    ]
    return {
        "published_rooms": [_artist_brief(a) for a in published],
        "draft_rooms": [_artist_brief(a) for a in drafts],
        "collections": collections,
        "works_visible": _scoped_works(grant).filter_by(visible=True).count(),
        "works_hidden": _scoped_works(grant).filter_by(visible=False).count(),
    }


@tool(
    "get_analytics",
    description="Audience de la plateforme : visites, sessions, canaux, villes, pays, appareils, pages, temps réel.",
    permission=perm.READ,
    category="lecture",
    returns="KPI, série quotidienne et répartitions.",
    parameters=_schema({
        "days": {**INT, "description": "Fenêtre en jours, 28 par défaut."},
    }),
)
def get_analytics(grant, days: int = 28) -> dict:
    from artworks.analytics import (
        DEVICE_LABELS,
        SOURCE_LABELS,
        breakdown,
        city_breakdown,
        kpis,
        live_snapshot,
        series,
        top_paths,
    )

    days = max(1, min(int(days or 28), 365))
    return {
        "days": days,
        "kpis": kpis(days),
        "series": series(days),
        "live": live_snapshot(),
        "sources": breakdown(PageView.source, days, labels=SOURCE_LABELS),
        "cities": city_breakdown(days),
        "countries": breakdown(PageView.country, days, hide_empty=True),
        "devices": breakdown(PageView.device, days, labels=DEVICE_LABELS),
        "referrers": breakdown(PageView.referrer_host, days, hide_empty=True, limit=10),
        "top_pages": top_paths(days),
    }


@tool(
    "list_messages",
    description="Les messages reçus et envoyés par la plateforme.",
    permission=perm.READ,
    category="lecture",
    returns="Messages, du plus récent au plus ancien.",
    parameters=_schema({
        "direction": {**STR, "description": "in, out, ou vide pour tout."},
        "unread_only": {**BOOL, "description": "Ne garder que les non lus."},
        "limit": {**INT, "description": "1 à 100, 30 par défaut."},
    }),
)
def list_messages(grant, direction: str = "", unread_only: bool = False, limit: int = 30) -> dict:
    rows = MailMessage.query
    if grant.artist_id is not None:
        rows = rows.filter(MailMessage.artist_id == grant.artist_id)
    if direction in ("in", "out"):
        rows = rows.filter(MailMessage.direction == direction)
    if unread_only:
        rows = rows.filter(MailMessage.is_read.is_(False))
    limit = max(1, min(int(limit or 30), 100))
    found = rows.order_by(MailMessage.created_at.desc()).limit(limit).all()
    return {
        "count": len(found),
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "kind": m.kind,
                "status": m.status,
                "from": f"{m.from_name} <{m.from_email}>".strip(),
                "to": m.to_email,
                "subject": m.subject,
                "excerpt": (m.body or "")[:280],
                "read": bool(m.is_read),
                "artist_id": m.artist_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in found
        ],
    }


@tool(
    "get_offers",
    description="Les offres de la plateforme, leur prix, leurs plafonds et les fonctionnalités incluses.",
    permission=perm.READ,
    category="lecture",
    returns="Catalogue d’offres, actives et inactives.",
    parameters=_schema({}),
)
def get_offers(grant) -> dict:
    from artworks.plans import all_offers

    return {
        "offers": [
            {
                "key": o.key,
                "name": o.name,
                "audience": o.audience,
                "price_cents": o.price_cents,
                "price_label": o.price_label,
                "max_works": o.max_works,
                "active": bool(o.active),
                "stripe_ready": bool(o.stripe_price_id),
                "features": [name for name in (
                    "stats", "customize", "share", "advanced_stats",
                    "featured", "ai", "priority", "collections",
                ) if o.allows(name)],
                "lines": o.feature_lines,
            }
            for o in all_offers()
        ]
    }


@tool(
    "list_subscriptions",
    description="Les mouvements d’abonnement récents : qui a changé d’offre, quand, avec quel statut.",
    permission=perm.READ,
    category="lecture",
    returns="Journal des changements d’offre.",
    parameters=_schema({"limit": {**INT, "description": "1 à 100, 30 par défaut."}}),
)
def list_subscriptions(grant, limit: int = 30) -> dict:
    rows = SubscriptionEvent.query
    if grant.artist_id is not None:
        rows = rows.filter(SubscriptionEvent.artist_id == grant.artist_id)
    limit = max(1, min(int(limit or 30), 100))
    found = rows.order_by(SubscriptionEvent.created_at.desc()).limit(limit).all()
    return {
        "count": len(found),
        "events": [
            {
                "id": e.id,
                "artist_id": e.artist_id,
                "plan": e.plan_key,
                "status": e.status,
                "note": e.note,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in found
        ],
    }


@tool(
    "get_service_health",
    description="État des services branchés : SMTP, Stripe, Mistral, réseaux sociaux, base.",
    permission=perm.READ,
    category="lecture",
    returns="Ce qui est configuré et ce qui ne l’est pas.",
    parameters=_schema({"probe_social": {**BOOL, "description": "Interroger réellement les réseaux (plus lent)."}}),
)
def get_service_health(grant, probe_social: bool = False) -> dict:
    from artworks.mailer import inbox_configured, mail_configured
    from artworks.mistral import mistral_ready
    from artworks.social import Facebook, Instagram, platform_status
    from artworks.stripe_billing import stripe_ready

    social = platform_status() if probe_social else {
        "facebook": {"configured": Facebook.configured()},
        "instagram": {"configured": Instagram.configured()},
    }
    return {
        "database": db.engine.dialect.name,
        "smtp": mail_configured(),
        "imap": inbox_configured(),
        "stripe": stripe_ready(),
        "mistral": mistral_ready(),
        "social": social,
        "recent_failures": KaelAuditLog.query.filter_by(ok=False).count(),
    }


# ================================================================= ANALYSE


def _artwork_findings(work: Work) -> list[dict]:
    findings = []
    note = (work.note or "").strip()
    if not note:
        findings.append({"level": "warning", "field": "note",
                         "detail": "Aucune note : la page d’œuvre n’a rien à dire aux moteurs ni aux visiteurs."})
    elif len(note) < 60:
        findings.append({"level": "info", "field": "note",
                         "detail": f"Note très courte ({len(note)} signes) — sous 60, la description est maigre."})
    if not work.medium:
        findings.append({"level": "info", "field": "medium", "detail": "Technique absente du cartel."})
    if not work.year:
        findings.append({"level": "info", "field": "year", "detail": "Année absente du cartel."})
    if not work.dimensions:
        findings.append({"level": "info", "field": "dimensions", "detail": "Dimensions absentes du cartel."})
    if len(work.title or "") < 3:
        findings.append({"level": "warning", "field": "title", "detail": "Titre trop court pour être identifiable."})
    if not (work.image_w or 0) > 0:
        findings.append({"level": "info", "field": "image",
                         "detail": "Dimensions du visuel inconnues : Open Graph ne peut pas les annoncer."})
    if work.visible and not work.artist.published:
        findings.append({"level": "info", "field": "visibility",
                         "detail": "Œuvre accrochée dans une salle encore fermée : invisible au public."})
    return findings


@tool(
    "analyze_artwork",
    description="Diagnostic d’une œuvre : cartel incomplet, description faible, visuel, visibilité, SEO.",
    permission=perm.ANALYZE,
    category="analyse",
    returns="Une note sur 100 et la liste des points à corriger.",
    parameters=_schema({"work_id": {**INT, "description": "Identifiant de l’œuvre."}}, ["work_id"]),
)
def analyze_artwork(grant, work_id: int) -> dict:
    work = _work_or_fail(grant, work_id)
    findings = _artwork_findings(work)
    penalty = sum(12 if f["level"] == "warning" else 5 for f in findings)
    return {
        "artwork": _work_brief(work),
        "score": max(0, 100 - penalty),
        "findings": findings,
        "seo_description": work.seo_description,
        "verdict": "Complète." if not findings else f"{len(findings)} point(s) à reprendre.",
    }


@tool(
    "analyze_portfolio",
    description="Diagnostic d’un atelier entier : complétude des cartels, note d’intention, accrochage, audience.",
    permission=perm.ANALYZE,
    category="analyse",
    returns="Synthèse de l’atelier et œuvres à reprendre en priorité.",
    parameters=_schema({"artist": {**STR, "description": "Identifiant, slug ou e-mail."}}, ["artist"]),
)
def analyze_portfolio(grant, artist: str) -> dict:
    row = _artist_or_fail(grant, artist)
    works = row.works.order_by(Work.position.asc()).all()
    weak = []
    for work in works:
        findings = _artwork_findings(work)
        if findings:
            penalty = sum(12 if f["level"] == "warning" else 5 for f in findings)
            weak.append({
                "id": work.id,
                "title": work.title,
                "score": max(0, 100 - penalty),
                "findings": [f["detail"] for f in findings],
            })
    weak.sort(key=lambda item: item["score"])

    remarks = []
    statement = (row.statement or "").strip()
    if not statement:
        remarks.append("Aucune note d’intention : la salle s’ouvre sans texte de présentation.")
    elif len(statement) < 120:
        remarks.append(f"Note d’intention courte ({len(statement)} signes).")
    if not row.cover_path:
        remarks.append("Aucune image de salle : le partage social retombe sur le visuel par défaut.")
    if not row.discipline:
        remarks.append("Discipline non renseignée — elle sert au référencement de la page.")
    if row.published and row.hung_count == 0:
        remarks.append("Salle ouverte mais vide : rien n’est accroché.")
    if not row.published and row.hung_count:
        remarks.append(f"{row.hung_count} œuvre(s) prête(s), mais la salle reste fermée.")
    limit = row.work_limit()
    if limit and row.works.count() >= limit:
        remarks.append(f"Plafond de l’offre atteint ({limit} œuvres).")

    return {
        "artist": _artist_full(row),
        "works_total": len(works),
        "works_complete": len(works) - len(weak),
        "works_to_improve": weak[:20],
        "remarks": remarks,
        "average_score": round(
            sum(100 - sum(12 if f["level"] == "warning" else 5 for f in _artwork_findings(w)) for w in works)
            / len(works)
        ) if works else None,
    }


@tool(
    "find_anomalies",
    description="Balayage de la plateforme : salles vides publiées, cartels incomplets, envois ratés, publications en échec.",
    permission=perm.ANALYZE,
    category="analyse",
    returns="Anomalies classées par gravité, avec ce qu’elles visent.",
    parameters=_schema({"days": {**INT, "description": "Fenêtre pour les échecs récents, 30 par défaut."}}),
)
def find_anomalies(grant, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=max(1, min(int(days or 30), 365)))
    anomalies: list[dict] = []

    for artist in _scoped_artists(grant).filter_by(published=True, is_example=False).all():
        if artist.hung_count == 0:
            anomalies.append({"level": "warning", "kind": "empty_room",
                              "subject": {"artist_id": artist.id, "name": artist.display_name},
                              "detail": "Salle ouverte sans aucune œuvre accrochée."})
        if not (artist.statement or "").strip():
            anomalies.append({"level": "info", "kind": "no_statement",
                              "subject": {"artist_id": artist.id, "name": artist.display_name},
                              "detail": "Salle publiée sans note d’intention."})

    missing_note = _scoped_works(grant).filter(
        Work.visible.is_(True), or_(Work.note.is_(None), Work.note == "")
    ).count()
    if missing_note:
        anomalies.append({"level": "info", "kind": "weak_descriptions",
                          "subject": {"count": missing_note},
                          "detail": f"{missing_note} œuvre(s) accrochée(s) sans note."})

    failed_mail = MailMessage.query.filter(
        MailMessage.direction == "out", MailMessage.status == "failed",
        MailMessage.created_at >= since,
    ).count()
    if failed_mail:
        anomalies.append({"level": "warning", "kind": "mail_failures",
                          "subject": {"count": failed_mail},
                          "detail": f"{failed_mail} e-mail(s) non partis sur la période."})

    failed_posts = SocialPost.query.filter(
        SocialPost.status == "error", SocialPost.created_at >= since
    ).count()
    if failed_posts:
        anomalies.append({"level": "warning", "kind": "social_failures",
                          "subject": {"count": failed_posts},
                          "detail": f"{failed_posts} publication(s) réseau en échec."})

    failed_tools = KaelAuditLog.query.filter(
        KaelAuditLog.ok.is_(False), KaelAuditLog.created_at >= since
    ).count()
    if failed_tools:
        anomalies.append({"level": "info", "kind": "tool_failures",
                          "subject": {"count": failed_tools},
                          "detail": f"{failed_tools} appel(s) d’outil K.A.E.L. en échec."})

    order = {"warning": 0, "info": 1}
    anomalies.sort(key=lambda item: order.get(item["level"], 2))
    return {"days": days, "count": len(anomalies), "anomalies": anomalies}


# ================================================================ ÉCRITURE

WRITABLE_WORK = ("title", "year", "medium", "dimensions", "note", "collection_name")


@tool(
    "update_artwork",
    description="Modifie le cartel ou la note d’une œuvre. Ne touche jamais au visuel.",
    permission=perm.WRITE,
    category="écriture",
    risk=MEDIUM,
    mutating=True,
    returns="L’œuvre après modification, et la liste des champs changés.",
    parameters=_schema({
        "work_id": {**INT, "description": "Identifiant de l’œuvre."},
        "title": STR, "year": STR, "medium": STR, "dimensions": STR,
        "note": {**STR, "description": "Texte du cartel, 2000 signes au plus."},
        "collection_name": {**STR, "description": "Collection (offre Studio uniquement)."},
    }, ["work_id"]),
)
def update_artwork(grant, work_id: int, **fields) -> dict:
    work = _work_or_fail(grant, work_id)
    limits = {"title": 180, "year": 12, "medium": 160, "dimensions": 120,
              "note": 2000, "collection_name": 120}
    changed = {}
    for name in WRITABLE_WORK:
        if name not in fields or fields[name] is None:
            continue
        if name == "collection_name" and not work.artist.has_feature("collections"):
            raise ToolError("Les collections sont réservées à l’offre Studio.")
        value = str(fields[name]).strip()[: limits[name]]
        if name == "title" and not value:
            raise ToolError("Le titre ne peut pas être vide.")
        if getattr(work, name) != value:
            changed[name] = {"before": getattr(work, name), "after": value}
            setattr(work, name, value)
    if not changed:
        return {"changed": {}, "artwork": _work_full(work), "note": "Rien à modifier."}
    work.touch()
    work.artist.touch()
    db.session.commit()
    return {"changed": changed, "artwork": _work_full(work)}


@tool(
    "update_artist",
    description="Modifie la présentation d’un artiste : note d’intention, discipline, lieu, e-mail de contact.",
    permission=perm.WRITE,
    category="écriture",
    risk=MEDIUM,
    mutating=True,
    returns="Le profil après modification et les champs changés.",
    parameters=_schema({
        "artist": {**STR, "description": "Identifiant, slug ou e-mail."},
        "statement": {**STR, "description": "Note d’intention, 4000 signes au plus."},
        "discipline": STR, "location": STR,
        "contact_email": {**STR, "description": "Adresse affichée au public."},
        "display_name": {**STR, "description": "Nom affiché."},
    }, ["artist"]),
)
def update_artist(grant, artist: str, **fields) -> dict:
    row = _artist_or_fail(grant, artist)
    limits = {"statement": 4000, "discipline": 120, "location": 120,
              "contact_email": 180, "display_name": 120}
    changed = {}
    for name, cap in limits.items():
        if name not in fields or fields[name] is None:
            continue
        value = str(fields[name]).strip()[:cap]
        if name == "display_name" and len(value) < 2:
            raise ToolError("Le nom affiché doit faire au moins deux caractères.")
        if name == "contact_email" and value and "@" not in value:
            raise ToolError("Adresse de contact invalide.")
        if getattr(row, name) != value:
            changed[name] = {"before": getattr(row, name), "after": value}
            setattr(row, name, value)
    if not changed:
        return {"changed": {}, "artist": _artist_full(row), "note": "Rien à modifier."}
    row.touch()
    db.session.commit()
    return {"changed": changed, "artist": _artist_full(row)}


@tool(
    "set_artwork_visibility",
    description="Accroche une œuvre dans la salle, ou la remet en réserve.",
    permission=perm.WRITE,
    category="écriture",
    risk=MEDIUM,
    mutating=True,
    returns="L’état de visibilité après changement.",
    parameters=_schema({
        "work_id": INT,
        "visible": {**BOOL, "description": "Vrai = accrochée, faux = en réserve."},
    }, ["work_id", "visible"]),
)
def set_artwork_visibility(grant, work_id: int, visible: bool) -> dict:
    work = _work_or_fail(grant, work_id)
    before = bool(work.visible)
    work.visible = bool(visible)
    work.touch()
    work.artist.touch()
    db.session.commit()
    return {"work_id": work.id, "title": work.title, "was": before, "now": bool(work.visible)}


@tool(
    "reorder_artworks",
    description="Change l’ordre d’accrochage d’un atelier.",
    permission=perm.WRITE,
    category="écriture",
    risk=LOW,
    mutating=True,
    returns="Le nouvel ordre appliqué.",
    parameters=_schema({
        "artist": {**STR, "description": "Identifiant, slug ou e-mail."},
        "work_ids": {"type": "array", "items": INT, "description": "Identifiants dans l’ordre voulu."},
    }, ["artist", "work_ids"]),
)
def reorder_artworks(grant, artist: str, work_ids: list) -> dict:
    row = _artist_or_fail(grant, artist)
    owned = {w.id: w for w in row.works.all()}
    unknown = [i for i in work_ids if int(i) not in owned]
    if unknown:
        raise ToolError(f"Ces œuvres n’appartiennent pas à {row.display_name} : {unknown}.")
    for position, work_id in enumerate(work_ids):
        owned[int(work_id)].position = position
    row.touch()
    db.session.commit()
    return {
        "artist_id": row.id,
        "order": [{"id": int(i), "title": owned[int(i)].title} for i in work_ids],
    }


# ============================================================== PUBLICATION


@tool(
    "compose_social_post",
    description="Prépare un post : texte, hashtags et visuel au format du réseau. Ne publie rien.",
    permission=perm.PUBLISH,
    category="publication",
    risk=LOW,
    mutating=False,
    returns="Un brouillon complet, avec l’URL HTTPS du visuel prête à publier.",
    parameters=_schema({
        "prompt": {**STR, "description": "La consigne, en français."},
        "work_id": {**INT, "description": "Œuvre à mettre en avant (facultatif)."},
        "platform": {**STR, "description": "instagram, facebook, pinterest, deviantart."},
        "format": {**STR, "description": "square, portrait, landscape, story."},
        "layout": {**STR, "description": "gallery, artwork, editorial, quote, poster."},
    }, ["prompt"]),
)
def compose_social_post(grant, prompt: str, work_id: int | None = None,
                        platform: str = "instagram", format: str = "", layout: str = "") -> dict:
    from artworks.composer import compose

    work = _work_or_fail(grant, work_id) if work_id else None
    draft = compose(
        str(prompt).strip(),
        platforms=[platform or "instagram"],
        work=work,
        fmt=format or "",
        layout=layout or "",
    )
    return {
        "caption": draft["caption"],
        "hashtags": draft["hashtags"],
        "message": draft["message"],
        "alt": draft["alt"],
        "design": draft["design"],
        "format": draft["format"],
        "image_name": draft["image_name"],
        "image_url": draft["image_url"],
        "link": draft["link"],
        "warning": draft["warning"],
        "next": "publish_social_post avec message, image_name et platforms.",
    }


@tool(
    "publish_social_post",
    description="Publie réellement sur les réseaux connectés. Action publique et irréversible.",
    permission=perm.PUBLISH,
    category="publication",
    risk=CRITICAL,
    mutating=True,
    returns="Le résultat par réseau, avec l’identifiant distant quand il existe.",
    parameters=_schema({
        "message": {**STR, "description": "Texte publié tel quel."},
        "platforms": {"type": "array", "items": STR, "description": "facebook, instagram, pinterest, deviantart."},
        "image_name": {**STR, "description": "Visuel généré par compose_social_post."},
        "image_url": {**STR, "description": "URL HTTPS publique, si le visuel ne vient pas d’ici."},
        "link": STR,
        "title": STR,
        "work_id": INT,
        "alt": STR,
    }, ["message", "platforms"]),
)
def publish_social_post(grant, message: str, platforms: list, image_name: str = "",
                        image_url: str = "", link: str = "", title: str = "",
                        work_id: int | None = None, alt: str = "", **_) -> dict:
    from artworks.composer import log_publication
    from artworks.social import PLATFORMS, publish as publish_social

    message = str(message).strip()
    if not message:
        raise ToolError("Le texte du post est vide.")
    wanted = [str(p).strip().lower() for p in (platforms or []) if str(p).strip()]
    unknown = [p for p in wanted if p not in PLATFORMS]
    if unknown:
        raise ToolError(f"Réseau inconnu : {', '.join(unknown)}.")
    if not wanted:
        raise ToolError("Indiquez au moins un réseau.")

    work = _work_or_fail(grant, work_id) if work_id else None
    if image_name and not image_url:
        image_url = absolute_media(image_name)
    if not image_url and work is not None:
        image_url = absolute_media(work.image_path)

    results = publish_social(wanted, title=title or "", message=message,
                             image_url=image_url, link=link or "")
    draft = {"message": message, "image_url": image_url, "image_name": image_name,
             "alt": alt, "prompt": "", "design": {"headline": title or ""}}
    for item in results:
        log_publication(item, platform=item["platform"], draft=draft, work=work)
    db.session.commit()
    return {
        "published": [r["platform"] for r in results if r.get("ok")],
        "failed": [{"platform": r["platform"], "error": r.get("error")} for r in results if not r.get("ok")],
        "results": results,
    }


@tool(
    "set_gallery_published",
    description="Ouvre ou ferme la galerie publique d’un artiste.",
    permission=perm.PUBLISH,
    category="publication",
    risk=HIGH,
    mutating=True,
    returns="L’état de la salle après changement, et son adresse.",
    parameters=_schema({
        "artist": {**STR, "description": "Identifiant, slug ou e-mail."},
        "published": {**BOOL, "description": "Vrai = ouvrir la salle au public."},
    }, ["artist", "published"]),
)
def set_gallery_published(grant, artist: str, published: bool) -> dict:
    from artworks.emails import send_gallery_published

    row = _artist_or_fail(grant, artist)
    before = bool(row.published)
    row.published = bool(published)
    row.touch()
    db.session.commit()
    if row.published and not before:
        send_gallery_published(row)
    return {
        "artist_id": row.id,
        "display_name": row.display_name,
        "was": before,
        "now": bool(row.published),
        "url": canonical_url(url_for("public.gallery", slug=row.slug)),
        "email_sent": bool(row.published and not before),
    }


@tool(
    "send_platform_email",
    description="Envoie un e-mail mis en page depuis l’adresse de la plateforme.",
    permission=perm.PUBLISH,
    category="publication",
    risk=HIGH,
    mutating=True,
    returns="Si l’envoi est parti, et l’identifiant du message archivé.",
    parameters=_schema({
        "to": {**STR, "description": "Adresse du destinataire."},
        "subject": STR,
        "body": {**STR, "description": "Corps du message ; une ligne vide sépare deux paragraphes."},
        "eyebrow": {**STR, "description": "Surtitre affiché au-dessus du titre."},
    }, ["to", "subject", "body"]),
)
def send_platform_email(grant, to: str, subject: str, body: str, eyebrow: str = "Artworksdigital") -> dict:
    from artworks.emails import deliver

    to = str(to).strip()
    if "@" not in to:
        raise ToolError("Adresse de destination invalide.")
    blocks = [b.strip() for b in str(body).split("\n\n") if b.strip()] or [str(body).strip()]
    ok, error = deliver(
        to, str(subject).strip()[:200],
        eyebrow=eyebrow, title=str(subject).strip()[:200],
        paragraphs=blocks, kind="kael",
    )
    return {"sent": ok, "error": error or None, "to": to, "subject": subject}


# =========================================================== ADMINISTRATION


@tool(
    "assign_plan",
    description="Attribue une offre à un artiste, en dehors de Stripe.",
    permission=perm.ADMIN,
    category="administration",
    risk=HIGH,
    mutating=True,
    returns="L’offre appliquée et l’ancienne.",
    parameters=_schema({
        "artist": {**STR, "description": "Identifiant, slug ou e-mail."},
        "plan_key": {**STR, "description": "decouverte, artiste, pro, studio."},
    }, ["artist", "plan_key"]),
)
def assign_plan(grant, artist: str, plan_key: str) -> dict:
    from artworks.plans import get_offer
    from artworks.stripe_billing import apply_plan

    row = _artist_or_fail(grant, artist)
    offer = Offer.query.filter_by(key=str(plan_key).strip()).first()
    if offer is None:
        raise ToolError(f"Offre inconnue : {plan_key}.")
    before = row.plan_key
    row.plan_override = True
    apply_plan(row, offer.key, status="active", note="Attribué par K.A.E.L.")
    final = get_offer(row.plan_key)
    return {
        "artist_id": row.id,
        "display_name": row.display_name,
        "was": before,
        "now": row.plan_key,
        "offer": final.name if final else row.plan_key,
    }


@tool(
    "delete_artwork",
    description="Retire définitivement une œuvre et son visuel. Irréversible.",
    permission=perm.ADMIN,
    category="administration",
    risk=CRITICAL,
    mutating=True,
    returns="Ce qui a été supprimé.",
    parameters=_schema({"work_id": INT}, ["work_id"]),
)
def delete_artwork(grant, work_id: int) -> dict:
    from artworks.images import remove_image

    work = _work_or_fail(grant, work_id)
    removed = {"id": work.id, "title": work.title, "artist_id": work.artist_id,
               "artist": work.artist.display_name}
    remove_image(work.image_path)
    work.artist.touch()
    db.session.delete(work)
    db.session.commit()
    return {"deleted": removed}


@tool(
    "get_audit_log",
    description="Le journal des actions de K.A.E.L. sur la plateforme.",
    permission=perm.ADMIN,
    category="administration",
    returns="Les appels d’outils, du plus récent au plus ancien.",
    parameters=_schema({
        "limit": {**INT, "description": "1 à 200, 50 par défaut."},
        "only_failures": BOOL,
    }),
)
def get_audit_log(grant, limit: int = 50, only_failures: bool = False) -> dict:
    from artworks.kael.audit import recent

    rows = recent(max(1, min(int(limit or 50), 200)), only_failures=bool(only_failures))
    return {
        "count": len(rows),
        "entries": [
            {
                "id": r.id,
                "tool": r.tool,
                "permission": r.permission,
                "ok": bool(r.ok),
                "summary": r.summary,
                "error": r.error or None,
                "confirmed": bool(r.confirmed),
                "actor": r.actor,
                "subject": {"kind": r.subject_kind, "id": r.subject_id} if r.subject_kind else None,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# --------------------------------------------------------- conséquences


def consequences_for(name: str, params: dict) -> tuple[str, list[str], str]:
    """Ce qu'une action sensible va faire, en clair, avant qu'on la confirme."""
    if name == "publish_social_post":
        nets = ", ".join(params.get("platforms") or [])
        return (
            f"Publier ce message sur {nets}.",
            [
                "La publication est immédiate et publique.",
                "Irréversible depuis Artworks Digital : la dépublication se fait sur le réseau.",
                f"Texte : « {str(params.get('message') or '')[:160]} »",
            ],
            nets,
        )
    if name == "set_gallery_published":
        opening = bool(params.get("published"))
        return (
            ("Ouvrir" if opening else "Fermer") + f" la galerie de {params.get('artist')}.",
            [
                "La galerie devient visible de tous et indexable." if opening
                else "La galerie disparaît du public et des moteurs.",
                "Un e-mail part vers l’artiste à la première ouverture." if opening
                else "Les liens déjà partagés renverront une page introuvable.",
            ],
            str(params.get("artist")),
        )
    if name == "send_platform_email":
        return (
            f"Envoyer « {params.get('subject')} » à {params.get('to')}.",
            ["Un e-mail part réellement depuis l’adresse de la plateforme.",
             "Irréversible : un message envoyé ne se rappelle pas."],
            str(params.get("to")),
        )
    if name == "assign_plan":
        return (
            f"Passer {params.get('artist')} sur l’offre {params.get('plan_key')}.",
            ["Les fonctionnalités de l’offre s’ouvrent ou se ferment immédiatement.",
             "L’artiste reçoit un e-mail de changement d’offre.",
             "L’offre est marquée « attribuée à la main » : Stripe ne la reprendra plus."],
            str(params.get("artist")),
        )
    if name == "delete_artwork":
        return (
            f"Supprimer l’œuvre {params.get('work_id')}.",
            ["L’œuvre et son visuel sont effacés de la base.",
             "Irréversible : aucune corbeille, aucune restauration.",
             "La page publique de l’œuvre renverra une erreur."],
            str(params.get("work_id")),
        )
    return ("Exécuter cette action.", ["Action sensible."], "")


def subject_of(name: str, params: dict) -> tuple[str, str]:
    """Sur quoi porte l'appel — pour que le journal soit consultable."""
    if "work_id" in params and params["work_id"]:
        return "work", str(params["work_id"])
    if "artist" in params and params["artist"]:
        return "artist", str(params["artist"])
    if "to" in params and params["to"]:
        return "email", str(params["to"])
    return "", ""
