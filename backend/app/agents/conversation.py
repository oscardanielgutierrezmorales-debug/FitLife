from __future__ import annotations

import re
import unicodedata
from typing import Literal


ConversationIntent = Literal[
    "contextual_followup", "plan_question", "progress_question",
    "SMALL_TALK", "APP_HELP", "PROFILE_QUERY", "PROFILE_SUMMARY", "PROFILE_REVIEW",
    "PLAN_SUMMARY", "ROUTINE_SUMMARY", "NUTRITION_SUMMARY", "PROGRESS_SUMMARY",
    "USER_QUERY", "PLAN_AUDIT", "PLAN_CONSTRAINT_CONFLICT",
]
ContextFocus = Literal["exercise", "meal", "overview"]


def _fold(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(char))


def classify_conversation_intent(message: str) -> ConversationIntent | None:
    """Recognize conversational references before exercise entity extraction.

    These patterns express the shape of a follow-up, rather than any exercise,
    meal, or plan item. This lets the persisted context answer it safely.
    """
    text = _fold(message).strip()
    if re.fullmatch(r"[¿?¡!.,\s]*(hola|buenos dias|buenas tardes|buenas noches|como estas|gracias|muchas gracias|perfecto|entendido|ok|okay)[¿?¡!.,\s]*", text):
        return "SMALL_TALK"
    if re.search(r"\b(que puedes hacer|en que me puedes ayudar|para que sirve fitlife|como funciona (fitlife|mi plan)|puedes (ayudarme|revisar|modificar)|que funciones tienes)\b", text):
        return "APP_HELP"
    if re.search(r"\b(como me llamo|cual es mi nombre|que nombre tengo|quien soy)\b", text):
        return "USER_QUERY"
    if re.search(r"\b(me estas poniendo|mi plan (tiene|incluye)|estas incluyendo|aparece).*(lacte|lactosa|gluten|nueces|frutos secos|carne|pollo|huevo)|\b(soy|tengo).*(sin lactosa|sin lacteos|vegano|vegana|vegetariano|vegetariana|sin gluten)\b", text):
        return "PLAN_CONSTRAINT_CONFLICT"
    if re.search(r"\b(mi plan|la dieta|la rutina).*(respeta|cumple|considera).*(perfil|restric)|\baudita (mi )?plan\b", text):
        return "PLAN_AUDIT"
    if re.search(r"\b(resumen|resume).*(mi )?perfil\b", text) or re.search(r"\by de mi perfil\b", text):
        return "PROFILE_SUMMARY"
    if re.search(r"\b(revisa|revisar|evalua|analiza) (mi )?perfil\b", text):
        return "PROFILE_REVIEW"
    if re.search(r"\b(que|cuales|cuantas|cuantos|dime).*(restricciones|objetivo|dias disponibles|horas por semana)|\bmi dieta considera|\bque informacion tienes de mi\b", text):
        return "PROFILE_QUERY"
    if re.search(r"\b(resumen|resume).*(mi )?(plan)\b", text) or re.search(r"\by de mi plan\b", text):
        return "PLAN_SUMMARY"
    if re.search(r"\b(resumen|resume).*(mi )?(rutina|entrenamiento)\b", text) or re.search(r"\bresumen general de mi rutina\b", text):
        return "ROUTINE_SUMMARY"
    if re.search(r"\b(resumen|resume).*(mi )?(alimentacion|dieta|comidas)|\bcomo esta organizada mi dieta\b|\bque tipo de alimentacion\b|\by de mi alimentacion\b", text):
        return "NUTRITION_SUMMARY"
    if re.search(r"\b(como voy|resume mi progreso|como voy con mi plan|que he completado|cuanto llevo)\b|\by como voy\b", text):
        return "PROGRESS_SUMMARY"
    # Progress questions are evaluated first: they refer to completed plan
    # state, not to the last subject discussed with the assistant.
    if re.search(
        r"\b(cual fue |que fue )?(mi )?(el |la )?(ultimo|ultima) (ejercicio|entrenamiento|movimiento).*(hice|realice|complete)|"
        r"\b(que hice la ultima vez|en que ejercicio me quede|que ejercicio hice al final)\b",
        text,
    ):
        return "progress_question"
    if re.search(
        r"\b(en que nos quedamos|que (fue|es) lo ultimo (que )?(vimos|hablamos|revisamos)|"
        r"cual fue el ultimo (ejercicio|tema|movimiento|alimento|comida).*(pregunt\w*|vimos|hablamos|revisamos)|"
        r"que estabamos (viendo|hablando|haciendo))\b",
        text,
    ):
        return "contextual_followup"
    if re.fullmatch(r"[¿?¡!.,\s]*(resume todo|y eso|y despues|que sigue)[¿?¡!.,\s]*", text):
        return "contextual_followup"
    if re.search(r"\b(en que dia (de mi rutina )?voy|que dia de mi rutina voy|que entrenamiento sigue|cual es (mi )?(siguiente|proximo) entrenamiento|progreso|cuanto(s)? dias? llevo)\b", text):
        return "progress_question"
    if re.search(
        r"\b(que me toca (hoy|ahora|este dia)|que (ejercicio|ejercicios|entrenamiento) (tengo que hacer|tengo|debo hacer|me toca)( .+)?|"
        r"que comida (tengo|me toca)( .+)?|que tengo que hacer( .+)?|que tengo el \d{1,2} de \w+|que dia (estoy viendo|tengo seleccionado|estoy revisando))\b",
        text,
    ):
        return "plan_question"
    return None


def asks_last_completed_exercise(message: str) -> bool:
    """Whether a progress turn asks for the last exercise actually performed."""
    text = _fold(message)
    return re.search(
        r"\b(ultimo|ultima) (ejercicio|entrenamiento|movimiento).*(hice|realice|complete)|"
        r"\b(que hice la ultima vez|en que ejercicio me quede|que ejercicio hice al final)\b",
        text,
    ) is not None


def contextual_focus(message: str) -> ContextFocus:
    """Select the memory fact requested by an already-classified follow-up."""
    text = _fold(message)
    if re.search(r"\bultimo (ejercicio|tema|movimiento).*(pregunt\w*|vimos|hablamos|revisamos)\b", text):
        return "exercise"
    if re.search(r"\bultima (comida|receta|alimentacion).*(vimos|hablamos|revisamos)?\b", text):
        return "meal"
    return "overview"
