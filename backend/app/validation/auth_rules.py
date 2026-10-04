"""Backend-authoritative, field-oriented validation for authentication."""

from __future__ import annotations

import re
from typing import Any


USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 80
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class AuthValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(next(iter(errors.values()), "Los datos de acceso no son válidos."))

    def detail(self) -> dict[str, Any]:
        first_field = next(iter(self.errors), None)
        return {
            "code": "AUTH_VALIDATION_ERROR",
            "field": first_field,
            "message": str(self),
            "field_errors": self.errors,
        }


def validate_credentials(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise AuthValidationError({"credentials": "Envía un usuario y una contraseña válidos."})

    errors: dict[str, str] = {}
    username = raw.get("username")
    password = raw.get("password")

    if not isinstance(username, str) or not username.strip():
        errors["username"] = "Ingresa un nombre de usuario."
    else:
        username = username.strip()
        if len(username) < USERNAME_MIN_LENGTH:
            errors["username"] = f"El usuario debe tener al menos {USERNAME_MIN_LENGTH} caracteres."
        elif len(username) > USERNAME_MAX_LENGTH:
            errors["username"] = f"El usuario no puede superar los {USERNAME_MAX_LENGTH} caracteres."
        elif not USERNAME_PATTERN.fullmatch(username):
            errors["username"] = "El usuario solo puede contener letras, números, puntos, guiones y guiones bajos."

    if not isinstance(password, str) or not password:
        errors["password"] = "Ingresa una contraseña."
    elif len(password) < PASSWORD_MIN_LENGTH:
        errors["password"] = f"La contraseña debe tener al menos {PASSWORD_MIN_LENGTH} caracteres."
    elif len(password) > PASSWORD_MAX_LENGTH:
        errors["password"] = f"La contraseña no puede superar los {PASSWORD_MAX_LENGTH} caracteres."

    if errors:
        raise AuthValidationError(errors)
    return {"username": username.casefold(), "password": password}
