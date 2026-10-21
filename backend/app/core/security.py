"""Password hashing and strictly validated, short-lived access JWTs."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from bson import ObjectId
import jwt

from app.core.config import Settings

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
REQUIRED_CLAIMS = ["sub", "sid", "exp", "iat", "jti", "iss", "aud"]


def utcnow():
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_access_token(session: dict, settings: Settings) -> str:
    now = utcnow()
    return jwt.encode(
        {
            "sub": str(session["user_id"]),
            "sid": session["session_id"],
            "iat": int(now.timestamp()),
            "exp": int(min(now + timedelta(minutes=15), session["expires_at"]).timestamp()),
            "jti": str(uuid4()),
            "iss": settings.AUTH_ISSUER,
            "aud": settings.AUTH_AUDIENCE,
        },
        settings.AUTH_SIGNING_SECRET.get_secret_value(),
        algorithm="HS256",
        headers={"kid": settings.AUTH_KEY_ID},
    )


def decode_access_token(token: str, settings: Settings) -> dict:
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "HS256":
        raise jwt.InvalidTokenError("Unexpected algorithm")
    keys = {settings.AUTH_KEY_ID: settings.AUTH_SIGNING_SECRET}
    if settings.AUTH_PREVIOUS_SECRET and settings.AUTH_PREVIOUS_KEY_ID:
        keys[settings.AUTH_PREVIOUS_KEY_ID] = settings.AUTH_PREVIOUS_SECRET
    key = keys.get(header.get("kid")) if isinstance(header.get("kid"), str) else None
    if key is None:
        raise jwt.InvalidTokenError("Unknown key ID")
    claims = jwt.decode(
        token, key.get_secret_value(), algorithms=["HS256"],
        issuer=settings.AUTH_ISSUER, audience=settings.AUTH_AUDIENCE,
        leeway=30, options={"require": REQUIRED_CLAIMS, "strict_aud": True},
    )
    if any(not isinstance(claims[name], str) or not claims[name]
           for name in ["sub", "sid", "jti", "iss", "aud"]):
        raise jwt.InvalidTokenError("Invalid claim types")
    if any(type(claims[name]) is not int for name in ["exp", "iat"]):
        raise jwt.InvalidTokenError("Invalid timestamp types")
    if claims["exp"] <= claims["iat"] or claims["exp"] - claims["iat"] > 900:
        raise jwt.InvalidTokenError("Invalid token lifetime")
    if not ObjectId.is_valid(claims["sub"]):
        raise jwt.InvalidTokenError("Invalid subject")
    try:
        UUID(claims["sid"])
        UUID(claims["jti"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise jwt.InvalidTokenError("Invalid token identifiers") from exc
    return claims
