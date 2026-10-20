from pydantic import BaseModel, Field


class BoardCreate(BaseModel):
    boardName: str = Field(min_length=1)
    createdBy: str
    members: list[str] = Field(default_factory=list)