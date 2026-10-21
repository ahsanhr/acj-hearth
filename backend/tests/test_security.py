from datetime import timedelta
from uuid import uuid4

from bson import ObjectId
import jwt
from pydantic import SecretStr, ValidationError
import pytest

from app.core.security import (
    decode_access_token, hash_password, issue_access_token, utcnow, verify_password,
)
from app.schemas.user import Registration


def session():
    return {"user_id": ObjectId(), "session_id": str(uuid4()),
            "expires_at": utcnow() + timedelta(days=30)}


def test_password_hash():
    raw = "a long password!1"
    hashed = hash_password(raw)
    assert hashed.startswith("$argon2id$")
    assert verify_password(raw, hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password(raw, "malformed")


def test_jwt_uniqueness_and_session_cap(auth_settings):
    record = session()
    record["expires_at"] = utcnow() + timedelta(seconds=60)
    first = issue_access_token(record, auth_settings)
    second = issue_access_token(record, auth_settings)
    claims = decode_access_token(first, auth_settings)
    assert first != second
    assert claims["sid"] == record["session_id"]
    assert claims["sub"] == str(record["user_id"])
    assert claims["exp"] <= int(record["expires_at"].timestamp())
    assert claims["jti"] != decode_access_token(second, auth_settings)["jti"]


@pytest.mark.parametrize("mutation", [{"iss": "wrong"}, {"aud": "wrong"}])
def test_jwt_rejects_wrong_issuer_or_audience(auth_settings, mutation):
    token = issue_access_token(session(), auth_settings)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.update(mutation)
    token = jwt.encode(claims, "a" * 48, algorithm="HS256", headers={"kid": "current"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, auth_settings)


def test_jwt_requires_session_claim(auth_settings):
    claims = jwt.decode(issue_access_token(session(), auth_settings), options={"verify_signature": False})
    claims.pop("sid")
    token = jwt.encode(claims, "a" * 48, algorithm="HS256", headers={"kid": "current"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, auth_settings)


def test_key_rotation(auth_settings):
    old = issue_access_token(session(), auth_settings)
    auth_settings.AUTH_PREVIOUS_SECRET = auth_settings.AUTH_SIGNING_SECRET
    auth_settings.AUTH_PREVIOUS_KEY_ID = "current"
    auth_settings.AUTH_KEY_ID = "next"
    auth_settings.AUTH_SIGNING_SECRET = SecretStr("b" * 48)
    decode_access_token(old, auth_settings)
    decode_access_token(issue_access_token(session(), auth_settings), auth_settings)
    auth_settings.AUTH_PREVIOUS_SECRET = None
    auth_settings.AUTH_PREVIOUS_KEY_ID = None
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(old, auth_settings)


@pytest.mark.parametrize("algorithm,key", [("HS384", "a" * 48), ("HS256", "b" * 48)])
def test_wrong_algorithm_or_signature(auth_settings, algorithm, key):
    claims = jwt.decode(issue_access_token(session(), auth_settings), options={"verify_signature": False})
    token = jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "current"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, auth_settings)


@pytest.mark.parametrize("password", [
    "short!1", "long password ! abc", "long password 1   ",
])
def test_password_policy_rejections(password):
    with pytest.raises(ValidationError):
        Registration(email="user@example.com", password=password)


def test_registration_normalization_and_password_preservation():
    raw = "  Unicode café 🏠 1  "
    payload = Registration(email=" USER@Example.com ", password=raw)
    assert str(payload.email) == "user@example.com"
    assert payload.password.get_secret_value() == raw


def test_missing_signing_secret_fails_startup_configuration(auth_settings):
    auth_settings.AUTH_SIGNING_SECRET = None
    with pytest.raises(ValueError):
        auth_settings.validate_auth()
