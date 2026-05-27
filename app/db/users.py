import logging
from typing import Optional
from uuid import UUID

from app.db.supabase import supabase
from app.models.user import UserCreate, UserSchema

logger = logging.getLogger("grain.db.users")


def get_user_by_chat_id(chat_id: int) -> Optional[UserSchema]:
    try:
        result = supabase.table("users").select("*").eq("telegram_chat_id", chat_id).execute()
        if result.data:
            return UserSchema(**result.data[0])
    except Exception as e:
        logger.warning(f"Failed to look up user by chat_id {chat_id}: {e}")
    return None


def get_user_by_id(user_id: UUID) -> Optional[UserSchema]:
    try:
        result = supabase.table("users").select("*").eq("id", str(user_id)).execute()
        if result.data:
            return UserSchema(**result.data[0])
    except Exception as e:
        logger.warning(f"Failed to look up user by id {user_id}: {e}")
    return None


def create_user(chat_id: int, display_name: str = "Telegram User") -> UserSchema:
    data = UserCreate(telegram_chat_id=chat_id, display_name=display_name).model_dump()
    result = supabase.table("users").insert(data).execute()
    if not result.data:
        raise Exception(f"Failed to create user for chat_id {chat_id}")
    logger.info(f"Created new user for chat_id {chat_id}: id={result.data[0]["id"]}")
    return UserSchema(**result.data[0])


def get_or_create_user_by_chat_id(chat_id: int) -> UserSchema:
    """Returns the user for a chat_id, creating one if it doesn't exist."""
    user = get_user_by_chat_id(chat_id)
    if user:
        return user
    return create_user(chat_id)
