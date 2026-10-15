from pydantic import Field

from app.models.base import MongoModel


class TodoList(MongoModel):
    boardID: str
    ownerID: str
    title: str
    tasks: list[str] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)