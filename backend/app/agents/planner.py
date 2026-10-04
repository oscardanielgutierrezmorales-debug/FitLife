from __future__ import annotations

from datetime import date, timedelta
from typing import Any


EXERCISE_BLOCKS = [
    ("Cuerpo completo A", [("Sentadilla con peso corporal", 3, "10–12"), ("Flexión inclinada", 3, "8–10"), ("Remo con banda", 3, "10–12")]),
    ("Cadena posterior y core", [("Peso muerto con mochila", 3, "10"), ("Puente de glúteo", 3, "12–15"), ("Plancha inclinada", 3, "20–30 s")]),
    ("Torso empuje", [("Press de pecho con mancuernas", 3, "8–12"), ("Flexión inclinada", 3, "8–10"), ("Plancha inclinada", 3, "20–30 s")]),
    ("Torso tracción", [("Remo con mancuerna", 3, "10–12"), ("Remo con banda", 3, "10–12"), ("Peso muerto con mochila", 3, "8–10")]),
    ("Pierna y estabilidad", [("Sentadilla a caja", 3, "10"), ("Zancada asistida", 3, "8 por lado"), ("Puente de glúteo", 3, "12")]),
    ("Movilidad y resistencia", [("Caminata rápida", 1, "20 min"), ("Movilidad de cadera", 2, "45 s"), ("Plancha inclinada", 2, "20 s")]),
]

BREAKFASTS = ["Avena con yogur, frutos rojos y nueces", "Tostada integral con huevo, jitomate y fruta", "Avena nocturna con chía y plátano", "Yogur con fruta, avena y semillas", "Tacos de frijol con aguacate", "Licuado de fruta, avena y crema de cacahuate", "Pudín de chía con fruta y almendras"]
LUNCHES = ["Bowl de arroz, verduras y pollo", "Ensalada de garbanzo, papa y verduras", "Tacos de tortilla de maíz con pollo y ensalada", "Lentejas guisadas con verduras y arroz", "Pasta integral con verduras y pollo", "Papa al horno con ensalada y pollo", "Salteado de verduras, arroz y pollo"]
SNACKS = ["Fruta con semillas", "Hummus con zanahoria", "Yogur con fruta", "Manzana con crema de cacahuate", "Palomitas naturales y fruta", "Tostada integral con aguacate", "Nueces y mandarina"]
DINNERS = ["Sopa de lentejas con ensalada", "Verduras salteadas con pollo", "Ensalada tibia de papa y verduras", "Tacos de frijol con verduras", "Crema de verduras y tostada integral", "Arroz con verduras y pollo", "Ensalada de garbanzo con tortilla de maíz"]


def _meal(kind: str, name: str, calories: int, day_index: int) -> dict[str, Any]:
    portions = "1 porción" if kind != "Comida" else "1 plato"
    return {"meal_type": kind, "name": name, "ingredients": [name], "portions": portions, "calories": calories, "macros": {"protein_g": round(calories * 0.22 / 4), "carbs_g": round(calories * 0.48 / 4), "fat_g": round(calories * 0.30 / 9)}, "instructions": "Lava los ingredientes, cocina con poca grasa y ajusta sal/especias a tus restricciones.", "alternative": f"Alternativa del día {(day_index % 7) + 1}: cambia por otra comida equivalente del calendario."}


def _restriction_safe(name: str, restrictions: list[str]) -> str:
    text = " ".join(restrictions).casefold()
    if any(word in text for word in ("vegana", "vegan")):
        name = name.replace("yogur", "yogur vegetal").replace("huevo", "tofu").replace("pollo", "tofu").replace("crema", "crema vegetal")
    elif any(word in text for word in ("vegetar",)):
        name = name.replace("pollo", "tofu")
    if "lactosa" in text or "lactose_free" in text:
        name = name.replace("yogur", "yogur sin lactosa")
    if "gluten_free" in text or "sin gluten" in text:
        name = name.replace("Avena", "Avena certificada sin gluten").replace("Tostada integral", "Tostada sin gluten").replace("Pasta integral", "Pasta sin gluten")
    if "nut_free" in text or "sin frutos secos" in text:
        name = name.replace("nueces", "semillas").replace("almendras", "semillas").replace("crema de cacahuate", "crema de semillas")
    return name


