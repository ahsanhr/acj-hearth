from datetime import datetime
from pydantic import Field

from app.models.base import MongoModel, current_time


class Board(MongoModel):
    boardName: str
    createdBy: str
    members: list[str] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=current_time)