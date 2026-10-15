from datetime import date
from pydantic import Field

from app.models.base import MongoModel


class Task(MongoModel):
    listID: str
    title: str
    description: str = ""
    completed: bool = False
    dueDate: date | None = None