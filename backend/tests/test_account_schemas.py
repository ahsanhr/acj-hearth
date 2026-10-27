"""Fast, database-free validation and public serializer contract tests."""

import pytest
from app.api.v1.endpoints.auth import public_user
from app.schemas.user import Registration, UserPublic
from bson import ObjectId
from pydantic import ValidationError

from tests.account_support import PUBLIC_FIELDS


@pytest.mark.parametrize("verified", [False, True])
def test_shared_public_serializer_exposes_only_canonical_fields_and_real_state(
    verified,
):
    uid = ObjectId()
    result = public_user(
        {
            "_id": uid,
            "name": "Alice",
            "email": "alice@example.com",
            "email_verified": verified,
            "password_hash": "never expose",
            "disabled": False,
            "auth_serial": 7,
            "auth_version": 2,
        }
    )
    assert result.model_dump() == {
        "id": str(uid),
        "name": "Alice",
        "email": "alice@example.com",
        "email_verified": verified,
    }


def test_schemas_expose_only_agreed_fields():
    assert set(UserPublic.model_fields) == PUBLIC_FIELDS
    assert set(Registration.model_fields) == {"email", "password"}


@pytest.mark.parametrize(
    "password",
    [
        "a" * 13 + "!1",
        "a" * 126 + "!1",
        "unicode symbol snowman☃1",
        "unicode punctuation。1",
        "é" * 13 + "!1",
        "  spaced password!1  ",
    ],
)
def test_registration_preserves_password_and_normalizes_email(password):
    payload = Registration(email=" ALICE@EXAMPLE.COM ", password=password)
    assert str(payload.email) == "alice@example.com"
    assert payload.password.get_secret_value() == password
    assert password not in repr(payload)


@pytest.mark.parametrize(
    "password",
    [
        "a" * 12 + "!1",
        "a" * 127 + "!1",
        "nonascii digit only!١",
    ],
)
def test_registration_password_policy_rejects_invalid_values_without_echo(password):
    with pytest.raises(ValidationError) as error:
        Registration(email="alice@example.com", password=password)
    assert password not in str(error.value)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"email": "alice@example.com"},
        {"password": "a long password!1"},
        {"email": None, "password": "a long password!1"},
        {"email": "alice@example.com", "password": None},
        {"email": "alice@example.com", "password": []},
        {"email": 123, "password": "a long password!1"},
        {
            "email": "alice@example.com",
            "password": "a long password!1",
            "unknown": True,
        },
    ],
)
def test_registration_rejects_missing_null_wrong_type_and_extra_fields(fields):
    with pytest.raises(ValidationError):
        Registration.model_validate(fields)
