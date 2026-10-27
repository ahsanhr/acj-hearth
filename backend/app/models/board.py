from datetime import datetime

from pydantic import Field

from app.models.base import MongoModel, PyObjectId, current_time


class Board(MongoModel):
    boardName: str
    createdBy: PyObjectId
    members: list[PyObjectId] = Field(default_factory=list)
    mutation_serial: int = Field(default=0, ge=0, strict=True)
    createdAt: datetime = Field(default_factory=current_time)
