from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from app.rag.retriever import LocalRetriever


ExerciseIntent = Literal["exercise_instruction", "routine_membership", "exercise_programming"]

# These are linguistic scaffolding, not a catalog of known exercises. The
# entity is matched only against the authenticated plan and the exercise KB.
STOP_WORDS = {
    "a", "al", "como", "cual", "cuanto", "cuantas", "de", "del", "dentro", "el", "elejercicio",
    "en", "encuentra", "encuentro", "es", "esta", "este", "hacer", "hacerlo", "hace", "hago",
    "la", "las", "lo", "los", "me", "mi", "no", "o", "para", "podria", "podrias", "puedes",
    "que", "realizar", "realizarlo", "se", "si", "su", "tecnica", "tecnicas", "un", "una", "y",
    "ejercicio", "rutina", "plan", "series", "repeticiones", "descanso", "paso", "pasos",
    "correcta", "correctamente", "aparece", "aparecer", "pertenece", "incluye", "forma", "parte",
}
CONNECTORS = {"de"}
TOKEN_PATTERN = re.compile(r"[a-záéíóúüñ0-9]+", re.IGNORECASE)


@dataclass(frozen=True)
class ExerciseEntity:
    label: str
    terms: frozenset[str]


@dataclass(frozen=True)
class ExerciseLookup:
    intent: ExerciseIntent
    entity: ExerciseEntity
    routine_match: dict[str, Any] | None
    knowledge: dict[str, Any] | None


def _normalize(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(char))


def _tokens(text: str) -> list[tuple[str, str]]:
    return [(word.casefold(), _normalize(word)) for word in TOKEN_PATTERN.findall(text)]


def extract_exercise_entity(question: str) -> ExerciseEntity:
    """Extract an exercise name while preserving its natural display order."""
    tokens = _tokens(question)
    meaningful = [index for index, (_, normalized) in enumerate(tokens) if normalized not in STOP_WORDS]
    if not meaningful:
        return ExerciseEntity("", frozenset())

    selected = set(meaningful)
    # Preserve a connector only when it joins two meaningful parts of a name:
    # "salto de superman", never the surrounding question wording.
    for index, (_, normalized) in enumerate(tokens):
        if normalized in CONNECTORS and index - 1 in selected and index + 1 in selected:
            selected.add(index)
    label = " ".join(surface for index, (surface, _) in enumerate(tokens) if index in selected)
    return ExerciseEntity(label, frozenset(tokens[index][1] for index in meaningful))


def classify_exercise_intent(question: str) -> ExerciseIntent:
    """Classify the requested type of answer independently from the domain guardrail."""
    normalized = _normalize(question)
    if re.search(r"\b(series|repeticiones|descanso|cuantas|cuantos|programad[oa])\b", normalized):
        return "exercise_programming"
    if re.search(r"\b(como|tecnica|tecnicas|pasos|realiz[ao]|ejecut[ao])\b", normalized):
        return "exercise_instruction"
    return "routine_membership"


