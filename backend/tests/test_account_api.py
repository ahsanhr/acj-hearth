"""Account API acceptance tests; field permutations belong in schema tests."""

import pytest
from app.api.v1.endpoints.auth import COOKIE_NAME
from app.core.security import PASSWORD_HASHER, verify_password
from bson import ObjectId

from tests.account_support import (
    ME,
    NEW_PASSWORD,
    USERS,
    VALIDATION_ERROR,
    cleared_cookie,
    create_account,
    mutate,
    public_response,
    snapshot,
)
from tests.test_auth_api import PASSWORD, call


def test_public_creation_is_canonical_and_does_not_login(api):
    http, db = api
    password = "  Unicode café 🏠 1  "
    response = http.post(
        USERS, json={"email": " ALICE@Example.COM ", "password": password}
    )
    data = public_response(response, 201)
    assert data == {
        "id": data["id"],
        "name": "alice",
        "email": "alice@example.com",
        "email_verified": False,
    }
    user = call(http, db.users.find_one, {"_id": ObjectId(data["id"])})
    assert user["name"] == "alice" and user["email"] == data["email"]
    assert user["disabled"] is user["email_verified"] is False
    assert type(user["auth_version"]) is type(user["auth_serial"]) is int
    assert user["auth_version"] == user["auth_serial"] == 0
    assert verify_password(password, user["password_hash"])
    assert not verify_password(password.strip(), user["password_hash"])
    assert user["password_hash"].startswith("$argon2id$")
    assert not PASSWORD_HASHER.check_needs_rehash(user["password_hash"])
    assert not {"firstName", "lastName", "userID", "username", "password"} & user.keys()
    assert call(http, db.sessions.count_documents, {}) == 0
    assert COOKIE_NAME not in response.headers.get("set-cookie", "")
    assert http.get(ME).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "invalid", "password": PASSWORD},
        {"email": "alice@example.com", "password": "short!1"},
        {
            "email": "alice@example.com",
            "password": PASSWORD,
            "password_hash": "forbidden",
        },
    ],
)
def test_invalid_creation_has_safe_validation_envelope_and_no_writes(api, payload):
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
        ("PATCH", ME, "{not-json"),
        ("DELETE", ME, "{not-json"),
        ("PATCH", ME, "[]"),
        ("POST", USERS, "null"),
        ("DELETE", ME, '"string"'),
    ],
)
def test_malformed_or_nonobject_json_is_safe(api, account, method, path, body):
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


def test_get_returns_real_verification_state_without_mutating(api, account):
    http, db = api
    call(
        http,
        db.users.update_one,
        {"_id": account["user"]["_id"]},
        {"$set": {"email_verified": True}},
    )
    before = snapshot(http, db)
    assert public_response(http.get(ME, headers=account["headers"])) == {
        **account["public"],
        "email_verified": True,
    }
    assert snapshot(http, db) == before


