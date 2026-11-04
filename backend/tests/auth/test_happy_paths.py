"""Authentication/session contracts: happy paths."""

from datetime import timedelta

from app.api.v1.endpoints.auth import COOKIE_NAME, COOKIE_PATH
from app.core.security import (
    decode_access_token,
    refresh_hash,
)
from bson import ObjectId

from tests.support.auth import EMAIL, authorize, call, login, register


def test_login_issues_secure_cookie_and_session_linked_access_token(api):
    http, db = api
    response = register(http, " USER@Example.com ")
    assert response.status_code == 201
    assert response.json()["email"] == EMAIL
    assert response.json()["email_verified"] is False
    response = login(http, "USER@example.com")
    token = authorize(http, response)
    cookie = http.cookies.get(COOKIE_NAME)
    cookie_header = response.headers["set-cookie"]
    for attribute in [
        "HttpOnly",
        "Secure",
        "SameSite=lax",
        f"Path={COOKIE_PATH}",
        "expires=",
    ]:
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
