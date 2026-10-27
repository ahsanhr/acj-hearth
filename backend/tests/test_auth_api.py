import asyncio
from datetime import timedelta
from functools import partial

from bson import ObjectId
import jwt

from app.api.v1.endpoints.auth import COOKIE_NAME, COOKIE_PATH
from app.core.security import decode_access_token, issue_access_token, refresh_hash, utcnow
from app.services.auth import AuthError

PASSWORD = "a long password!1"
EMAIL = "user@example.com"


def call(http, fn, *args, **kwargs):
    return http.portal.call(partial(fn, *args, **kwargs))


def register(http, email=EMAIL):
    return http.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})


def login(http, email=EMAIL, password=PASSWORD):
    return http.post("/api/v1/auth/login", json={"email": email, "password": password})


def authorize(http, result):
    assert result.status_code == 200, result.text
    token = result.json()["access_token"]
    http.headers["Authorization"] = f"Bearer {token}"
    return token


def test_registration_login_and_cookie(api):
    http, db = api
    response = register(http, " USER@Example.com ")
    assert response.status_code == 201
    assert response.json()["email"] == EMAIL
    assert response.json()["email_verified"] is False
    duplicate = register(http)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == "An account with this email already exists."
    token = authorize(http, login(http, "USER@example.com"))
    cookie = http.cookies.get(COOKIE_NAME)
    response = login(http)
    cookie_header = response.headers["set-cookie"]
    for attribute in ["HttpOnly", "Secure", "SameSite=lax", f"Path={COOKIE_PATH}", "expires="]:
        assert attribute in cookie_header
    assert response.headers["cache-control"] == "no-store"
    assert cookie not in response.text
    claims = decode_access_token(token, http.app.state.settings)
    user = call(http, db.users.find_one, {"email": EMAIL})
    record = call(http, db.sessions.find_one, {"session_id": claims["sid"]})
    assert record["user_id"] == user["_id"] == ObjectId(claims["sub"])
    assert user["password_hash"].startswith("$argon2id$")
    assert record["refresh_token_hash"] == refresh_hash(cookie)
    assert record["expires_at"] - record["created_at"] == timedelta(days=30)
    listing = http.get("/api/v1/auth/sessions")
    assert listing.status_code == 200
    assert "refresh_token_hash" not in listing.text
    assert cookie not in listing.text
    assert http.get("/api/v1/users/me").status_code == 200
    assert http.get("/api/v1/boards/").status_code == 200


def test_login_errors_and_validation_do_not_echo_password(api):
    http, _ = api
    register(http)
    wrong = login(http, password="wrong")
    missing = login(http, email="absent@example.com")
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    result = http.post("/api/v1/auth/register", json={"email": "bad", "password": "secret"})
    assert result.status_code == 422
    assert "secret" not in result.text
    result = http.post("/api/v1/auth/login", json={"username": "user", "password": PASSWORD})
    assert result.status_code == 422
    assert PASSWORD not in result.text


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
    replay = http.post("/api/v1/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={old_cookie}"})
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


def test_refresh_when_access_expired_and_session_boundary(api):
    http, db = api
    register(http)
    token = authorize(http, login(http))
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.update(iat=int((utcnow() - timedelta(minutes=20)).timestamp()),
                  exp=int((utcnow() - timedelta(minutes=5)).timestamp()))
    expired = jwt.encode(claims, "a" * 48, algorithm="HS256", headers={"kid": "current"})
    http.headers["Authorization"] = f"Bearer {expired}"
    assert http.get("/api/v1/users/me").status_code == 401
    assert http.post("/api/v1/auth/refresh").status_code == 200
    call(http, db.sessions.update_one, {"session_id": claims["sid"]},
         {"$set": {"expires_at": utcnow()}})
    assert http.post("/api/v1/auth/refresh").status_code == 401
    http.headers["Authorization"] = f"Bearer {token}"
    assert http.get("/api/v1/users/me").status_code == 401