# Token syntax/signature/expiry permutations are covered by test_auth_api.py
# and test_security.py. Here verify every account route enforces live identity.
@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("state", ["missing", "revoked", "disabled", "deleted"])
def test_private_operations_require_active_identity(api, account, method, state):
    http, db = api
    uid = account["user"]["_id"]
    headers = account["headers"] if state != "missing" else {}
    if state == "revoked":
        call(http, db.sessions.delete_many, {"user_id": uid})
    elif state == "disabled":
        call(http, db.users.update_one, {"_id": uid}, {"$set": {"disabled": True}})
    elif state == "deleted":
        call(http, db.users.delete_one, {"_id": uid})
    before = snapshot(http, db)
    payload = {
        "current_password": PASSWORD,
        **({"name": "Not allowed"} if method == "PATCH" else {}),
    }
    response = http.request(
        method, ME, headers=headers, **({"json": payload} if method != "GET" else {})
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers.get("cache-control") == "no-store"
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "fields",
    [{"name": "New"}, {"email": "new@example.com"}, {"new_password": NEW_PASSWORD}],
)
@pytest.mark.parametrize("confirmation", [None, "wrong"])
def test_every_patch_requires_password_confirmation(api, account, fields, confirmation):
    http, db = api
    before = snapshot(http, db)
    payload = dict(fields)
    if confirmation is not None:
        payload["current_password"] = confirmation
    response = mutate(http, payload=payload, account=account)
    assert response.status_code == (422 if confirmation is None else 400), response.text
    assert response.json()["error"]["code"] == (
        "validation_error" if confirmation is None else "incorrect_password"
    )
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"name": None},
        {"email": None},
        {"new_password": None},
        {"name": "  \t "},
        {"name": "a" * 129},
        {"name": 7},
        {"email": "bad"},
        {"new_password": "short!1"},
        {"name": "valid", "password_hash": "forbidden"},
        {"name": "valid", "auth_version": 1},
        {"name": "valid", "unknown": True},
    ],
)
def test_invalid_patch_rejects_entire_request(api, account, fields):
    http, db = api
    before = snapshot(http, db)
    response = mutate(
        http, payload={"current_password": PASSWORD, **fields}, account=account
    )
    assert response.status_code == 422, response.text
    assert response.json() == VALIDATION_ERROR
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "fields",
    [
        {"name": " Trimmed Alias "},
        {"name": "x"},
        {"name": "x" * 128},
        {"email": " NEW@Example.com "},
        {"new_password": NEW_PASSWORD},
        {"name": "Combined", "email": "new@example.com", "new_password": NEW_PASSWORD},
        {"email": " ALICE@EXAMPLE.COM "},
    ],
)
def test_partial_updates_preserve_fields_and_revoke_only_when_required(
    api, account, fields
):
    http, db = api
    uid = account["user"]["_id"]
    call(http, db.users.update_one, {"_id": uid}, {"$set": {"email_verified": True}})
    login = http.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    second_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    before = call(http, db.users.find_one, {"_id": uid})
    response = mutate(
        http, payload={"current_password": PASSWORD, **fields}, account=account
    )
    result = public_response(response)
    after = call(http, db.users.find_one, {"_id": uid})
    email_changed = (
        "email" in fields and fields["email"].strip().casefold() != before["email"]
    )
    revokes = email_changed or "new_password" in fields
    assert after["_id"] == uid and result["id"] == str(uid)
    assert result["name"] == fields.get("name", before["name"]).strip()
    assert result["email"] == fields.get("email", before["email"]).strip().casefold()
    assert result["email_verified"] is (not email_changed)
    assert after["disabled"] is False
    if "new_password" in fields:
        assert verify_password(fields["new_password"], after["password_hash"])
        assert not verify_password(PASSWORD, after["password_hash"])
        assert not PASSWORD_HASHER.check_needs_rehash(after["password_hash"])
    else:
        assert after["password_hash"] == before["password_hash"]
    for headers in [account["headers"], second_headers]:
        assert http.get(ME, headers=headers).status_code == (401 if revokes else 200)
    assert call(http, db.sessions.count_documents, {"user_id": uid}) == (
        0 if revokes else 2
    )
    if revokes:
        cleared_cookie(response)
        assert after["auth_version"] > before["auth_version"]
        assert (
            http.post(
                "/api/v1/auth/refresh",
                headers={"Cookie": f"{COOKIE_NAME}={account['refresh']}"},
            ).status_code
            == 401
        )
    else:
        assert "set-cookie" not in response.headers
    assert (
        http.post(
            "/api/v1/auth/login",
            json={
                "email": f" {result['email'].upper()} ",
                "password": fields.get("new_password", PASSWORD),
            },
        ).status_code
        == 200
    )


def test_names_are_nonunique_and_email_change_does_not_rename(api, account):
    http, db = api
    other = create_account(http, db, "bob@example.com")
    for identity in [account, other]:
        public_response(
            mutate(
                http,
                payload={"name": "Same alias", "current_password": PASSWORD},
                account=identity,
            )
        )
    response = mutate(
        http,
        payload={"email": "elsewhere@example.com", "current_password": PASSWORD},
        account=account,
    )
    assert public_response(response)["name"] == "Same alias"


