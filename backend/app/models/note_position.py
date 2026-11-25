from pydantic import BaseModel, ConfigDict, Field


class NotePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0, le=5000, strict=True)
    y: int = Field(ge=0, le=5000, strict=True)
