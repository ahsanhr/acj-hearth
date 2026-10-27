from datetime import datetime, timezone
from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, WithJsonSchema


def object_id(value):
    if not isinstance(value, (ObjectId, str)):
        raise ValueError("Invalid MongoDB identifier")
    try:
        return value if isinstance(value, ObjectId) else ObjectId(value)
    except (InvalidId, ValueError, TypeError) as exc:
        raise ValueError("Invalid MongoDB identifier") from exc


PyObjectId = Annotated[
    ObjectId,
    BeforeValidator(object_id),
    PlainSerializer(str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": "^[a-fA-F0-9]{24}$"}),
]


class MongoModel(BaseModel):
    id: PyObjectId | None = Field(
        default=None,
        alias="_id",
        frozen=True,
    )

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "extra": "forbid",
        "hide_input_in_errors": True,
    }


def current_time():
    return datetime.now(timezone.utc)
