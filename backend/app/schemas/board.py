from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.base import PyObjectId


class BoardCreate(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True, extra="forbid", hide_input_in_errors=True
    )
    boardName: str = Field(min_length=1, strict=True)
    createdBy: PyObjectId
    members: list[PyObjectId] = Field(default_factory=list)


class BoardUpdate(BaseModel):
    model_config = BoardCreate.model_config
    boardName: str | None = Field(default=None, min_length=1, strict=True)
    members: list[PyObjectId] | None = None

    @field_validator("boardName", "members", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Board fields cannot be null")
        return value

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("An update is required")
        return self
