import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    ("payload", "field", "message"),
    [
        ({"username": "", "password": "strong-password-123"}, "username", "Ingresa un nombre de usuario."),
        ({"username": "ab", "password": "strong-password-123"}, "username", "al menos 3 caracteres"),
        ({"username": "a" * 81, "password": "strong-password-123"}, "username", "80 caracteres"),
        ({"username": "hola mundo", "password": "strong-password-123"}, "username", "solo puede contener"),
        ({"username": "valid.user", "password": ""}, "password", "Ingresa una contraseña."),
        ({"username": "valid.user", "password": "short"}, "password", "al menos 12 caracteres"),
        ({"username": "valid.user", "password": "x" * 129}, "password", "128 caracteres"),
    ],
)
def test_signup_returns_structured_field_errors(payload, field, message):
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/signup", json=payload)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "AUTH_VALIDATION_ERROR"
        assert detail["field"] == field
        assert message in detail["field_errors"][field]


def test_signup_accepts_valid_credentials_and_reports_duplicate_username():
    username = f"valid.auth-{uuid.uuid4().hex[:10]}"
    payload = {"username": username, "password": "strong-password-123"}
    with TestClient(app) as client:
        created = client.post("/api/v1/auth/signup", json=payload)
        assert created.status_code == 201, created.text
        duplicate = client.post("/api/v1/auth/signup", json=payload)
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == {
            "code": "USERNAME_TAKEN",
            "field": "username",
            "message": "Este nombre de usuario ya está registrado.",
            "field_errors": {"username": "Este nombre de usuario ya está registrado."},
        }


def test_login_distinguishes_validation_from_bad_credentials():
    with TestClient(app) as client:
        invalid = client.post("/api/v1/auth/login", json={"username": "ab", "password": "short"})
        assert invalid.status_code == 422
        assert set(invalid.json()["detail"]["field_errors"]) == {"username", "password"}
        unauthorized = client.post("/api/v1/auth/login", json={"username": "missing.user", "password": "strong-password-123"})
        assert unauthorized.status_code == 401
        assert unauthorized.json()["detail"] == "Usuario o contraseña incorrectos."
