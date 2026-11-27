from pydantic import Field

from app.models.base import MongoModel, PyObjectId
from app.models.note_position import NotePosition


class TodoList(MongoModel):
    boardID: PyObjectId
    ownerID: PyObjectId | None
    title: str
    position: NotePosition | None = None
    tasks: list[PyObjectId] = Field(default_factory=list)
    messages: list[PyObjectId] = Field(default_factory=list)
