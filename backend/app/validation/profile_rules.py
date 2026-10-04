"""Single, backend-authoritative validation contract for FitLife profiles."""

from __future__ import annotations

import math
from typing import Any

from ..guardrails.profile_guardrail import ProfileSecurityError, assert_safe_profile_text


SUPPORTED_LANGUAGES = {"es", "en"}
SUPPORTED_SEX = {"female", "male", "non_binary", "prefer_not_to_say"}
SUPPORTED_GOALS = {"weight_loss", "hypertrophy", "endurance", "general_fitness"}
SUPPORTED_RESTRICTIONS = {
    "vegetarian": "vegetarian",
    "vegetariana": "vegetarian",
    "vegetariano": "vegetarian",
    "vegan": "vegan",
    "vegana": "vegan",
    "vegano": "vegan",
    "lactose_free": "lactose_free",
    "sin lactosa": "lactose_free",
    "dairy_free": "dairy_free",
    "sin lacteos": "dairy_free",
    "sin lácteos": "dairy_free",
    "gluten_free": "gluten_free",
    "sin gluten": "gluten_free",
    "nut_free": "nut_free",
    "sin frutos secos": "nut_free",
    "sin nueces": "nut_free",
}
NO_RESTRICTIONS = {"", "none", "nothing", "ninguna", "ninguno", "sin restricciones"}
PROFILE_FIELDS = {
    "language", "sex", "age", "height_cm", "weight_kg",
    "workout_hours_per_week", "goal", "dietary_restrictions", "available_days",
}


