"""Le contrat d'un outil, et l'endroit où ils se déclarent.

Un outil dit ce qu'il fait, ce qu'il attend, ce qu'il exige comme droit, et
s'il change quelque chose. K.A.E.L. lit cette déclaration pour savoir ce
qu'il peut faire — il ne devine rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from artworks.kael import permissions

# Un risque n'est pas une opinion : il décide si la main humaine est requise.
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

#: Au-delà de ce niveau, l'outil ne s'exécute pas sans confirmation humaine.
CONFIRM_FROM = {HIGH, CRITICAL}


class ToolError(Exception):
    """Erreur attendue d'un outil : message rendu tel quel à K.A.E.L."""


class PermissionDenied(ToolError):
    """Le jeton présenté n'a pas la portée exigée."""


class ConfirmationRequired(Exception):
    """L'action est prête mais attend une main humaine.

    Porte de quoi l'expliquer : ce qui va se passer, sur quoi, et ce qui
    est irréversible."""

    def __init__(self, tool: str, intent: str, consequences: list[str], target: str = ""):
        super().__init__(intent)
        self.tool = tool
        self.intent = intent
        self.consequences = consequences
        self.target = target


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    permission: str
    handler: Callable[..., Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    risk: str = LOW
    mutating: bool = False
    category: str = "general"
    #: Ce que l'outil renvoie, en une phrase — aide K.A.E.L. à choisir.
    returns: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return self.risk in CONFIRM_FROM

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "permission": self.permission,
            "permission_label": permissions.LABELS.get(self.permission, ""),
            "risk": self.risk,
            "mutating": self.mutating,
            "requires_human_confirmation": self.needs_confirmation,
            "returns": self.returns,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }


_TOOLS: dict[str, Tool] = {}


def tool(
    name: str,
    *,
    description: str,
    permission: str,
    parameters: dict[str, Any] | None = None,
    risk: str = LOW,
    mutating: bool = False,
    category: str = "general",
    returns: str = "",
):
    """Déclare un outil. Le nom est unique : deux déclarations, une erreur."""

    def decorate(handler):
        if name in _TOOLS:
            raise RuntimeError(f"Outil K.A.E.L. déjà déclaré : {name}")
        _TOOLS[name] = Tool(
            name=name,
            description=description,
            permission=permission,
            handler=handler,
            parameters=parameters or {"type": "object", "properties": {}},
            risk=risk,
            mutating=mutating,
            category=category,
            returns=returns,
        )
        return handler

    return decorate


def get(name: str) -> Tool | None:
    return _TOOLS.get(name)


def all_tools() -> list[Tool]:
    return sorted(_TOOLS.values(), key=lambda item: (item.category, item.name))


def manifest(granted: frozenset[str] | None = None) -> dict[str, Any]:
    """Le catalogue, filtré sur ce que le jeton présenté peut réellement faire."""
    tools = all_tools()
    if granted is not None:
        tools = [item for item in tools if item.permission in granted]
    return {
        "application": "artworks-digital",
        "assistant": "K.A.E.L.",
        "version": 1,
        "permissions": [
            {"name": scope, "label": permissions.LABELS[scope], "implies": list(permissions.IMPLIES[scope])}
            for scope in permissions.ALL
        ],
        "granted": sorted(granted) if granted is not None else None,
        "confirmation_policy": {
            "confirm_from_risk": sorted(CONFIRM_FROM),
            "how": (
                "Un outil sensible répond 409 avec une carte de confirmation et un "
                "confirm_token. Rappeler le même outil avec les mêmes paramètres et "
                "ce jeton exécute l'action."
            ),
        },
        "tools": [item.describe() for item in tools],
    }