def _daily_calorie_target(profile: dict[str, Any]) -> int:
    """A general-wellness planning target, not a diagnosis or medical prescription."""
    age = float(profile["age"])
    height = float(profile["height_cm"])
    weight = float(profile["weight_kg"])
    goal_adjustment = {
        "weight_loss": -250,
        "hypertrophy": 200,
        "endurance": 100,
        "general_fitness": 0,
    }[profile["goal"]]
    baseline = 1300 + (weight * 7) + (height * 1.5) - max(age - 30, 0) * 5 + goal_adjustment
    return int(max(1400, min(3000, round(baseline / 10) * 10)))


def _goal_focus(goal: str) -> str:
    return {
        "weight_loss": "acondicionamiento y fuerza de cuerpo completo",
        "hypertrophy": "fuerza e hipertrofia con técnica controlada",
        "endurance": "resistencia, movilidad y progresión gradual",
        "general_fitness": "condición física general y movilidad",
    }[goal]


def generate_plan(profile: dict[str, Any], start: date | None = None) -> list[dict[str, Any]]:
    """Build 28 persisted, structured days; no frontend or LLM generation is used."""
    start = start or date.today()
    available = sorted(set(profile.get("available_days") or [0, 2, 4]))
    hours = float(profile.get("workout_hours_per_week") or 3)
    sessions = min(len(available), max(2, round(hours / 1.25)))
    training_days = set(available[:sessions])
    restrictions = list(profile.get("dietary_restrictions") or [])
    daily_target = _daily_calorie_target(profile)
    focus = _goal_focus(profile["goal"])
    duration = max(30, min(75, round(hours * 60 / max(1, sessions) / 5) * 5))
    days: list[dict[str, Any]] = []
    training_number = 0
    for index in range(28):
        current = start + timedelta(days=index)
        training = current.weekday() in training_days
        week = index // 7 + 1
        if training:
            # Rotate across real sessions, not calendar offsets, so every
            # block remains reachable with any choice of available weekdays.
            title, raw_exercises = EXERCISE_BLOCKS[training_number % len(EXERCISE_BLOCKS)]
            exercises = [{"name": name, "sets": sets + (1 if week == 3 else 0), "repetitions": reps if week != 4 else f"{reps}, técnica controlada", "rest_seconds": 90 if "Torso" in title else 75, "instructions": "Mantén técnica controlada y detente si aparece dolor agudo."} for name, sets, reps in raw_exercises]
            workout = {"type": title, "focus": focus, "duration_minutes": duration + (5 if week == 3 else 0), "warmup": ["3 min de caminata suave", "Movilidad dinámica", "Serie de práctica"], "exercises": exercises, "recovery": "5–7 min de respiración y estiramientos suaves."}
            kind = "workout"
            training_number += 1
        else:
            kind = "recovery" if current.weekday() in available else "rest"
            title = "Recuperación activa" if kind == "recovery" else "Descanso y movilidad"
            workout = {"type": title, "focus": focus, "duration_minutes": 20 if kind == "recovery" else 10, "warmup": [], "exercises": [], "recovery": "Caminata suave, movilidad y prioriza sueño e hidratación."}
        names = [BREAKFASTS[index % 7], LUNCHES[(index + week) % 7], SNACKS[(index * 2 + week) % 7], DINNERS[(index * 3 + week) % 7]]
        variation = ((index + week) % 5 - 2) * 20
        target_for_day = daily_target + variation
        meal_bases = [round(target_for_day * ratio / 10) * 10 for ratio in (0.24, 0.36, 0.12, 0.28)]
        meals = [_meal(kind_name, _restriction_safe(name, restrictions), calories, index) for kind_name, name, calories in zip(("Desayuno", "Comida", "Colación", "Cena"), names, meal_bases)]
        days.append({"date": current.isoformat(), "week": week, "day_index": index, "kind": kind, "title": title, "workout": workout, "nutrition": {"meals": meals, "daily_calories": sum(meal["calories"] for meal in meals), "daily_targets": f"Objetivo general: {focus}. Prioriza proteína suficiente, verduras, fibra e hidratación."}, "notes": "Orientación general de bienestar; no sustituye atención médica, nutricional ni de emergencia."})
    return days
