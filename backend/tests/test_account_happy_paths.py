"""Account contracts: happy paths."""

import pytest
from app.api.v1.endpoints.auth import COOKIE_NAME
from app.core.security import PASSWORD_HASHER, verify_password
from app.schemas.user import AccountPatch, Registration
from bson import ObjectId

from tests.account_support import (
    ME,
    NEW_PASSWORD,
    USERS,
    cleared_cookie,
    create_account,
    mutate,
    public_response,
    snapshot,
)
from tests.auth_support import PASSWORD, call


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


@pytest.mark.parametrize(
    "fields",
    [
        {"name": " Trimmed Alias "},
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
        # The old password must also fail through the public login endpoint,
        # not only when checked directly against the replacement hash.
        assert (
            http.post(
                "/api/v1/auth/login",
                json={
                    "email": result["email"],
                    "password": PASSWORD,
                },
            ).status_code
            == 401
        )
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


def test_display_names_need_not_be_unique(api, account):
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


@pytest.mark.parametrize(
    "password",
    [
        "a" * 13 + "!1",
        "é" * 126 + "!1",
        "unicode punctuation。1",
    ],
)
def test_registration_accepts_password_boundaries_and_unicode_punctuation(password):
    payload = Registration(email=" ALICE@EXAMPLE.COM ", password=password)
    assert str(payload.email) == "alice@example.com"
    assert payload.password.get_secret_value() == password
    assert password not in repr(payload)


@pytest.mark.parametrize("name", ["x", "x" * 128], ids=["minimum", "maximum"])
def test_patch_accepts_name_length_boundaries(name):
    payload = AccountPatch(name=name, current_password=PASSWORD)
    assert payload.name == name
