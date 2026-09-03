from flask import g, has_app_context

from artworks.extensions import db
from artworks.models import Offer

# Le catalogue est relu une fois par requête, pas une fois par lecture.
#
# `Artist.offer` appelait `get_offer()`, qui rappelait `seed_offers()`, qui
# repassait les quatre offres du catalogue : cinq requêtes SQL pour savoir
# si un artiste a droit aux statistiques. Les gabarits posent la question
# plusieurs fois par artiste, et l'annuaire en affiche trente — la page
# /galeries partait ainsi à 450 requêtes. Le catalogue ne bouge pas pendant
# une requête HTTP : le mémoriser sur `g` le ramène à cinq, sans rien
# changer à ce qui est servi.
_SEEDED = "_artworks_offers_seeded"
_CACHE = "_artworks_offers_cache"

CATALOG = (
    {
        "key": "decouverte",
        "name": "Découverte",
        "badge": "🆓",
        "audience": "Tester Artworksdigital",
        "features_text": "Profil artiste\nJusqu’à 5 œuvres\nPage publique\nPrésence dans la plateforme",
        "price_cents": 0,
        "max_works": 5,
        "sort": 10,
        "allow_stats": False,
        "allow_customize": False,
        "allow_share": False,
        "allow_advanced_stats": False,
        "allow_featured": False,
        "allow_ai": False,
        "allow_priority": False,
        "allow_collections": False,
    },
    {
        "key": "artiste",
        "name": "Artiste",
        "badge": "🎨",
        "audience": "Artistes indépendants",
        "features_text": "Jusqu’à 30 œuvres\nPortfolio complet\nStatistiques\nPersonnalisation du profil\nPartage des œuvres",
        "price_cents": 990,
        "max_works": 30,
        "sort": 20,
        "allow_stats": True,
        "allow_customize": True,
        "allow_share": True,
        "allow_advanced_stats": False,
        "allow_featured": False,
        "allow_ai": False,
        "allow_priority": False,
        "allow_collections": False,
    },
    {
        "key": "pro",
        "name": "Pro",
        "badge": "🚀",
        "audience": "Artistes qui développent leur activité",
        "features_text": "Œuvres illimitées\nStatistiques avancées\nMise en avant\nOutils de présentation\nFonctionnalités IA",
        "price_cents": 1990,
        "max_works": None,
        "sort": 30,
        "allow_stats": True,
        "allow_customize": True,
        "allow_share": True,
        "allow_advanced_stats": True,
        "allow_featured": True,
        "allow_ai": True,
        "allow_priority": False,
        "allow_collections": False,
    },
    {
        "key": "studio",
        "name": "Studio",
        "badge": "👑",
        "audience": "Artistes professionnels / collectifs",
        "features_text": "Tout Pro\nVisibilité prioritaire\nFonctionnalités IA avancées\nGestion de plusieurs collections\nOutils professionnels",
        "price_cents": 3990,
        "max_works": None,
        "sort": 40,
        "allow_stats": True,
        "allow_customize": True,
        "allow_share": True,
        "allow_advanced_stats": True,
        "allow_featured": True,
        "allow_ai": True,
        "allow_priority": True,
        "allow_collections": True,
    },
)


def seed_offers(*, force: bool = False) -> None:
    """Crée les offres manquantes et aligne le catalogue : un flag oublié
    en base ne doit pas laisser une promesse d’offre sans effet.

    L'alignement a lieu une fois par contexte d'application — soit une fois
    par requête. `force=True` le refait tout de suite, pour le code qui
    vient d'écrire une offre.
    """
    if not force and has_app_context() and getattr(g, _SEEDED, False):
        return
    changed = False
    for spec in CATALOG:
        offer = db.session.get(Offer, spec["key"])
        if offer is None:
            db.session.add(Offer(**spec))
            changed = True
            continue
        for key, value in spec.items():
            if key == "key":
                continue
            if getattr(offer, key) != value:
                setattr(offer, key, value)
                changed = True
    if changed:
        db.session.commit()
    if has_app_context():
        setattr(g, _SEEDED, True)
        # Une offre vient peut-être d'être créée ou réalignée : le cache de
        # lecture repart de zéro.
        setattr(g, _CACHE, {})


def forget_offers() -> None:
    """Oublier le catalogue mémorisé. À appeler après avoir écrit une offre."""
    if has_app_context():
        setattr(g, _SEEDED, False)
        setattr(g, _CACHE, {})


def get_offer(key: str | None) -> Offer | None:
    seed_offers()
    wanted = key or "decouverte"
    cache = getattr(g, _CACHE, None) if has_app_context() else None
    if cache is not None and wanted in cache:
        return cache[wanted]
    offer = db.session.get(Offer, wanted) or db.session.get(Offer, "decouverte")
    if cache is not None:
        cache[wanted] = offer
    return offer


def active_offers() -> list[Offer]:
    seed_offers()
    return Offer.query.filter_by(active=True).order_by(Offer.sort.asc()).all()


def all_offers() -> list[Offer]:
    seed_offers()
    return Offer.query.order_by(Offer.sort.asc()).all()
