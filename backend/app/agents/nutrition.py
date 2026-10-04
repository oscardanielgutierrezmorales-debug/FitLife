from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.rag.retriever import LocalRetriever


MEAL_STOP_WORDS = {"como", "hacer", "hago", "preparo", "preparar", "cocino", "cocinar", "la", "el", "los", "las", "de", "con", "mi", "en", "plan", "receta", "comida", "esta", "este", "que", "por", "para", "un", "una", "del", "al", "y"}
PREPARATION_TERMS = ("prepar", "cocin", "receta", "ingrediente", "tiempo", "horno", "sustitu")


def _normalize(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(char))


def _terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-zñ0-9]+", _normalize(value)) if len(word) > 2 and word not in MEAL_STOP_WORDS}


def _payload(day: dict[str, Any]) -> dict[str, Any]:
    return day.get("payload", day)


def _recipe_guidance(meal: dict[str, Any]) -> tuple[list[str], list[str], str]:
    """Deterministic preparation guidance tied to the exact persisted meal name."""
    name = str(meal["name"])
    normalized = _normalize(name)
    if "tacos de tortilla de maiz" in normalized:
        protein = "tofu desmenuzado" if "tofu" in normalized else "pollo cocido y deshebrado"
        return (["tortillas de maíz", protein, "verduras para ensalada", "especias suaves"], [f"Calienta el {protein} con especias y una pequeña cantidad de aceite.", "Calienta las tortillas en un comal.", "Sirve el relleno, añade la ensalada y dobla los tacos."], "8–12 min una vez que el pollo o tofu esté cocido.")
    if "papa al horno" in normalized:
        return (["papa", "aceite", "especias", "verduras"], ["Lava y corta la papa.", "Mézclala con poco aceite y especias.", "Hornea hasta que esté suave y dorada."], "30–40 min a 200 °C.")
    if "garbanzo" in normalized:
        return (["garbanzos cocidos", "verduras", "limón", "aceite de oliva"], ["Mezcla los garbanzos con las verduras picadas.", "Aliña con limón, aceite y hierbas."], "5–10 min; usa garbanzos ya cocidos.")
    if "verduras salteadas" in normalized:
        protein = "tofu" if "tofu" in normalized else "pollo"
        return (["verduras", protein, "aceite", "especias"], [f"Cocina el {protein} hasta que esté bien cocido.", "Saltea las verduras a fuego medio-alto.", "Combina y sazona al final."], "10–15 min.")
    return ([name], [meal.get("instructions", "Prepara los ingredientes con poca grasa y ajusta las especias a tus restricciones.")], "El tiempo depende de los ingredientes frescos.")


def _meal_response(meal: dict[str, Any], day: dict[str, Any], *, preparation: bool) -> str:
    if not preparation:
        return f"Según tu plan del {day['date']}, {meal['meal_type'].casefold()} es {meal['name']}: {meal['calories']} kcal estimadas."
    ingredients, steps, duration = _recipe_guidance(meal)
    return "\n".join([f"En tu plan del {day['date']} aparece {meal['name']}.", f"Ingredientes principales: {', '.join(ingredients)}.", "Preparación: " + " ".join(steps), f"Tiempo orientativo: {duration}", f"Porción del plan: {meal['portions']}."])


def find_plan_meal(question: str, selected_day: dict[str, Any], days: list[dict[str, Any]], history: list[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find a requested meal in the authenticated user's persisted plan only."""
    query = question if not history or _terms(question) else f"{history[-1]} {question}"
    query_terms = _terms(query)
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    selected_date = _payload(selected_day).get("date")
    for raw_day in days:
        day = _payload(raw_day)
        for meal in day.get("nutrition", {}).get("meals", []):
            name_terms = _terms(str(meal.get("name", "")))
            overlap = len(query_terms & name_terms)
            if not overlap:
                continue
            score = overlap / max(1, len(query_terms)) + overlap / max(1, len(name_terms))
            if day.get("date") == selected_date:
                score += 0.08
            candidates.append((score, day, meal))
    if not candidates:
        return None
    score, day, meal = max(candidates, key=lambda item: item[0])
    return (day, meal) if score >= 0.34 else None


def plan_nutrition_response(question: str, day: dict[str, Any], days: list[dict[str, Any]] | None = None, history: list[str] | None = None) -> str | None:
    normalized = _normalize(question)
    selected = _payload(day)
    plan_days = days or [selected]
    if any(term in normalized for term in PREPARATION_TERMS):
        matched = find_plan_meal(question, selected, plan_days, history)
        if matched:
            matched_day, meal = matched
            return _meal_response(meal, matched_day, preparation=True)

    meals = selected["nutrition"]["meals"]
    if any(word in normalized for word in ("caloria", "kcal")):
        breakfast = next((meal for meal in meals if meal["meal_type"] == "Desayuno"), None)
        if "desayuno" in normalized and breakfast:
            return _meal_response(breakfast, selected, preparation=False)
        requested = next((meal for meal in meals if _normalize(meal["meal_type"]) in normalized), None)
        if requested:
            return _meal_response(requested, selected, preparation=False)
        total = sum(meal["calories"] for meal in meals)
        detail = "; ".join(f"{meal['meal_type']}: {meal['calories']} kcal" for meal in meals)
        return f"Según tu plan del {selected['date']}: {detail}. Total del día: {total} kcal estimadas."
    return None


def nutrition_context(question: str, retriever: LocalRetriever) -> str:
    results = retriever.retrieve(question, kind="nutrition")
    return "\n".join(item["text"] for item in results if item["score"] >= 0.34)
