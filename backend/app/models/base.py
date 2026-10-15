from datetime import datetime, timezone
from typing import Annotated

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, Field


PyObjectId = Annotated[str, BeforeValidator(str)]


class MongoModel(BaseModel):
    id: PyObjectId | None = Field(
        default=None,
        alias="_id"
    )

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True
    }


def current_time():
    return datetime.now(timezone.utc)