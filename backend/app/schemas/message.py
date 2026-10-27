from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PyObjectId


class MessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    message: str = Field(min_length=1, strict=True)


class MessageCreate(MessageUpdate):
    model_config = ConfigDict(
        arbitrary_types_allowed=True, extra="forbid", hide_input_in_errors=True
    )
    replyTo: PyObjectId | None = None
