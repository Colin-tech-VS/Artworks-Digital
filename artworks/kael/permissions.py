"""Les cinq portées de K.A.E.L. sur Artworks Digital.

Une portée n'est pas un rôle : c'est un droit précis, déclaré par chaque
outil et porté par chaque jeton. Un jeton de lecture ne peut rien écrire,
même si l'outil existe et même si K.A.E.L. le demande.
"""

from __future__ import annotations

READ = "KAEL_READ"
ANALYZE = "KAEL_ANALYZE"
WRITE = "KAEL_WRITE"
PUBLISH = "KAEL_PUBLISH"
ADMIN = "KAEL_ADMIN"

ALL = (READ, ANALYZE, WRITE, PUBLISH, ADMIN)

LABELS = {
    READ: "Lire les données de la plateforme",
    ANALYZE: "Analyser et produire des diagnostics",
    WRITE: "Modifier les contenus autorisés",
    PUBLISH: "Publier — galerie, réseaux, e-mails",
    ADMIN: "Administration : offres, comptes, suppressions",
}

# Une portée en implique d'autres : écrire suppose de pouvoir lire ce qu'on
# modifie. L'inverse n'est jamais vrai.
IMPLIES = {
    READ: (),
    ANALYZE: (READ,),
    WRITE: (READ, ANALYZE),
    PUBLISH: (READ, ANALYZE),
    ADMIN: (READ, ANALYZE, WRITE, PUBLISH),
}


def expand(scopes) -> frozenset[str]:
    """Développe les portées accordées avec tout ce qu'elles impliquent."""
    granted: set[str] = set()
    for scope in scopes or ():
        scope = str(scope).strip().upper()
        if scope not in IMPLIES:
            continue
        granted.add(scope)
        granted.update(IMPLIES[scope])
    return frozenset(granted)


def normalize(scopes) -> list[str]:
    """Garde l'ordre canonique et jette ce qui n'existe pas."""
    wanted = {str(s).strip().upper() for s in (scopes or ())}
    return [scope for scope in ALL if scope in wanted]


def allows(granted: frozenset[str], required: str) -> bool:
    return required in granted
