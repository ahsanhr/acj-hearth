from datetime import datetime
from pydantic import Field

from app.models.base import MongoModel, current_time


class Message(MongoModel):
    listID: str
    userID: str
    message: str
    createdAt: datetime = Field(default_factory=current_time)