def test_owned_sessions_eviction_and_clear(api):
    http, db = api
    register(http)
    first_token = authorize(http, login(http))
    first_cookie = http.cookies.get(COOKIE_NAME)
    for _ in range(5):
        authorize(http, login(http))
    assert call(http, db.sessions.count_documents, {}) == 5
    http.headers["Authorization"] = f"Bearer {first_token}"
    assert http.get("/api/v1/auth/sessions").status_code == 401
    assert http.post("/api/v1/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={first_cookie}"}).status_code == 401
    authorize(http, login(http))
    register(http, "other@example.com")
    other_session, _ = call(http, http.app.state.auth_service.login, "other@example.com", PASSWORD)
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


def test_concurrent_logins_and_refresh(api):
    http, db = api
    register(http)
    service = http.app.state.auth_service

    async def simultaneous_logins():
        return await asyncio.gather(*(service.login(EMAIL, PASSWORD) for _ in range(8)))

    results = call(http, simultaneous_logins)
    assert len({r[0]["session_id"] for r in results}) == 8
    assert call(http, db.sessions.count_documents, {}) == 5
    _, raw = call(http, service.login, EMAIL, PASSWORD)

    async def simultaneous_refreshes():
        return await asyncio.gather(service.refresh(raw), service.refresh(raw), return_exceptions=True)

    results = call(http, simultaneous_refreshes)
    assert sum(isinstance(r, tuple) for r in results) == 1
    assert sum(isinstance(r, AuthError) and r.status == 401 for r in results) == 1


def test_password_change_and_account_revocation(api):
    http, db = api
    register(http)
    authorize(http, login(http))
    authorize(http, login(http))
    wrong = http.post("/api/v1/auth/password", json={"current_password": "wrong", "new_password": "another password!2"})
    assert wrong.status_code == 400
    assert call(http, db.sessions.count_documents, {}) == 2
    changed = http.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "another password!2"})
    assert changed.status_code == 204
    assert call(http, db.sessions.count_documents, {}) == 0
    assert http.get("/api/v1/users/me").status_code == 401
    assert login(http).status_code == 401
    authorize(http, login(http, password="another password!2"))
    assert http.post("/api/v1/users/me/disable").status_code == 204
    assert call(http, db.sessions.count_documents, {}) == 0
    assert http.get("/api/v1/users/me").status_code == 401
    assert login(http, password="another password!2").status_code == 401


def test_delete_account_and_stale_session_rejected(api):
    http, db = api
    register(http)
    authorize(http, login(http))
    original = call(http, db.sessions.find_one, {})
    assert http.delete("/api/v1/users/me").status_code == 204
    assert call(http, db.sessions.count_documents, {}) == 0
    assert call(http, db.users.count_documents, {}) == 0
    # Even an externally reintroduced session must not authenticate a deleted user.
    call(http, db.sessions.insert_one, original)
    assert http.get("/api/v1/users/me").status_code == 401


def test_origin_validation(api):
    http, _ = api
    for path in ["login", "refresh", "logout"]:
        response = http.post(f"/api/v1/auth/{path}", headers={"Origin": "https://evil.example"},
                             json={"email": EMAIL, "password": PASSWORD})
        assert response.status_code == 403
    http.headers.pop("Origin")
    assert http.post("/api/v1/auth/logout").status_code == 403


def test_tampered_missing_and_mismatched_jwt(api):
    http, _ = api
    register(http)
    token = authorize(http, login(http))
    claims = jwt.decode(token, options={"verify_signature": False})
    for bad in ["malformed", token + "tampered", issue_access_token({
        "user_id": ObjectId(), "session_id": claims["sid"],
        "expires_at": utcnow() + timedelta(days=1),
    }, http.app.state.settings)]:
        http.headers["Authorization"] = f"Bearer {bad}"
        assert http.get("/api/v1/users/me").status_code == 401
    http.headers.pop("Authorization")
    assert http.get("/api/v1/users/me").status_code == 401
