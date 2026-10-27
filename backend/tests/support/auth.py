"""Shared auth/session fixtures and HTTP helpers; no tests import test modules."""

from datetime import timedelta
from functools import partial
from uuid import uuid4

from app.core.security import utcnow
from bson import ObjectId

PASSWORD = "a long password!1"
EMAIL = "user@example.com"


def call(http, fn, *args, **kwargs):
    return http.portal.call(partial(fn, *args, **kwargs))


def register(http, email=EMAIL):
    return http.post("/api/v1/users", json={"email": email, "password": PASSWORD})


def login(http, email=EMAIL, password=PASSWORD):
    return http.post("/api/v1/auth/login", json={"email": email, "password": password})


def authorize(http, result):
    assert result.status_code == 200, result.text
    token = result.json()["access_token"]
    http.headers["Authorization"] = f"Bearer {token}"
    return token


def token_session():
    return {
        "user_id": ObjectId(),
        "session_id": str(uuid4()),
        "expires_at": utcnow() + timedelta(days=30),
    }
