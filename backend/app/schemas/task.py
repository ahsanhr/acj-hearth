from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: str = Field(min_length=1, strict=True)
    description: str = ""
    dueDate: date | None = None


class TaskUpdate(BaseModel):
    model_config = TaskCreate.model_config
    title: str | None = Field(default=None, min_length=1, strict=True)
    description: str | None = None
    completed: bool | None = None
    dueDate: date | None = None

    @field_validator("title", "description", "completed", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Only the due date may be cleared")
        return value
