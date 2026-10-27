"""Canonical stored account. Public responses use UserPublic, never this model."""

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
        extra="forbid",
        hide_input_in_errors=True,
        validate_assignment=True,
    )

    id: ObjectId = Field(alias="_id", frozen=True)
    name: str = Field(min_length=1, max_length=128, strict=True)
    email: EmailStr
    password_hash: str = Field(pattern=r"^\$argon2id\$", repr=False)
    email_verified: bool = Field(strict=True)
    disabled: bool = Field(strict=True)
    auth_version: int = Field(ge=0, strict=True)
    auth_serial: int = Field(ge=0, strict=True)

    @field_validator("name")
    @classmethod
    def canonical_name(cls, value):
        if value != value.strip():
            raise ValueError("Stored account names must be trimmed")
        return value

    @field_validator("email", mode="before")
    @classmethod
    def canonical_email(cls, value):
        if not isinstance(value, str) or value != value.strip().casefold():
            raise ValueError("Stored account emails must be normalized")
        return value
