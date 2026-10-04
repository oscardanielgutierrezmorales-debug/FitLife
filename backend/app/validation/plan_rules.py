"""Deterministic validation of a generated plan against its owner profile."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


RESTRICTION_FLAGS = {
    "vegetarian": ("contains_meat",),
    "vegan": ("contains_meat", "contains_dairy", "contains_egg"),
    "lactose_free": ("contains_lactose",),
    "dairy_free": ("contains_dairy",),
    "gluten_free": ("contains_gluten",),
    "nut_free": ("contains_nuts",),
}

GOAL_FOCUS = {
    "weight_loss": "acondicionamiento y fuerza de cuerpo completo",
    "hypertrophy": "fuerza e hipertrofia con técnica controlada",
    "endurance": "resistencia, movilidad y progresión gradual",
    "general_fitness": "condición física general y movilidad",
}


def validate_plan_against_profile(profile: dict[str, Any], days: list[dict[str, Any]]) -> dict[str, Any]:
    """Return structured violations without relying on meal-name keywords."""
    violations: list[dict[str, Any]] = []
    restrictions = set(profile.get("dietary_restrictions") or [])
    available = set(profile.get("available_days") or [])
    weekly_minutes: dict[int, int] = defaultdict(int)
    expected_focus = GOAL_FOCUS.get(str(profile.get("goal")))

    for day in days:
        day_index = int(day.get("day_index", 0))
        workout = day.get("workout") or {}
        if day.get("kind") == "workout":
            from datetime import date

            weekday = date.fromisoformat(str(day["date"])).weekday()
            if weekday not in available:
                violations.append({
                    "type": "training_availability",
                    "day": day_index + 1,
                    "date": day.get("date"),
                    "weekday": weekday,
                })
            weekly_minutes[int(day.get("week", 1))] += int(workout.get("duration_minutes") or 0)
        if expected_focus and workout.get("focus") != expected_focus:
            violations.append({
                "type": "goal_mismatch",
                "day": day_index + 1,
                "date": day.get("date"),
                "goal": profile.get("goal"),
            })

        for meal in (day.get("nutrition") or {}).get("meals", []):
            flags = meal.get("dietary_properties")
            if not isinstance(flags, dict):
                violations.append({
                    "type": "missing_dietary_metadata",
                    "day": day_index + 1,
                    "date": day.get("date"),
                    "meal": meal.get("meal_type"),
                    "item": meal.get("name"),
                })
                continue
            for restriction in restrictions:
                incompatible = [flag for flag in RESTRICTION_FLAGS.get(restriction, ()) if flags.get(flag) is True]
                if incompatible:
                    violations.append({
                        "type": "dietary_restriction",
                        "restriction": restriction,
                        "day": day_index + 1,
                        "date": day.get("date"),
                        "meal": meal.get("meal_type"),
                        "item": meal.get("name"),
                        "incompatible_properties": incompatible,
                    })

    allowed_minutes = float(profile.get("workout_hours_per_week") or 0) * 60
    for week, minutes in weekly_minutes.items():
        if minutes > allowed_minutes + 1:
            violations.append({
                "type": "weekly_training_capacity",
                "week": week,
                "planned_minutes": minutes,
                "available_minutes": int(allowed_minutes),
            })
    return {"valid": not violations, "violations": violations}
