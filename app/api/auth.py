"""Authentication for the web dashboard — one-time Telegram code + API key fallback."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

from app.core.config import settings
from app.core.logger import logger
from app.db.users import get_user_by_id, get_user_by_chat_id, create_telegram_link_token
from app.db.supabase import supabase

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Request / Response models ────────────────────────────────────────────


class RequestCodeRequest(BaseModel):
    telegram_chat_id: int


class VerifyCodeRequest(BaseModel):
    telegram_chat_id: int
    code: str


class SessionTokenResponse(BaseModel):
    session_token: str
    user: dict


class TelegramLinkTokenResponse(BaseModel):
    token: str
    telegram_url: str
    expires_in_minutes: int


class ApiKeyCreate(BaseModel):
    name: str = "Default API Key"
    expires_in_days: Optional[int] = None


class ApiKeyResponse(BaseModel):
    id: str
    key: str
    key_prefix: str
    name: str
    created_at: str
    expires_at: Optional[str] = None


# ── Session JWT helpers ──────────────────────────────────────────────────


def create_session_token(user_id: UUID) -> str:
    """Create a short-lived JWT session token."""
    if not settings.SESSION_SECRET:
        logger.error("SESSION_SECRET is not set — cannot create session tokens")
        raise HTTPException(
            status_code=500,
            detail="Server misconfigured: SESSION_SECRET is not set. Contact the admin.",
        )
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SESSION_SECRET, algorithm="HS256")


def verify_session_token(token: str) -> Optional[UUID]:
    """Decode a session JWT and return the user UUID, or None if invalid."""
    if not settings.SESSION_SECRET:
        return None
    try:
        payload = jwt.decode(token, settings.SESSION_SECRET, algorithms=["HS256"])
        return UUID(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None


# ── Auth code helpers ────────────────────────────────────────────────────


def _generate_code() -> str:
    """Generate a 6-digit numeric one-time code."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _store_code(user_id: UUID, code: str, ttl_minutes: int = 5) -> None:
    """Store a one-time code in the auth_codes table."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    supabase.table("auth_codes").insert({
        "user_id": str(user_id),
        "code": code,
        "expires_at": expires_at.isoformat(),
    }).execute()


def _verify_code(user_id: UUID, code: str) -> bool:
    """Check if a code is valid, not expired, and not yet used. Marks it used on success."""
    now = datetime.now(timezone.utc).isoformat()
    result = supabase.table("auth_codes")\
        .select("*")\
        .eq("user_id", str(user_id))\
        .eq("code", code)\
        .is_("used_at", "null")\
        .execute()

    if not result.data:
        return False

    record = result.data[0]
    expires_at = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
    if expires_at < now:
        return False

    supabase.table("auth_codes")\
        .update({"used_at": now})\
        .eq("id", record["id"])\
        .execute()
    return True


def _extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract the Bearer token from the Authorization header."""
    if not authorization:
        return ""
    if authorization.startswith("Bearer "):
        return authorization.replace("Bearer ", "").strip()
    return authorization.strip()


# ── Unified auth dependency ──────────────────────────────────────────────


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> UUID:
    """Dependency: accepts either a session JWT or an API key.
    Raises 401 if missing or invalid.
    """
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Try session JWT first
    user_id = verify_session_token(token)
    if user_id:
        return user_id

    # Fall back to API key
    user_id = _verify_api_key_auth(token)
    if user_id:
        return user_id

    raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
) -> Optional[UUID]:
    """Same as get_current_user but returns None instead of 401."""
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    user_id = verify_session_token(token)
    if user_id:
        return user_id
    return _verify_api_key_auth(token)


# ── API key helpers (for programmatic access) ────────────────────────────


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return f"grain_{secrets.token_urlsafe(32)}"


