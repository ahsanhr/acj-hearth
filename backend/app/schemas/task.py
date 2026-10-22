
from datetime import date

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    dueDate: date | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    completed: bool | None = None
    dueDate: date | None = None
