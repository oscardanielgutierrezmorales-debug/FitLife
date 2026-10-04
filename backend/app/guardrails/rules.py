from __future__ import annotations

import re
import unicodedata


def normalize(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(char))


def contains_any(value: str, terms: tuple[str, ...]) -> bool:
    normalized = normalize(value)
    return any(re.search(rf"\b{re.escape(normalize(term))}\b", normalized) for term in terms)


INJECTION_TERMS = ("ignore instrucciones", "ignora instrucciones", "system prompt", "prompt del sistema", "revela tus instrucciones", "actua como", "actúa como")
JAILBREAK_TERMS = ("jailbreak", "dan mode", "sin restricciones", "bypass", "evade tus reglas")
UNSAFE_TERMS = ("como suicidarme", "hacerme daño", "autolesion", "anorexia", "dejar de comer", "dieta de 500", "esteroides sin receta")