def _verify_api_key_auth(api_key: str) -> Optional[UUID]:
    """Verify an API key and return the user UUID, or None."""
    if not api_key or not api_key.startswith("grain_"):
        return None
    key_hash = hash_api_key(api_key)
    try:
        result = supabase.table("api_keys")\
            .select("*")\
            .eq("key_hash", key_hash)\
            .eq("is_active", True)\
            .execute()
        if not result.data:
            return None
        key_record = result.data[0]
        if key_record.get("expires_at"):
            expires_at = datetime.fromisoformat(key_record["expires_at"].replace("Z", "+00:00"))
            if expires_at < datetime.now(timezone.utc):
                return None
        supabase.table("api_keys")\
            .update({"last_used_at": datetime.now(timezone.utc).isoformat()})\
            .eq("id", key_record["id"])\
            .execute()
        return UUID(key_record["user_id"])
    except Exception as e:
        logger.warning(f"API key verification failed: {e}")
        return None


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/request-code")
async def request_code(req: RequestCodeRequest):
    """Step 1: User enters their Telegram chat ID on the login page.
    Sends a 6-digit code to their Telegram and stores it.
    """
    user = get_user_by_chat_id(req.telegram_chat_id)
    if not user:
        raise HTTPException(status_code=404, detail="No Grain account found for this Telegram chat ID. Send a message to the bot first.")

    code = _generate_code()
    _store_code(user.id, code)

    from app.integrations.telegram import send_message
    try:
        await send_message(
            req.telegram_chat_id,
            f"🔑 Your Grain login code: *{code}*\n\nExpires in 5 minutes."
        )
    except Exception as e:
        logger.error(f"Failed to send login code to chat {req.telegram_chat_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to send code via Telegram. Is the bot running?")

    return {"message": "Code sent to your Telegram"}


@router.post("/verify-code", response_model=SessionTokenResponse)
async def verify_code(req: VerifyCodeRequest):
    """Step 2: User enters the 6-digit code. Returns a session JWT."""
    user = get_user_by_chat_id(req.telegram_chat_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not _verify_code(user.id, req.code):
        raise HTTPException(status_code=401, detail="Invalid or expired code")

    token = create_session_token(user.id)
    return SessionTokenResponse(
        session_token=token,
        user={
            "id": str(user.id),
            "telegram_chat_id": user.telegram_chat_id,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        },
    )


@router.get("/me")
async def get_current_user_info(
    user_id: UUID = Depends(get_current_user),
):
    """Returns the authenticated user's info."""
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": str(user.id),
        "telegram_chat_id": user.telegram_chat_id,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat(),
    }


@router.post("/api-keys", response_model=ApiKeyResponse)
async def create_api_key(
    request: ApiKeyCreate,
    user_id: UUID = Depends(get_current_user),
):
    """Creates a new API key for the current user (advanced/programmatic access)."""
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    key_prefix = api_key[:8]
    expires_at = None
    if request.expires_in_days:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=request.expires_in_days)).isoformat()
    result = supabase.table("api_keys").insert({
        "user_id": str(user_id),
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "name": request.name,
        "expires_at": expires_at,
    }).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create API key")
    key_record = result.data[0]
    return ApiKeyResponse(
        id=key_record["id"],
        key=api_key,
        key_prefix=key_prefix,
        name=request.name,
        created_at=key_record["created_at"],
        expires_at=expires_at,
    )


@router.get("/api-keys")
async def list_api_keys(
    user_id: UUID = Depends(get_current_user),
):
    """Lists all API keys for the current user (without the actual keys)."""
    result = supabase.table("api_keys")\
        .select("id, key_prefix, name, created_at, last_used_at, expires_at, is_active")\
        .eq("user_id", str(user_id))\
        .order("created_at", desc=True)\
        .execute()
    return {"api_keys": result.data or []}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user_id: UUID = Depends(get_current_user),
):
    """Revokes (deletes) an API key."""
    result = supabase.table("api_keys")\
        .select("id")\
        .eq("id", key_id)\
        .eq("user_id", str(user_id))\
        .execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="API key not found")
    supabase.table("api_keys").delete().eq("id", key_id).execute()
    return {"status": "deleted", "key_id": key_id}


@router.post("/telegram-link-token", response_model=TelegramLinkTokenResponse)
async def telegram_link_token(authorization: Optional[str] = Header(None)):
    """Creates a one-time token for linking the current user's Telegram account."""
    user_id = await get_current_user(authorization)
    token = create_telegram_link_token(user_id)
    return TelegramLinkTokenResponse(
        token=token,
        telegram_url=build_telegram_link_url(token),
        expires_in_minutes=10,
    )


def build_telegram_link_url(token: str) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"
