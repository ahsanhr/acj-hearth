from pydantic import BaseModel, Field


class TodoListCreate(BaseModel):
    ownerID: str = Field(min_length=1)
    title: str = Field(min_length=1)