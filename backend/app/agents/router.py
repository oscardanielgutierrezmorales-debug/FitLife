from __future__ import annotations

from app.guardrails.domain_classifier import classify_domain


def route(message: str) -> str:
    """The explicit router is intentionally separate from guardrail policy."""
    return classify_domain(message)

