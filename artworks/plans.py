from artworks.extensions import db
from artworks.models import Offer

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


def seed_offers() -> None:
    """Crée les offres manquantes et aligne le catalogue : un flag oublié
    en base ne doit pas laisser une promesse d’offre sans effet."""
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


def get_offer(key: str | None) -> Offer | None:
    seed_offers()
    return db.session.get(Offer, key or "decouverte") or db.session.get(Offer, "decouverte")


def active_offers() -> list[Offer]:
    seed_offers()
    return Offer.query.filter_by(active=True).order_by(Offer.sort.asc()).all()


def all_offers() -> list[Offer]:
    seed_offers()
    return Offer.query.order_by(Offer.sort.asc()).all()
