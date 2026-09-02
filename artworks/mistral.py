import json
import re
import urllib.error
import urllib.request

from flask import current_app

API_URL = "https://api.mistral.ai/v1/chat/completions"


def mistral_ready() -> bool:
    return bool(current_app.config.get("MISTRAL_API_KEY"))


def _call(messages: list[dict], *, heavy: bool, max_tokens: int, temperature: float, json_mode: bool) -> str:
    key = current_app.config.get("MISTRAL_API_KEY") or ""
    if not key:
        raise RuntimeError("Clé Mistral absente.")
    model = current_app.config.get("MISTRAL_MODEL_HEAVY" if heavy else "MISTRAL_MODEL") or "mistral-small-latest"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", "replace")[:240]) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Mistral injoignable : {exc.reason}") from exc
    choices = data.get("choices") or []
    if not choices:
        return ""
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def complete(prompt: str, *, heavy: bool = False, max_tokens: int = 400, system: str = "") -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    return _call(messages, heavy=heavy, max_tokens=max_tokens, temperature=0.7, json_mode=False)


def _extract_json(raw: str) -> dict:
    """Le modèle borde parfois sa réponse — on va chercher l’objet."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def complete_json(prompt: str, *, heavy: bool = False, max_tokens: int = 900, system: str = "", temperature: float = 0.75) -> dict:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    raw = _call(messages, heavy=heavy, max_tokens=max_tokens, temperature=temperature, json_mode=True)
    data = _extract_json(raw)
    if not data:
        raise RuntimeError("Réponse Mistral illisible.")
    return data


# --------------------------------------------------------------- réseaux

SOCIAL_SYSTEM = """Tu écris pour Artworksdigital, une plateforme où chaque artiste ouvre SA
galerie — pas une marketplace, pas une boutique, pas un catalogue partagé.

Ton : sobre, sensible, éditorial. Phrases courtes. Jamais de superlatifs
publicitaires, jamais d’émojis dans le titre du visuel, jamais de « découvrez
vite » ni de promesse commerciale. Le vocabulaire est celui d’une exposition :
salle, accrochage, cartel, note d’intention, lumière, matière.

Tu réponds UNIQUEMENT par un objet JSON valide, sans commentaire autour."""

SOCIAL_SCHEMA = """{
  "caption": "texte du post, 2 à 5 phrases, français, prêt à publier",
  "hashtags": ["#sansAccent", "8 maximum, pertinents, en minuscules"],
  "alt": "description de l'image pour l'accessibilité, une phrase",
  "design": {
    "layout": "gallery | artwork | editorial | quote | poster",
    "kicker": "surtitre très court, 2 à 4 mots",
    "headline": "titre du visuel, 4 à 12 mots, sans point final",
    "subline": "sous-titre, une phrase courte",
    "palette": {"bg": "#rrggbb", "ink": "#rrggbb", "accent": "#rrggbb"}
  }
}"""

LAYOUT_GUIDE = """Choix de mise en page :
- "gallery" : une œuvre encadrée sur fond papier, cartel dessous. Le plus juste quand il y a une œuvre.
- "artwork" : l'œuvre en plein cadre, titre posé dessus. Fort, à réserver aux images contrastées.
- "editorial" : pas d'image, titre centré sur papier. Pour une annonce, une pensée.
- "quote" : une phrase entre guillemets, barre d'accent. Pour une citation d'artiste.
- "poster" : aplat de couleur en haut, texte dessous. Le plus graphique, pour une offre ou un événement.

Palette : fonds clairs et chauds (papier, sable, lin, craie), encre très sombre,
accent terreux (bronze, terre de Sienne, vert forêt, bleu ardoise). Le contraste
entre "ink" et "bg" doit rester fort."""


def generate_social(
    prompt: str,
    *,
    platform: str = "instagram",
    artist_name: str = "",
    work_title: str = "",
    work_cartel: str = "",
    work_note: str = "",
    link: str = "",
    has_image: bool = False,
    heavy: bool = False,
) -> dict:
    """Transforme une consigne libre en post complet : texte + brief de visuel."""
    context = [f"Réseau visé : {platform}."]
    if artist_name:
        context.append(f"Artiste : {artist_name}.")
    if work_title:
        context.append(f"Œuvre : {work_title}.")
    if work_cartel:
        context.append(f"Cartel : {work_cartel}.")
    if work_note:
        context.append(f"Note de l’artiste : {work_note[:400]}")
    if link:
        context.append(f"Lien à mentionner : {link}")
    context.append(
        "Un visuel de l’œuvre est disponible : privilégie \"gallery\" ou \"artwork\"."
        if has_image
        else "Aucune image d’œuvre n’est disponible : choisis \"editorial\", \"quote\" ou \"poster\"."
    )
    if platform == "instagram":
        context.append("Instagram : la légende peut respirer, les hashtags comptent.")
    elif platform == "facebook":
        context.append("Facebook : peu ou pas de hashtags, une phrase d’accroche claire.")

    user = (
        f"{LAYOUT_GUIDE}\n\n"
        f"Contexte :\n" + "\n".join(f"- {line}" for line in context) + "\n\n"
        f"Consigne de l’auteur : {prompt.strip()}\n\n"
        f"Réponds avec exactement cette forme :\n{SOCIAL_SCHEMA}"
    )
    data = complete_json(user, heavy=heavy, system=SOCIAL_SYSTEM, max_tokens=900)

    hashtags = data.get("hashtags")
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    tags = []
    for tag in (hashtags or [])[:8]:
        tag = str(tag).strip().lstrip("#")
        tag = re.sub(r"[^0-9A-Za-zÀ-ÿ_]", "", tag)
        if tag:
            tags.append(f"#{tag}")

    design = data.get("design") if isinstance(data.get("design"), dict) else {}
    return {
        "caption": str(data.get("caption") or "").strip(),
        "hashtags": tags,
        "alt": str(data.get("alt") or "").strip()[:400],
        "design": design,
    }


def generate_statement(artist_name: str, discipline: str, works: list[str], intent: str = "") -> str:
    """Note d’intention pour l’atelier — un texte, pas du JSON."""
    lines = ", ".join(works[:8]) or "un accrochage en cours"
    ask = intent.strip() or "Écris une note d’intention pour la salle."
    prompt = (
        f"Artiste : {artist_name}. Discipline : {discipline or 'non précisée'}.\n"
        f"Œuvres accrochées : {lines}.\n\n"
        f"{ask}\n\n"
        "Trois à cinq phrases, à la troisième personne, en français. "
        "Ton d’exposition : sobre, concret, sans jargon ni superlatif. "
        "Pas de liste, pas de titre, pas de guillemets autour du texte."
    )
    return complete(prompt, system=SOCIAL_SYSTEM.split("Tu réponds")[0], max_tokens=380)
