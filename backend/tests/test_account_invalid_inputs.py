"""Invalid inputs: one representative per distinct validation rule."""

import pytest
from app.schemas.message import MessageUpdate
from app.schemas.user import AccountPatch, Registration
from pydantic import ValidationError

from tests.account_support import ME, USERS, VALIDATION_ERROR, mutate, snapshot
from tests.auth_support import PASSWORD, call


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "invalid", "password": PASSWORD},
        {"email": "alice@example.com", "password": "short!1"},
        {
            "email": "alice@example.com",
            "password": PASSWORD,
            "password_hash": "forbidden",
        },
    ],
    ids=["invalid-email", "invalid-password", "protected-field"],
)
def test_creation_rejects_invalid_fields_without_writes(api, payload):
    http, db = api
    before = snapshot(http, db)
    response = http.post(USERS, json=payload)
    assert response.status_code == 422, response.text
    assert response.json() == VALIDATION_ERROR
    assert response.headers.get("cache-control") == "no-store"
    assert PASSWORD not in response.text
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", USERS, "{not-json"),
        ("PATCH", ME, "[]"),
        ("DELETE", ME, "null"),
    ],
    ids=["malformed-json", "nonobject-body", "null-body"],
)
def test_account_routes_reject_invalid_json_bodies(api, account, method, path, body):
    http, db = api
    before = snapshot(http, db)
    response = http.request(
        method,
        path,
        content=body,
        headers={
            **account["headers"],
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json() == VALIDATION_ERROR
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"name": None},
        {"email": None},
        {"new_password": None},
        {"name": "  \t "},
        {"email": "bad"},
        {"new_password": "short!1"},
        {"name": "valid", "password_hash": "forbidden"},
    ],
    ids=[
        "no-mutable-field",
        "null-name",
        "null-email",
        "null-password",
        "blank-name",
        "invalid-email",
        "invalid-password",
        "protected-field",
    ],
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
    "payload",
    [
        {},
        {"current_password": None},
        {"current_password": PASSWORD, "unknown": True},
    ],
    ids=["missing-password", "null-password", "unknown-field"],
)
def test_delete_rejects_invalid_confirmation_body_without_cleanup(
    api, account_graph, payload
):
    http, db = api
    account, _, _ = account_graph
    before = snapshot(http, db)
    response = mutate(http, method="DELETE", payload=payload, account=account)
    assert response.status_code == 422, response.text
    assert response.json() == VALIDATION_ERROR
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "password",
    [
        "a" * 12 + "!1",
        "a" * 127 + "!1",
        "nonascii digit only!١",
    ],
    ids=["below-minimum", "above-maximum", "nonascii-digit"],
)
def test_password_policy_rejects_boundaries_and_nonascii_digits_without_echo(password):
    with pytest.raises(ValidationError) as error:
        Registration(email="alice@example.com", password=password)
    assert password not in str(error.value)


@pytest.mark.parametrize(
    "fields",
    [
        {"email": "alice@example.com"},
        {"password": PASSWORD},
        {"email": None, "password": PASSWORD},
        {"email": "alice@example.com", "password": None},
        {"email": "alice@example.com", "password": []},
        {"email": 123, "password": PASSWORD},
    ],
    ids=[
        "missing-password",
        "missing-email",
        "null-email",
        "null-password",
        "wrong-password-type",
        "wrong-email-type",
    ],
)
def test_registration_requires_typed_nonnull_credentials(fields):
    with pytest.raises(ValidationError):
        Registration.model_validate(fields)


@pytest.mark.parametrize("name", ["x" * 129, 7], ids=["above-maximum", "wrong-type"])
def test_patch_name_schema_rejects_invalid_length_or_type(name):
    with pytest.raises(ValidationError):
        AccountPatch(name=name, current_password=PASSWORD)


def test_message_edit_rejects_client_supplied_deleted_state():
    with pytest.raises(ValidationError):
        MessageUpdate.model_validate({"message": "restore", "deleted": False})


def test_board_counter_cannot_be_client_supplied(api, account):
    http, db = api
    response = http.post(
        "/api/v1/boards/",
        headers=account["headers"],
        json={
            "boardName": "protected",
            "createdBy": str(account["user"]["_id"]),
            "members": [],
            "mutation_serial": 900,
        },
    )
    assert response.status_code == 422, response.text
    assert call(http, db.boards.count_documents, {}) == 0


def test_malformed_relationship_id_is_rejected_without_creating_data(api, account):
    http, db = api
    response = http.post(
        "/api/v1/boards/",
        headers=account["headers"],
        json={
            "boardName": "invalid reference",
            "createdBy": str(account["user"]["_id"]),
            "members": ["not-an-objectid"],
        },
    )
    assert response.status_code == 422, response.text
    assert call(http, db.boards.count_documents, {}) == 0
