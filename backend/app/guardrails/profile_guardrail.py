"""Security checks for profile data, kept separate from health-data validation."""

from __future__ import annotations

import re

from .rules import INJECTION_TERMS, contains_any


class ProfileSecurityError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(message)


def assert_safe_profile_text(field: str, value: str) -> str:
    """Reject control characters, oversized values and instruction-like content.

    Profile fields are deliberately limited to enums and short restriction labels,
    but this guardrail remains an independent boundary if a client calls the API
    directly instead of using the form.
    """
    if not isinstance(value, str):
        raise ProfileSecurityError(field, "El valor debe ser texto.")
    normalized = value.strip()
    if not normalized or len(normalized) > 60 or re.search(r"[\x00-\x1f\x7f]", normalized):
        raise ProfileSecurityError(field, "El formato del dato no es válido.")
    if contains_any(normalized, INJECTION_TERMS):
        raise ProfileSecurityError(field, "El dato contiene contenido no permitido.")
    return normalized
