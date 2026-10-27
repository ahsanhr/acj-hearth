from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PyObjectId


class TodoListCreate(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True, extra="forbid", hide_input_in_errors=True
    )
    ownerID: PyObjectId
    title: str = Field(min_length=1, strict=True)


class TodoListUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: str = Field(min_length=1, strict=True)
