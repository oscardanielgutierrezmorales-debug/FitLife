from __future__ import annotations

from dataclasses import dataclass

from .domain_classifier import classify_domain, off_topic_category
from .rules import INJECTION_TERMS, JAILBREAK_TERMS, UNSAFE_TERMS, contains_any


@dataclass(frozen=True)
class GuardrailDecision:
    allow: bool
    intent: str
    message: str | None = None


def evaluate_input(message: str) -> GuardrailDecision:
    if contains_any(message, INJECTION_TERMS):
        return GuardrailDecision(False, "INJECTION", "No puedo cambiar mis instrucciones. Puedo ayudarte con fitness, nutrición, bienestar o tu plan.")
    if contains_any(message, JAILBREAK_TERMS):
        return GuardrailDecision(False, "JAILBREAK", "No puedo desactivar las medidas de seguridad. Puedo ayudarte con tu plan de FitLife.")
    if contains_any(message, UNSAFE_TERMS):
        return GuardrailDecision(False, "UNSAFE", "No puedo orientar sobre esa solicitud. Si hay riesgo inmediato, busca ayuda profesional o servicios de emergencia locales.")
    intent = classify_domain(message)
    if intent == "OFF_TOPIC":
        category = off_topic_category(message)
        if category:
            return GuardrailDecision(False, intent, f"FitLife está diseñado para ayudarte con fitness, nutrición, recetas, bienestar y tu plan personalizado. No puedo responder preguntas generales de {category} desde este chat.")
        return GuardrailDecision(False, intent, "Esta pregunta está fuera del alcance de FitLife. Puedo ayudarte con tu rutina, ejercicios, alimentación, recetas, progreso y tu plan personalizado de 28 días.")
    return GuardrailDecision(True, intent)
