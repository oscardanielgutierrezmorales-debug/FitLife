from __future__ import annotations

import re

from .rules import normalize


DOMAINS: dict[str, tuple[str, ...]] = {
    "FITNESS": ("ejercicio", "entren", "rutina", "series", "repeticiones", "descanso", "peso", "mancuerna", "remo", "sentadilla", "flexion", "press", "salto", "cardio", "movilidad"),
    "NUTRITION": ("comida", "comer", "desayuno", "cena", "caloria", "caloría", "proteina", "proteína", "receta", "prepar", "cocinar", "ingrediente", "garbanzo", "papa", "pollo", "macro"),
    "PLAN": ("mi plan", "hoy", "mañana", "calendario", "me toca", "progreso", "completado"),
    "WELLNESS": ("sueño", "sueno", "hidrat", "bienestar", "estrés", "estres", "recuperación", "recuperacion"),
}


OFF_TOPIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "programación": (r"\b(python|sql|javascript|typescript|programacion|script|codigo|base de datos|api|software)\b",),
    "matemáticas": (r"\b(matematica|algebra|ecuacion|geometria)\b", r"\b\d+\s*[+*/x-]\s*\d+\b"),
    "videojuegos": (r"\b(pokemon|videojuego|gaming|consola)\b",),
    "ciencias o historia": (r"\b(fisica|newton|historia|geografia|politica)\b",),
}


def off_topic_category(message: str) -> str | None:
    normalized = normalize(message)
    for category, patterns in OFF_TOPIC_PATTERNS.items():
        candidate = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", normalized) if category == "matemáticas" else normalized
        if any(re.search(pattern, candidate) for pattern in patterns):
            return category
    return None


def classify_domain(message: str) -> str:
    category = off_topic_category(message)
    normalized = normalize(message)
    # A named but unknown movement (for example, an invented modifier after
    # "salto") is still an exercise-shaped FitLife request. It must reach the
    # deterministic exercise validator, which can safely reject the movement;
    # a general videogame/cooking question must remain off-topic.
    exercise_signal = any(term in normalized for term in ("ejercicio", "rutina", "series", "repeticiones", "descanso", "salto", "sentadilla", "flexion", "remo", "press"))
    if category and not (category == "videojuegos" and exercise_signal):
        return "OFF_TOPIC"
    scores = {name: sum(normalize(term) in normalized for term in terms) for name, terms in DOMAINS.items()}
    # A food question can legitimately mention training (for example, a
    # post-workout meal). On a tie favour the more specific nutrition intent.
    priority = {"NUTRITION": 4, "PLAN": 3, "FITNESS": 2, "WELLNESS": 1}
    best, score = max(scores.items(), key=lambda item: (item[1], priority[item[0]]))
    return best if score else "OFF_TOPIC"
