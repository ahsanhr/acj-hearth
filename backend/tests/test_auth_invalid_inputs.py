"""Authentication/session contracts: invalid inputs."""

import pytest
from app.schemas.user import Registration
from pydantic import ValidationError

from tests.auth_support import PASSWORD, call, login, register


def test_login_errors_and_validation_do_not_echo_password(api):
    http, db = api
    assert register(http).status_code == 201
    wrong = login(http, password="wrong")
    missing = login(http, email="absent@example.com")
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    assert wrong.json()["error"]["code"] == "invalid_credentials"
    assert "wrong" not in wrong.text
    assert call(http, db.sessions.count_documents, {}) == 0
    result = http.post(
        "/api/v1/auth/login", json={"username": "user", "password": PASSWORD}
    )
    assert result.status_code == 422
    assert PASSWORD not in result.text


@pytest.mark.parametrize(
    "password",
    ["long password ! abc", "long password 1   "],
    ids=["missing-ascii-digit", "missing-punctuation-or-symbol"],
)
def test_password_policy_rejections(password):
    with pytest.raises(ValidationError):
        Registration(email="user@example.com", password=password)


def test_missing_signing_secret_fails_startup_configuration(auth_settings):
    auth_settings.AUTH_SIGNING_SECRET = None
    with pytest.raises(ValueError):
        auth_settings.validate_auth()
