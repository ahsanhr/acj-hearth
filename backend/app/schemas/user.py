import unicodedata
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailStr
    password: SecretStr = Field(max_length=4096)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().casefold() if isinstance(value, str) else value


def validate_new_password(value: SecretStr) -> SecretStr:
    password = value.get_secret_value()
    if not 15 <= len(password) <= 128:
        raise ValueError("Password must contain 15–128 characters")
    if not any(c in "0123456789" for c in password):
        raise ValueError("Password must contain at least one digit (0–9)")
    if not any(unicodedata.category(c)[0] in {"P", "S"} for c in password):
        raise ValueError("Password must contain at least one punctuation or symbol character")
    return value


class Registration(Credentials):
    @field_validator("password")
    @classmethod
    def password_policy(cls, value):
        return validate_new_password(value)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    current_password: SecretStr = Field(max_length=4096)
    new_password: SecretStr

    @field_validator("new_password")
    @classmethod
    def password_policy(cls, value):
        return validate_new_password(value)


class UserPublic(BaseModel):
    id: str
    email: str
    email_verified: bool = False
