"""Authentication/session contracts: authorization."""

from datetime import timedelta

import jwt
import pytest
from app.core.security import (
    decode_access_token,
    issue_access_token,
    utcnow,
)
from bson import ObjectId
from pydantic import SecretStr

from tests.auth_support import (
    EMAIL,
    PASSWORD,
    authorize,
    call,
    login,
    register,
    token_session,
)


def test_refresh_when_access_expired_and_session_boundary(api):
    http, db = api
    register(http)
    token = authorize(http, login(http))
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.update(
        iat=int((utcnow() - timedelta(minutes=20)).timestamp()),
        exp=int((utcnow() - timedelta(minutes=5)).timestamp()),
    )
    expired = jwt.encode(
        claims, "a" * 48, algorithm="HS256", headers={"kid": "current"}
    )
    http.headers["Authorization"] = f"Bearer {expired}"
    assert http.get("/api/v1/users/me").status_code == 401
    assert http.post("/api/v1/auth/refresh").status_code == 200
    call(
        http,
        db.sessions.update_one,
        {"session_id": claims["sid"]},
        {"$set": {"expires_at": utcnow()}},
    )
    assert http.post("/api/v1/auth/refresh").status_code == 401
    http.headers["Authorization"] = f"Bearer {token}"
    assert http.get("/api/v1/users/me").status_code == 401


def test_disabled_account_revokes_sessions_and_cannot_authenticate(api):
    http, db = api
    assert register(http).status_code == 201
    authorize(http, login(http))
    token = authorize(http, login(http))
    claims = decode_access_token(token, http.app.state.settings)
    original = call(http, db.sessions.find_one, {"session_id": claims["sid"]})
    assert call(http, db.sessions.count_documents, {}) == 2
    assert http.post("/api/v1/users/me/disable").status_code == 204
    assert call(http, db.sessions.count_documents, {}) == 0
    assert http.get("/api/v1/users/me").status_code == 401
    assert login(http).status_code == 401
    # Status checks must not depend solely on the session having been deleted.
    call(http, db.sessions.insert_one, original)
    assert http.get("/api/v1/users/me").status_code == 401


def test_delete_account_and_stale_session_rejected(api):
    http, db = api
    register(http)
    authorize(http, login(http))
    original = call(http, db.sessions.find_one, {})
    assert (
        http.request(
            "DELETE", "/api/v1/users/me", json={"current_password": PASSWORD}
        ).status_code
        == 204
    )
    assert call(http, db.sessions.count_documents, {}) == 0
    assert call(http, db.users.count_documents, {}) == 0
    # Even an externally reintroduced session must not authenticate a deleted user.
    call(http, db.sessions.insert_one, original)
    assert http.get("/api/v1/users/me").status_code == 401


def test_origin_validation(api):
    http, _ = api
    for path in ["login", "refresh", "logout"]:
        response = http.post(
            f"/api/v1/auth/{path}",
            headers={"Origin": "https://evil.example"},
            json={"email": EMAIL, "password": PASSWORD},
        )
        assert response.status_code == 403
    http.headers.pop("Origin")
    assert http.post("/api/v1/auth/logout").status_code == 403


def test_tampered_missing_and_mismatched_jwt(api):
    http, _ = api
    register(http)
    token = authorize(http, login(http))
    claims = jwt.decode(token, options={"verify_signature": False})
    for bad in [
        "malformed",
        token + "tampered",
        issue_access_token(
            {
                "user_id": ObjectId(),
                "session_id": claims["sid"],
                "expires_at": utcnow() + timedelta(days=1),
            },
            http.app.state.settings,
        ),
    ]:
        http.headers["Authorization"] = f"Bearer {bad}"
        assert http.get("/api/v1/users/me").status_code == 401
    http.headers.pop("Authorization")
    assert http.get("/api/v1/users/me").status_code == 401


@pytest.mark.parametrize("mutation", [{"iss": "wrong"}, {"aud": "wrong"}])
def test_jwt_rejects_wrong_issuer_or_audience(auth_settings, mutation):
    token = issue_access_token(token_session(), auth_settings)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.update(mutation)
    token = jwt.encode(claims, "a" * 48, algorithm="HS256", headers={"kid": "current"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, auth_settings)


def test_jwt_requires_session_claim(auth_settings):
    claims = jwt.decode(
        issue_access_token(token_session(), auth_settings),
        options={"verify_signature": False},
    )
    claims.pop("sid")
    token = jwt.encode(claims, "a" * 48, algorithm="HS256", headers={"kid": "current"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, auth_settings)


def test_key_rotation(auth_settings):
    old = issue_access_token(token_session(), auth_settings)
    auth_settings.AUTH_PREVIOUS_SECRET = auth_settings.AUTH_SIGNING_SECRET
    auth_settings.AUTH_PREVIOUS_KEY_ID = "current"
    auth_settings.AUTH_KEY_ID = "next"
    auth_settings.AUTH_SIGNING_SECRET = SecretStr("b" * 48)
    decode_access_token(old, auth_settings)
    decode_access_token(
        issue_access_token(token_session(), auth_settings), auth_settings
    )
    auth_settings.AUTH_PREVIOUS_SECRET = None
    auth_settings.AUTH_PREVIOUS_KEY_ID = None
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(old, auth_settings)


@pytest.mark.parametrize("algorithm,key", [("HS384", "a" * 48), ("HS256", "b" * 48)])
def test_wrong_algorithm_or_signature(auth_settings, algorithm, key):
    claims = jwt.decode(
        issue_access_token(token_session(), auth_settings),
        options={"verify_signature": False},
    )
    token = jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "current"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, auth_settings)
