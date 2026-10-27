from datetime import datetime

from pydantic import Field, model_validator

from app.models.base import MongoModel, PyObjectId, current_time


class Message(MongoModel):
    listID: PyObjectId
    userID: PyObjectId | None
    message: str
    createdAt: datetime = Field(default_factory=current_time)
    replyTo: PyObjectId | None = None
    deleted: bool = False

    @model_validator(mode="after")
    def valid_author_state(self):
        if self.deleted:
            if self.userID is not None or self.message != "message deleted":
                raise ValueError("Deleted messages must be anonymous placeholders")
        elif self.userID is None:
            raise ValueError("An active message requires an author")
        return self


def tombstone_document(message):
    # A replacement whitelist removes cached authors, attachments, and any other
    # original content rather than trying to enumerate fields to unset.
    metadata = {
        key: message[key]
        for key in ("_id", "listID", "createdAt", "replyTo")
        if key in message
    }
    return {**metadata, "userID": None, "message": "message deleted", "deleted": True}
