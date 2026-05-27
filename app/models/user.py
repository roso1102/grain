from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class UserCreate(BaseModel):
    telegram_chat_id: int
    display_name: str = "Telegram User"


class UserSchema(BaseModel):
    id: UUID
    telegram_chat_id: Optional[int] = None
    display_name: Optional[str] = None
    created_at: datetime
