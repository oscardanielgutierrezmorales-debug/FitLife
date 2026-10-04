from __future__ import annotations

from .rules import contains_any


def validate_output(text: str, *, intent: str) -> str:
    """Return a safe replacement only when a generated response violates policy."""
    if contains_any(text, ("contraseña", "token jwt", "api key", "instrucciones internas")):
        return "No puedo compartir información sensible. Puedo ayudarte con fitness, nutrición, bienestar o tu plan."
    if intent == "OFF_TOPIC":
        return "Esta pregunta está fuera del alcance de FitLife. Puedo ayudarte con tu rutina, ejercicios, alimentación, recetas y tu plan personalizado de 28 días."
    return text
