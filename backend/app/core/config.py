from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "hearth"
    # No fallback signing secret: startup must fail when it is missing.
    AUTH_SIGNING_SECRET: SecretStr | None = None
    AUTH_KEY_ID: str = "current"
    AUTH_PREVIOUS_SECRET: SecretStr | None = None
    AUTH_PREVIOUS_KEY_ID: str | None = None
    AUTH_ISSUER: str = "hearth"
    AUTH_AUDIENCE: str = "hearth-api"
    AUTH_ALLOWED_ORIGINS: list[str] = []
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    def validate_auth(self):
        if not self.AUTH_SIGNING_SECRET or len(
            self.AUTH_SIGNING_SECRET.get_secret_value().encode()
        ) < 32:
            raise ValueError("AUTH_SIGNING_SECRET must contain at least 32 bytes")
        if not self.AUTH_KEY_ID or not self.AUTH_ISSUER or not self.AUTH_AUDIENCE:
            raise ValueError("JWT key ID, issuer, and audience must not be empty")
        if bool(self.AUTH_PREVIOUS_SECRET) != bool(self.AUTH_PREVIOUS_KEY_ID):
            raise ValueError("Configure both previous key ID and secret, or neither")
        if self.AUTH_PREVIOUS_SECRET:
            if len(self.AUTH_PREVIOUS_SECRET.get_secret_value().encode()) < 32:
                raise ValueError("Previous JWT secret must contain at least 32 bytes")
            if self.AUTH_PREVIOUS_KEY_ID == self.AUTH_KEY_ID:
                raise ValueError("Current and previous JWT key IDs must differ")
        from urllib.parse import urlsplit

        for origin in self.AUTH_ALLOWED_ORIGINS:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password
                or "*" in origin
            ):
                raise ValueError("Allowed origins must be exact HTTP(S) origins")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()