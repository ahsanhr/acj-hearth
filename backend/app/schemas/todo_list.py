from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.base import PyObjectId
from app.models.note_position import NotePosition


class TodoListCreate(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True, extra="forbid", hide_input_in_errors=True
    )
    ownerID: PyObjectId
    title: str = Field(min_length=1, strict=True)


class TodoListUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: str | None = Field(default=None, min_length=1, strict=True)
    position: NotePosition | None = None

    @field_validator("title", "position", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("List fields cannot be null")
        return value

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("An update is required")
        return self
