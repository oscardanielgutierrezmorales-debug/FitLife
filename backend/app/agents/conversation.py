from __future__ import annotations

import re
import unicodedata
from typing import Literal


ConversationIntent = Literal["contextual_followup", "plan_question", "progress_question"]
ContextFocus = Literal["exercise", "meal", "overview"]


def _fold(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(char))


def classify_conversation_intent(message: str) -> ConversationIntent | None:
    """Recognize conversational references before exercise entity extraction.

    These patterns express the shape of a follow-up, rather than any exercise,
    meal, or plan item. This lets the persisted context answer it safely.
    """
    text = _fold(message).strip()
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
