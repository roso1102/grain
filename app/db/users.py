import logging
import secrets
from datetime import datetime, timedelta, timezone
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


def get_user_by_supabase_id(supabase_user_id: UUID) -> Optional[UserSchema]:
    try:
        result = supabase.table("users").select("*").eq("supabase_user_id", str(supabase_user_id)).execute()
        if result.data:
            return UserSchema(**result.data[0])
    except Exception as e:
        logger.warning(f"Failed to look up user by supabase_user_id {supabase_user_id}: {e}")
    return None


def create_user_from_supabase(supabase_user_id: UUID, display_name: str = "Supabase User") -> UserSchema:
    data = {
        "supabase_user_id": str(supabase_user_id),
        "display_name": display_name,
    }
    result = supabase.table("users").insert(data).execute()
    if not result.data:
        raise Exception(f"Failed to create user for supabase_user_id {supabase_user_id}")
    logger.info(f"Created new user for supabase_user_id {supabase_user_id}: id={result.data[0]['id']}")
    return UserSchema(**result.data[0])


def create_user(chat_id: int, display_name: str = "Telegram User") -> UserSchema:
    data = UserCreate(telegram_chat_id=chat_id, display_name=display_name).model_dump()
    result = supabase.table("users").insert(data).execute()
    if not result.data:
        raise Exception(f"Failed to create user for chat_id {chat_id}")
    logger.info(f"Created new user for chat_id {chat_id}: id={result.data[0]['id']}")
    return UserSchema(**result.data[0])


def get_or_create_user_by_chat_id(chat_id: int) -> UserSchema:
    """Returns the user for a chat_id, creating one if it doesn't exist."""
    user = get_user_by_chat_id(chat_id)
    if user:
        return user
    return create_user(chat_id)


def link_user_to_supabase(chat_id: int, supabase_user_id: UUID) -> Optional[UserSchema]:
    """Links a Telegram user to their Supabase Auth account."""
    try:
        result = supabase.table("users")\
            .update({"supabase_user_id": str(supabase_user_id)})\
            .eq("telegram_chat_id", chat_id)\
            .execute()
        if result.data:
            logger.info(f"Linked user chat_id={chat_id} to supabase_user_id={supabase_user_id}")
            return UserSchema(**result.data[0])
    except Exception as e:
        logger.warning(f"Failed to link user {chat_id} to supabase_user_id {supabase_user_id}: {e}")
    return None


def create_telegram_link_token(user_id: UUID, ttl_minutes: int = 10) -> str:
    """Creates a short-lived one-time token used to link Telegram to a Grain user."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    result = supabase.table("telegram_link_tokens").insert({
        "token": token,
        "user_id": str(user_id),
        "expires_at": expires_at.isoformat(),
    }).execute()
    if not result.data:
        raise Exception("Failed to create Telegram link token")
    return token


def consume_telegram_link_token(token: str, telegram_chat_id: int) -> Optional[UserSchema]:
    """Consumes a token and links the Telegram chat ID to the associated Grain user."""
    try:
        result = supabase.table("telegram_link_tokens").select("*").eq("token", token).execute()
        rows = result.data or []
        if not rows:
            return None

        row = rows[0]
        if row.get("consumed_at"):
            return None

        expires_at_raw = row.get("expires_at")
        if expires_at_raw:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
            if expires_at < datetime.now(timezone.utc):
                return None

        user_id = row.get("user_id")
        if not user_id:
            return None

        user = get_user_by_id(UUID(user_id))
        if not user:
            return None

        if user.telegram_chat_id is not None and user.telegram_chat_id != telegram_chat_id:
            logger.warning(
                f"Refusing Telegram relink for user_id={user_id}: existing chat_id={user.telegram_chat_id}, incoming chat_id={telegram_chat_id}"
            )
            return None

        linked = supabase.table("users").update({
            "telegram_chat_id": telegram_chat_id,
        }).eq("id", str(user.id)).execute()
        if not linked.data:
            return None

        supabase.table("telegram_link_tokens").update({
            "consumed_at": datetime.now(timezone.utc).isoformat(),
            "telegram_chat_id": telegram_chat_id,
        }).eq("token", token).execute()

        return UserSchema(**linked.data[0])
    except Exception as e:
        logger.warning(f"Failed to consume Telegram link token: {e}")
    return None
