from datetime import date

from app.models.base import MongoModel, PyObjectId


class Task(MongoModel):
    listID: PyObjectId
    title: str
    description: str = ""
    completed: bool = False
    dueDate: date | None = None