class ProfileValidationError(ValueError):
    """A safe, field-oriented error suitable for UI and direct API clients."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(next(iter(errors.values()), "El perfil no es válido."))

    def detail(self) -> dict[str, Any]:
        code = "INVALID_PROFILE_FIELD" if any(message == "El campo no está permitido en el perfil." for message in self.errors.values()) else "PROFILE_VALIDATION_ERROR"
        return {"code": code, "message": str(self), "field_errors": self.errors}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _required_string(raw: dict[str, Any], field: str, label: str, errors: dict[str, str]) -> str | None:
    value = raw.get(field)
    if not isinstance(value, str):
        errors[field] = f"Selecciona un valor válido para {label}."
        return None
    try:
        return assert_safe_profile_text(field, value).casefold()
    except ProfileSecurityError as exc:
        errors[field] = exc.message
        return None


def validate_profile_data(raw: Any, *, require_complete: bool = True) -> dict[str, Any]:
    """Validate, normalize and return a profile without persisting it.

    This intentionally does not use the LLM. It is deterministic, performs no
    logging of health values, and is called both when saving and generating.
    """
    if not isinstance(raw, dict):
        raise ProfileValidationError({"profile": "El perfil debe enviarse como un objeto válido."})

    errors: dict[str, str] = {}
    unknown = set(raw) - PROFILE_FIELDS
    for field in sorted(unknown):
        errors[field] = "El campo no está permitido en el perfil."
    missing = PROFILE_FIELDS - set(raw)
    if require_complete:
        for field in sorted(missing):
            errors[field] = "Este campo es obligatorio para generar un plan seguro."

    language = _required_string(raw, "language", "el idioma", errors)
    if language is not None and language not in SUPPORTED_LANGUAGES:
        errors["language"] = "El idioma debe ser Español o English."

    sex = _required_string(raw, "sex", "el sexo", errors)
    if sex is not None and sex not in SUPPORTED_SEX:
        errors["sex"] = "Selecciona una de las opciones de sexo disponibles."

    goal = _required_string(raw, "goal", "el objetivo", errors)
    if goal is not None and goal not in SUPPORTED_GOALS:
        errors["goal"] = "Selecciona uno de los objetivos disponibles de FitLife."

    age = raw.get("age")
    if not isinstance(age, int) or isinstance(age, bool) or not 13 <= age <= 120:
        errors["age"] = "La edad debe ser un número entero entre 13 y 120 años."

    def valid_measurement(field: str, label: str, minimum: float, maximum: float) -> float | None:
        value = raw.get(field)
        if not _is_number(value) or not minimum <= float(value) <= maximum:
            errors[field] = f"{label} debe estar entre {minimum:g} y {maximum:g}."
            return None
        return float(value)

    height = valid_measurement("height_cm", "La estatura", 80, 250)
    weight = valid_measurement("weight_kg", "El peso", 25, 400)
    hours = raw.get("workout_hours_per_week")
    normalized_hours: float | None = None
    if not _is_number(hours):
        errors["workout_hours_per_week"] = "Las horas semanales deben ser un número entre 1 y 28."
    elif float(hours) > 28:
        errors["workout_hours_per_week"] = "Las horas semanales ingresadas superan el límite seguro permitido (máximo 28 hrs/semana)."
    elif float(hours) < 1:
        errors["workout_hours_per_week"] = "Las horas semanales deben ser de al menos 1 hr/semana."
    else:
        normalized_hours = float(hours)

    raw_days = raw.get("available_days")
    normalized_days: list[int] = []
    if not isinstance(raw_days, list):
        errors["available_days"] = "Selecciona al menos un día disponible."
    elif not raw_days:
        errors["available_days"] = "Selecciona al menos un día disponible."
    elif len(raw_days) > 7 or any(not isinstance(day, int) or isinstance(day, bool) or day < 0 or day > 6 for day in raw_days):
        errors["available_days"] = "Los días disponibles deben estar entre lunes (0) y domingo (6)."
    elif len(set(raw_days)) != len(raw_days):
        errors["available_days"] = "No repitas días disponibles."
    else:
        normalized_days = sorted(raw_days)

    raw_restrictions = raw.get("dietary_restrictions")
    restrictions: list[str] = []
    if not isinstance(raw_restrictions, list):
        errors["dietary_restrictions"] = "Las restricciones alimentarias deben enviarse como una lista."
    elif len(raw_restrictions) > len(SUPPORTED_RESTRICTIONS):
        errors["dietary_restrictions"] = "Selecciona únicamente las restricciones alimentarias disponibles."
    else:
        for item in raw_restrictions:
            if not isinstance(item, str):
                errors["dietary_restrictions"] = "Cada restricción alimentaria debe ser texto válido."
                break
            try:
                normalized = assert_safe_profile_text("dietary_restrictions", item).casefold()
            except ProfileSecurityError as exc:
                errors["dietary_restrictions"] = exc.message
                break
            if normalized in NO_RESTRICTIONS:
                continue
            mapped = SUPPORTED_RESTRICTIONS.get(normalized)
            if not mapped:
                errors["dietary_restrictions"] = "Una o más restricciones alimentarias no son compatibles con FitLife."
                break
            restrictions.append(mapped)
        if len(set(restrictions)) != len(restrictions):
            errors["dietary_restrictions"] = "No repitas restricciones alimentarias."
        restrictions = [item for item in ("vegetarian", "vegan", "lactose_free", "dairy_free", "gluten_free", "nut_free") if item in restrictions]
        if "vegan" in restrictions:
            restrictions.remove("vegetarian")

    if normalized_hours is not None and normalized_days:
        safe_capacity = len(normalized_days) * 6
        if normalized_hours > safe_capacity:
            errors["workout_hours_per_week"] = (
                f"Con {len(normalized_days)} día(s) disponible(s), el máximo seguro es "
                f"{safe_capacity} hrs/semana (hasta 6 hrs por día)."
            )

    if errors:
        raise ProfileValidationError(errors)
    return {
        "language": language,
        "sex": sex,
        "age": age,
        "height_cm": height,
        "weight_kg": weight,
        "workout_hours_per_week": normalized_hours,
        "goal": goal,
        "dietary_restrictions": restrictions,
        "available_days": normalized_days,
    }
