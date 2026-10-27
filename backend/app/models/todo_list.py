from pydantic import Field

from app.models.base import MongoModel, PyObjectId


class TodoList(MongoModel):
    boardID: PyObjectId
    ownerID: PyObjectId | None
    title: str
    tasks: list[PyObjectId] = Field(default_factory=list)
    messages: list[PyObjectId] = Field(default_factory=list)
