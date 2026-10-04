from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.rag.retriever import LocalRetriever


MEAL_STOP_WORDS = {
    "como", "hacer", "hago", "preparo", "preparar", "cocino", "cocinar",
    "dame", "dar", "quiero", "quisiera", "puedes", "podrias",
    "la", "el", "los", "las", "de", "con", "mi", "en", "plan", "receta",
    "comida", "desayuno", "cena", "colacion", "esta", "este", "que", "por",
    "para", "un", "una", "del", "al", "y", "hoy",
}
PREPARATION_TERMS = ("prepar", "cocin", "receta", "ingrediente", "tiempo", "horno", "sustitu")


@dataclass(frozen=True)
class PlanNutritionAnswer:
    message: str
    day: dict[str, Any]
    meal: dict[str, Any]
    knowledge: str = ""


def _normalize(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(char))


def _canonical_term(word: str) -> str:
    """Fold common Spanish plurals so an entity keeps its semantic weight."""
    if len(word) > 5 and word.endswith("ces"):
        return f"{word[:-3]}z"
    if len(word) > 4 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _terms(value: str) -> set[str]:
    return {
        _canonical_term(word)
        for word in re.findall(r"[a-zñ0-9]+", _normalize(value))
        if len(word) > 2 and word not in MEAL_STOP_WORDS
    }


def _payload(day: dict[str, Any]) -> dict[str, Any]:
    return day.get("payload", day)


def _recipe_guidance(meal: dict[str, Any], knowledge: str = "") -> tuple[list[str], list[str], str]:
    """Deterministic preparation guidance tied to the exact persisted meal name."""
    name = str(meal["name"])
    normalized = _normalize(name)
    if "tacos de tortilla de maiz" in normalized:
        protein = "tofu desmenuzado" if "tofu" in normalized else "pollo cocido y deshebrado"
        ingredients, steps, duration = ["tortillas de maíz", protein, "verduras para ensalada", "especias suaves"], [f"Calienta el {protein} con especias y una pequeña cantidad de aceite.", "Calienta las tortillas en un comal.", "Sirve el relleno, añade la ensalada y dobla los tacos."], "8–12 min una vez que el pollo o tofu esté cocido."
    elif "papa al horno" in normalized:
        ingredients, steps, duration = ["papa", "aceite", "especias", "verduras"], ["Lava y corta la papa.", "Mézclala con poco aceite y especias.", "Hornea hasta que esté suave y dorada."], "30–40 min a 200 °C."
    elif "garbanzo" in normalized:
        ingredients, steps, duration = ["garbanzos cocidos", "verduras", "limón", "aceite de oliva"], ["Mezcla los garbanzos con las verduras picadas.", "Aliña con limón, aceite y hierbas."], "5–10 min; usa garbanzos ya cocidos."
    elif "verduras salteadas" in normalized:
        protein = "tofu" if "tofu" in normalized else "pollo"
        ingredients, steps, duration = ["verduras", protein, "aceite", "especias"], [f"Cocina el {protein} hasta que esté bien cocido.", "Saltea las verduras a fuego medio-alto.", "Combina y sazona al final."], "10–15 min."
    else:
        ingredients, steps, duration = [name], [meal.get("instructions", "Prepara los ingredientes con poca grasa y ajusta las especias a tus restricciones.")], "El tiempo depende de los ingredientes frescos."

    # The plan decides *what* to prepare. When RAG has a relevant culinary
    # guide, it replaces generic technique text while keeping the exact meal.
    if knowledge:
        rag_steps = [part.strip() for part in re.split(r"(?<=[.!?])\s+", knowledge) if part.strip()]
        if rag_steps:
            steps = rag_steps
    return ingredients, steps, duration


def _meal_response(meal: dict[str, Any], day: dict[str, Any], *, preparation: bool, knowledge: str = "") -> str:
    if not preparation:
        return f"Según tu plan del {day['date']}, {meal['meal_type'].casefold()} es {meal['name']}: {meal['calories']} kcal estimadas."
    ingredients, steps, duration = _recipe_guidance(meal, knowledge)
    ingredient_lines = "\n".join(f"- {ingredient}" for ingredient in ingredients)
    step_lines = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    return "\n\n".join([
        f"### {meal['name']}",
        f"En tu plan del {day['date']} corresponde a **{meal['meal_type'].casefold()}**.",
        f"**Ingredientes**\n{ingredient_lines}",
        f"**Preparación**\n{step_lines}",
        f"**Tiempo aproximado:** {duration}",
        f"**Porción:** {meal['portions']}.",
    ])


