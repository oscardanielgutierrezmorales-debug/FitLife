from __future__ import annotations

from app.agents.conversation import classify_conversation_intent
from app.agents.fitness import classify_exercise_intent
from app.guardrails.domain_classifier import classify_domain


def route(message: str) -> str:
    """Return a user-facing FitLife intent without weakening safety policy."""
    if conversational := classify_conversation_intent(message):
        return conversational
    domain = classify_domain(message)
    if domain == "FITNESS":
        return classify_exercise_intent(message).upper()
    if domain == "NUTRITION":
        normalized = message.casefold()
        return "RECIPE_INSTRUCTION" if any(term in normalized for term in ("receta", "prepar", "cocin", "ingrediente")) else "NUTRITION_QUERY"
    if domain == "PLAN":
        return "PLAN_QUERY"
    return domain


def route_domain(message: str) -> str:
    """Return the broad operational agent used by the existing pipeline."""
    return classify_domain(message)