def test_duplicate_email_creation_and_combined_patch_are_atomic(api, account):
    http, db = api
    create_account(http, db, "bob@example.com")
    before = snapshot(http, db)
    responses = [
        http.post(USERS, json={"email": " ALICE@EXAMPLE.COM ", "password": PASSWORD}),
        mutate(
            http,
            payload={
                "email": " BOB@EXAMPLE.COM ",
                "name": "Must not persist",
                "new_password": NEW_PASSWORD,
                "current_password": PASSWORD,
            },
            account=account,
        ),
    ]
    for response in responses:
        assert response.status_code == 409, response.text
        assert response.json()["error"] == {
            "code": "email_exists",
            "message": "An account with this email already exists.",
        }
    assert snapshot(http, db) == before


@pytest.mark.parametrize("field", ["id", "_id"])
def test_client_cannot_select_another_account(api, account, field):
    http, db = api
    other = create_account(http, db, "bob@example.com")
    before = snapshot(http, db)
    for method in ["PATCH", "DELETE"]:
        response = mutate(
            http,
            method=method,
            payload={
                field: str(other["user"]["_id"]),
                "current_password": PASSWORD,
                **({"name": "attack"} if method == "PATCH" else {}),
            },
            account=account,
        )
        assert response.status_code == 422, response.text
    for method in ["GET", "PATCH", "DELETE"]:
        assert http.request(
            method, f"{USERS}/{other['user']['_id']}", headers=account["headers"]
        ).status_code in (404, 405)
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "payload,status",
    [
        ({}, 422),
        ({"current_password": None}, 422),
        ({"current_password": PASSWORD, "unknown": True}, 422),
        ({"current_password": "wrong"}, 400),
    ],
)
def test_delete_confirmation_failure_preserves_everything(
    api, account_graph, payload, status
):
    http, db = api
    account, _, _ = account_graph
    before = snapshot(http, db)
    response = mutate(http, method="DELETE", payload=payload, account=account)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == (
        "validation_error" if status == 422 else "incorrect_password"
    )
    assert snapshot(http, db) == before


def test_responses_and_logs_never_expose_secrets(api, account, caplog):
    http, _ = api
    caplog.set_level("DEBUG")
    secrets = [
        PASSWORD,
        NEW_PASSWORD,
        account["user"]["password_hash"],
        account["refresh"],
        account["headers"]["Authorization"].split()[1],
    ]
    responses = [
        http.get(ME, headers=account["headers"]),
        mutate(
            http,
            payload={"name": "Safe", "current_password": PASSWORD},
            account=account,
        ),
        mutate(
            http, payload={"name": "Safe", "current_password": "wrong"}, account=account
        ),
        mutate(
            http,
            payload={
                "name": None,
                "new_password": NEW_PASSWORD,
                "current_password": PASSWORD,
            },
            account=account,
        ),
    ]
    for response in responses:
        assert response.headers.get("cache-control") == "no-store"
        for secret in secrets:
            assert secret not in response.text
    for secret in secrets:
        assert secret not in caplog.text


def test_retired_routes_are_not_registered(api):
    http, db = api
    before = snapshot(http, db)
    for path in ["/api/v1/auth/register", "/api/v1/auth/password"]:
        response = http.post(
            path,
            json={
                "email": "alice@example.com",
                "password": PASSWORD,
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        )
        assert response.status_code in (404, 405), response.text
        assert path not in http.get("/openapi.json").json()["paths"]
    assert snapshot(http, db) == before


@pytest.mark.parametrize(
    "origin,allowed",
    [("https://app.example.com", True), ("https://evil.example", False)],
)
def test_patch_cors_preflight_preserves_origin_and_credentials_policy(
    api, origin, allowed
):
    http, _ = api
    response = http.options(
        ME,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == (200 if allowed else 400)
    if allowed:
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
        assert "PATCH" in response.headers["access-control-allow-methods"]
    else:
        assert "access-control-allow-origin" not in response.headers
