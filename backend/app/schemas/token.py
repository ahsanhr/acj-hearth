from datetime import datetime

from pydantic import BaseModel


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SessionPublic(BaseModel):
    session_id: str
    created_at: datetime
    expires_at: datetime
    current: bool