def _meal_type_reference(question: str) -> str | None:
    normalized = _normalize(question)
    if re.search(r"\b(desayuno|mi desayuno)\b", normalized):
        return "Desayuno"
    if re.search(r"\b(cena|mi cena)\b", normalized):
        return "Cena"
    if re.search(r"\b(colacion|snack|mi colacion)\b", normalized):
        return "Colación"
    if re.search(r"\b(mi comida|la comida de hoy|comida del dia)\b", normalized):
        return "Comida"
    return None


def find_plan_meal(question: str, selected_day: dict[str, Any], days: list[dict[str, Any]], history: list[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find a requested meal in the authenticated user's persisted plan only."""
    query = question if not history or _terms(question) or _meal_type_reference(question) else f"{history[-1]} {question}"
    query_terms = _terms(query)
    meal_type = _meal_type_reference(question)
    selected = _payload(selected_day)
    if meal_type and not query_terms:
        meal = next((item for item in selected.get("nutrition", {}).get("meals", []) if item.get("meal_type") == meal_type), None)
        return (selected, meal) if meal else None

    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    selected_date = selected.get("date")
    for raw_day in days:
        day = _payload(raw_day)
        for meal in day.get("nutrition", {}).get("meals", []):
            name_terms = _terms(str(meal.get("name", "")))
            overlap = len(query_terms & name_terms)
            if not overlap:
                continue
            query_coverage = overlap / max(1, len(query_terms))
            name_coverage = overlap / max(1, len(name_terms))
            # The requested entity has priority over incidental generic words
            # such as "ensalada". Selected-day proximity only breaks true ties.
            score = (query_coverage * 2.0) + name_coverage
            if query_terms <= name_terms:
                score += 0.5
            if meal_type and meal.get("meal_type") == meal_type:
                score += 0.3
            if day.get("date") == selected_date:
                score += 0.03
            candidates.append((score, day, meal))
    if not candidates:
        return None
    score, day, meal = max(candidates, key=lambda item: item[0])
    return (day, meal) if score >= 1.15 else None


def plan_nutrition_answer(question: str, day: dict[str, Any], days: list[dict[str, Any]] | None = None, history: list[str] | None = None, retriever: LocalRetriever | None = None) -> PlanNutritionAnswer | None:
    normalized = _normalize(question)
    selected = _payload(day)
    plan_days = days or [selected]
    if any(term in normalized for term in PREPARATION_TERMS):
        matched = find_plan_meal(question, selected, plan_days, history)
        if matched:
            matched_day, meal = matched
            knowledge = nutrition_context(str(meal["name"]), retriever) if retriever else ""
            return PlanNutritionAnswer(_meal_response(meal, matched_day, preparation=True, knowledge=knowledge), matched_day, meal, knowledge)

    meals = selected["nutrition"]["meals"]
    if any(word in normalized for word in ("caloria", "kcal")):
        breakfast = next((meal for meal in meals if meal["meal_type"] == "Desayuno"), None)
        if "desayuno" in normalized and breakfast:
            return PlanNutritionAnswer(_meal_response(breakfast, selected, preparation=False), selected, breakfast)
        requested = next((meal for meal in meals if _normalize(meal["meal_type"]) in normalized), None)
        if requested:
            return PlanNutritionAnswer(_meal_response(requested, selected, preparation=False), selected, requested)
    return None


def plan_nutrition_response(question: str, day: dict[str, Any], days: list[dict[str, Any]] | None = None, history: list[str] | None = None) -> str | None:
    answer = plan_nutrition_answer(question, day, days, history)
    if answer:
        return answer.message
    selected = _payload(day)
    meals = selected["nutrition"]["meals"]
    normalized = _normalize(question)
    if any(word in normalized for word in ("caloria", "kcal")):
        total = sum(meal["calories"] for meal in meals)
        detail = "; ".join(f"{meal['meal_type']}: {meal['calories']} kcal" for meal in meals)
        return f"Según tu plan del {selected['date']}: {detail}. Total del día: {total} kcal estimadas."
    return None


def nutrition_context(question: str, retriever: LocalRetriever) -> str:
    results = retriever.retrieve(question, kind="nutrition")
    return "\n".join(item["text"] for item in results if item["score"] >= 0.34)
