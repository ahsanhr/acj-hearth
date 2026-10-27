"""Authentication/session contracts: data integrity."""

from datetime import timedelta

from app.api.v1.endpoints.auth import COOKIE_NAME
from app.core.security import (
    decode_access_token,
    hash_password,
    issue_access_token,
    utcnow,
    verify_password,
)

from tests.auth_support import PASSWORD, authorize, call, login, register, token_session


def test_refresh_rotation_and_logout_without_access_token(api):
    http, db = api
    register(http)
    other_session_token = authorize(http, login(http))
    first_token = authorize(http, login(http))
    old_cookie = http.cookies.get(COOKIE_NAME)
    first_claims = decode_access_token(first_token, http.app.state.settings)
    record = call(http, db.sessions.find_one, {"session_id": first_claims["sid"]})
    response = http.post("/api/v1/auth/refresh")
    second_token = authorize(http, response)
    second_claims = decode_access_token(second_token, http.app.state.settings)
    new_cookie = http.cookies.get(COOKIE_NAME)
    assert first_claims["sid"] == second_claims["sid"]
    assert first_claims["jti"] != second_claims["jti"]
    assert old_cookie != new_cookie
    updated = call(http, db.sessions.find_one, {"session_id": first_claims["sid"]})
    assert record["expires_at"] == updated["expires_at"]
    replay = http.post(
        "/api/v1/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={old_cookie}"}
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "reauthentication_required"
    assert http.get("/api/v1/users/me").status_code == 200  # replay does not revoke
    http.headers.pop("Authorization")
    assert http.post("/api/v1/auth/logout").status_code == 204
    assert http.cookies.get(COOKIE_NAME) is None
    assert http.post("/api/v1/auth/logout").status_code == 204
    assert http.post("/api/v1/auth/refresh").status_code == 401
    http.headers["Authorization"] = f"Bearer {second_token}"
    assert http.get("/api/v1/users/me").status_code == 401
    http.headers["Authorization"] = f"Bearer {other_session_token}"
    assert http.get("/api/v1/users/me").status_code == 200
    assert call(http, db.sessions.count_documents, {}) == 1


def test_owned_sessions_eviction_and_clear(api):
    http, db = api
    register(http)
    first_token = authorize(http, login(http))
    first_cookie = http.cookies.get(COOKIE_NAME)
    for _ in range(5):
        latest_token = authorize(http, login(http))
    assert call(http, db.sessions.count_documents, {}) == 5
    http.headers["Authorization"] = f"Bearer {first_token}"
    assert http.get("/api/v1/auth/sessions").status_code == 401
    assert (
        http.post(
            "/api/v1/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={first_cookie}"}
        ).status_code
        == 401
    )
    # Restore the still-valid current token; another login would only repeat
    # creation/eviction already exercised by the six logins above.
    http.headers["Authorization"] = f"Bearer {latest_token}"
    register(http, "other@example.com")
    other_session, _ = call(
        http, http.app.state.auth_service.login, "other@example.com", PASSWORD
    )
    other_sid = other_session["session_id"]
    assert http.delete(f"/api/v1/auth/sessions/{other_sid}").status_code == 404
    sessions = http.get("/api/v1/auth/sessions").json()
    target = next(s["session_id"] for s in sessions if not s["current"])
    assert http.delete(f"/api/v1/auth/sessions/{target}").status_code == 204
    assert http.get("/api/v1/users/me").status_code == 200
    assert http.delete("/api/v1/auth/sessions").status_code == 204
    assert http.cookies.get(COOKIE_NAME) is None
    assert http.get("/api/v1/users/me").status_code == 401
    assert call(http, db.sessions.count_documents, {}) == 1


def test_password_hash():
    raw = "a long password!1"
    hashed = hash_password(raw)
    assert hashed.startswith("$argon2id$")
    assert verify_password(raw, hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password(raw, "malformed")


def test_jwt_uniqueness_and_session_cap(auth_settings):
    record = token_session()
    record["expires_at"] = utcnow() + timedelta(seconds=60)
    first = issue_access_token(record, auth_settings)
    second = issue_access_token(record, auth_settings)
    claims = decode_access_token(first, auth_settings)
    assert first != second
    assert claims["sid"] == record["session_id"]
    assert claims["sub"] == str(record["user_id"])
    assert claims["exp"] <= int(record["expires_at"].timestamp())
    assert claims["jti"] != decode_access_token(second, auth_settings)["jti"]