def _plan_exercises(days: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for day in days:
        payload = day.get("payload", day)
        workout = payload.get("workout") if isinstance(payload, dict) else None
        exercises = workout.get("exercises", []) if isinstance(workout, dict) else []
        for exercise in exercises:
            if isinstance(exercise, dict) and isinstance(exercise.get("name"), str):
                entries.append((payload, exercise))
    return entries


def find_exercise_in_user_plan(entity: ExerciseEntity, days: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match only against the authenticated user's persisted routine."""
    if not entity.terms:
        return None
    ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for day, exercise in _plan_exercises(days):
        name_entity = extract_exercise_entity(exercise["name"])
        overlap = len(name_entity.terms & entity.terms)
        unknown_terms = entity.terms - name_entity.terms
        # A user assertion is never evidence. Every non-filler term must be
        # present in the actual routine before it is considered a match.
        if overlap and not unknown_terms:
            ranked.append((overlap / max(1, len(name_entity.terms)), day, exercise))
    if not ranked:
        return None
    _, day, exercise = max(ranked, key=lambda item: item[0])
    return {"day": day, "exercise": exercise}


def find_exercise_knowledge(entity: ExerciseEntity, retriever: LocalRetriever) -> dict[str, Any] | None:
    """Return a verified technical exercise record, never a merely similar hit."""
    if not entity.terms:
        return None
    candidates = retriever.retrieve(entity.label, kind="exercise")
    verified: list[dict[str, Any]] = []
    for candidate in candidates:
        aliases = candidate.get("aliases", [])
        candidate_entity = extract_exercise_entity(" ".join([str(candidate.get("name", "")), *map(str, aliases)]))
        # This allows natural shorthand ("remo") but rejects invented
        # modifiers ("salto de pokemon") from being mapped to a real exercise.
        if entity.terms <= candidate_entity.terms and candidate.get("score", 0) >= 0.34:
            verified.append(candidate)
    return max(verified, key=lambda item: item["score"]) if verified else None


def find_exercise(question: str, days: list[dict[str, Any]], retriever: LocalRetriever, history: list[str]) -> ExerciseLookup:
    """Resolve routine context and technical knowledge as separate sources."""
    intent = classify_exercise_intent(question)
    entity = extract_exercise_entity(question)
    # Generic programming follow-ups ("¿cuántas series?") can inherit the
    # prior entity. A valid named query never mixes with prior conversation.
    if not entity.terms and history:
        entity = extract_exercise_entity(history[-1])
    routine_match = find_exercise_in_user_plan(entity, days)
    knowledge = find_exercise_knowledge(entity, retriever)
    return ExerciseLookup(intent, entity, routine_match, knowledge)


def _routine_programming(match: dict[str, Any]) -> str:
    exercise = match["exercise"]
    return (
        f"{exercise['sets']} series de {exercise['repetitions']} repeticiones, "
        f"con {exercise['rest_seconds']} segundos de descanso."
    )


def exercise_response(lookup: ExerciseLookup) -> str:
    """Answer the user's requested kind of exercise question safely and clearly."""
    match, knowledge, entity = lookup.routine_match, lookup.knowledge, lookup.entity
    if lookup.intent == "exercise_programming":
        if match:
            exercise, day = match["exercise"], match["day"]
            return f"En tu rutina de {day['workout']['type']}, {exercise['name']} está programada como {_routine_programming(match)}"
        if knowledge:
            return f"{knowledge['name']} no aparece en tu rutina actual, así que no tengo series, repeticiones ni descanso personalizados para indicarte."
        return _unknown_exercise_response(entity)

    if lookup.intent == "routine_membership":
        if match:
            exercise, day = match["exercise"], match["day"]
            return f"Sí, {exercise['name']} aparece en tu rutina de {day['workout']['type']}: {_routine_programming(match)}"
        if knowledge:
            return f"{knowledge['name']} no aparece en tu rutina actual, aunque sí tengo una guía técnica verificada para ese ejercicio."
        return _unknown_exercise_response(entity)

    # Technical instruction: a routine match personalizes the prescription;
    # only the knowledge base provides the actual movement explanation.
    if knowledge:
        name = knowledge["name"]
        prefix = f"Para hacer {name}:\n{knowledge['text']}"
        if match:
            return f"{prefix}\n\nEn tu rutina aparece como {_routine_programming(match)}"
        return f"{name} no aparece en tu rutina actual, pero sí puedo explicarte cómo realizarlo.\n\n{prefix}"
    if match:
        exercise = match["exercise"]
        return (
            f"{exercise['name']} sí aparece en tu rutina como {_routine_programming(match)} "
            "No tengo una guía técnica verificada en la base local para explicarte su ejecución sin inventar indicaciones."
        )
    return _unknown_exercise_response(entity)


def _unknown_exercise_response(entity: ExerciseEntity) -> str:
    label = entity.label or "ese ejercicio"
    return (
        f"No encuentro un ejercicio identificado como “{label}” en tu rutina actual ni en la base de ejercicios disponible. "
        "No quiero inventarte una técnica para un movimiento que no puedo identificar. "
        "Si te refieres a otro ejercicio, dime el nombre o descríbeme cómo es."
    )
