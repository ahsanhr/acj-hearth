import unicodedata
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


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
        raise ValueError(
            "Password must contain at least one punctuation or symbol character"
        )
    return value


class Registration(Credentials):
    @field_validator("password")
    @classmethod
    def password_policy(cls, value):
        return validate_new_password(value)


class PasswordConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    current_password: SecretStr = Field(max_length=4096)


class AccountPatch(PasswordConfirmation):
    name: Annotated[str, Field(strict=True, min_length=1, max_length=128)] | None = None
    email: EmailStr | None = None
    new_password: SecretStr | None = None

    @field_validator("name", "email", "new_password", mode="before")
    @classmethod
    def normalize_submitted_fields(cls, value, info):
        # Defaults represent omission; explicitly submitted nulls are invalid.
        if value is None:
            raise ValueError("Account fields cannot be null")
        if isinstance(value, str) and info.field_name in {"name", "email"}:
            return (
                value.strip().casefold()
                if info.field_name == "email"
                else value.strip()
            )
        return value

    @field_validator("new_password")
    @classmethod
    def password_policy(cls, value):
        return validate_new_password(value)

    @model_validator(mode="after")
    def require_mutable_field(self):
        if not self.model_fields_set & {"name", "email", "new_password"}:
            raise ValueError("At least one mutable account field is required")
        return self


class UserPublic(BaseModel):
    id: str
    name: str
    email: str
    email_verified: bool = False
