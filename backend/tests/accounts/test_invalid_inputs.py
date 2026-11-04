"""Unhappy paths: representative invalid classes, not every input permutation."""

import pytest
from app.schemas.message import MessageUpdate
from app.schemas.user import AccountPatch, Registration
from pydantic import ValidationError

from tests.support.accounts import ME, USERS, VALIDATION_ERROR, mutate, snapshot
from tests.support.auth import PASSWORD, call

pytestmark = pytest.mark.unhappy_path


@pytest.mark.parametrize(
    "method,path,payload",
    [
        (
            "POST",
            USERS,
            {
                "email": "alice@example.com",
                "password": PASSWORD,
                "password_hash": "forbidden",
            },
        ),
        ("PATCH", ME, {"current_password": PASSWORD, "name": None}),
        ("DELETE", ME, {}),
    ],
    ids=["unknown-field", "explicit-null", "missing-required-field"],
)
def test_account_routes_reject_invalid_fields_without_writes(
    api, account, method, path, payload
):
    http, db = api
    before = snapshot(http, db)
    response = http.request(method, path, json=payload, headers=account["headers"])
    assert response.status_code == 422, response.text
    assert response.json() == VALIDATION_ERROR
    assert response.headers.get("cache-control") == "no-store"
    assert PASSWORD not in response.text
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "method,path,body",
    [("POST", USERS, "{not-json"), ("PATCH", ME, "[]"), ("DELETE", ME, "null")],
    ids=["malformed-json", "nonobject-body", "null-body"],
)
def test_account_routes_reject_invalid_json_bodies(api, account, method, path, body):
    http, db = api
    before = snapshot(http, db)
    response = http.request(
        method,
        path,
        content=body,
        headers={**account["headers"], "Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert response.json() == VALIDATION_ERROR
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "fields",
    [{}, {"name": "  \t "}, {"new_password": "short!1"}],
    ids=["no-mutable-field", "blank-name", "invalid-password"],
)
def test_patch_rejects_invalid_fields_atomically(api, account, fields):
    http, db = api
    before = snapshot(http, db)
    response = mutate(
        http, payload={"current_password": PASSWORD, **fields}, account=account
    )
    assert response.status_code == 422, response.text
    assert response.json() == VALIDATION_ERROR
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "password",
    [
        "a" * 12 + "!1",
        "a" * 127 + "!1",
        "nonascii digit only!١",
        "long password ! abc",
        "long password 1   ",
    ],
    ids=[
        "below-minimum",
        "above-maximum",
        "nonascii-digit",
        "missing-ascii-digit",
        "missing-punctuation-or-symbol",
    ],
)
def test_password_policy_rejects_invalid_classes_without_echo(password):
    with pytest.raises(ValidationError) as error:
        Registration(email="alice@example.com", password=password)
    assert password not in str(error.value)


@pytest.mark.parametrize(
    "fields",
    [
        {"email": "alice@example.com"},
        {"password": PASSWORD},
        {"email": "invalid", "password": PASSWORD},
        {"email": "alice@example.com", "password": []},
        {"email": 123, "password": PASSWORD},
    ],
    ids=[
        "missing-password",
        "missing-email",
        "invalid-email",
        "wrong-password-type",
        "wrong-email-type",
    ],
)
def test_registration_rejects_missing_malformed_or_wrong_type_credentials(fields):
    with pytest.raises(ValidationError):
        Registration.model_validate(fields)


@pytest.mark.parametrize("name", ["x" * 129, 7], ids=["above-maximum", "wrong-type"])
def test_patch_name_schema_rejects_invalid_length_or_type(name):
    with pytest.raises(ValidationError):
        AccountPatch(name=name, current_password=PASSWORD)


def test_message_edit_rejects_client_supplied_deleted_state():
    with pytest.raises(ValidationError):
        MessageUpdate.model_validate({"message": "restore", "deleted": False})


@pytest.mark.parametrize(
    "fields",
    [{"mutation_serial": 900}, {"members": ["not-an-objectid"]}],
    ids=["server-managed-counter", "malformed-relationship-id"],
)
def test_board_rejects_invalid_fields_without_creating_data(api, account, fields):
    http, db = api
    before = snapshot(http, db)
    response = http.post(
        "/api/v1/boards/",
        headers=account["headers"],
        json={
            "boardName": "invalid",
            "createdBy": str(account["user"]["_id"]),
            "members": [],
            **fields,
        },
    )
    assert response.status_code == 422, response.text
    assert call(http, db.boards.count_documents, {}) == 0
    assert snapshot(http, db) == before
