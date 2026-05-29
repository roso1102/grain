"""Telegram Login authentication for the web dashboard."""
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import httpx

from app.core.config import settings
from app.core.logger import logger
from app.db.users import get_user_by_chat_id, get_user_by_id, create_telegram_link_token
from app.db.users import get_user_by_supabase_id, create_user_from_supabase

router = APIRouter(prefix="/auth", tags=["Auth"])

SESSION_EXPIRE_HOURS = 72


class TelegramLoginData(BaseModel):
    """Incoming data from the Telegram Login Widget."""
    id: int
    first_name: str
    last_name: str = ""
    username: str = ""
    photo_url: str = ""
    auth_date: int  # Unix timestamp
    hash: str


class TelegramLinkTokenResponse(BaseModel):
    token: str
    telegram_url: str
    expires_in_minutes: int


def build_telegram_link_url(token: str) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"


def _verify_telegram_login(data: TelegramLoginData) -> bool:
    """
    Verifies the Telegram Login Widget callback signature.
    https://core.telegram.org/widgets/login#checking-authorization
    """
    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set — cannot verify Telegram login")
        return False

    # Build the data-check string: sorted alphabetically, excluding hash
    fields = []
    for key, value in sorted(data.model_dump(exclude={"hash"}).items()):
        if value:  # only include non-empty values
            fields.append(f"{key}={value}")
    data_check_string = "\n".join(fields)

    # Telegram Login Widget verification uses SHA256(bot_token) as the secret key.
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()

    # Compute expected hash
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Compare in constant time
    return hmac.compare_digest(computed_hash, data.hash)


def _is_auth_date_recent(auth_date: int, max_age_seconds: int = 86400) -> bool:
    """Checks that the auth_date isn't older than max_age_seconds."""
    now = time.time()
    return (now - auth_date) < max_age_seconds


def create_session_token(user_id: UUID) -> str:
    """Issues a signed JWT containing the user's UUID."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(hours=SESSION_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.SESSION_SECRET, algorithm="HS256")


def create_session_token_for_chat_id(chat_id: int) -> Optional[str]:
    """Looks up user by Telegram chat_id and issues a session token."""
    user = get_user_by_chat_id(chat_id)
    if not user:
        return None
    return create_session_token(user.id)


def _verify_session_token(token: Optional[str]) -> Optional[UUID]:
    """Core JWT verification. Returns user_id or None."""
    if not token or token == "null":
        return None
    if not settings.SESSION_SECRET:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.SESSION_SECRET,
            algorithms=["HS256"],
        )
        sub = payload.get("sub")
        if sub:
            return UUID(sub)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    return None


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> UUID:
    """
    Dependency: extracts and validates the session JWT from the Authorization header.
    Returns the user's UUID. Raises 401 if missing or invalid.
    """
    token = authorization.replace("Bearer ", "").strip() if authorization else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    user_id = _verify_session_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_id


async def _verify_supabase_token(access_token: str) -> dict:
    """Verify a Supabase access token by calling the Supabase /auth/v1/user endpoint.
    Returns the user object on success or raises HTTPException(401).
    """
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing Supabase access token")
    if not settings.SUPABASE_URL:
        raise HTTPException(status_code=500, detail="SUPABASE_URL not configured")

    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": settings.SUPABASE_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to contact Supabase: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Supabase session token")
    try:
        return resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid response from Supabase")


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
) -> Optional[UUID]:
    """
    Same as get_current_user but returns None instead of 401 when no valid token.
    Use for dual-auth endpoints that also accept X-User-Id header.
    """
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    try:
        user_id = _verify_session_token(token)
        return user_id
    except HTTPException:
        return None


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/telegram-login")
async def telegram_login(data: TelegramLoginData):
    """
    Called by the web dashboard after the Telegram Login Widget succeeds.
    Verifies the signature, looks up or creates the user, returns a session token.
    """
    # 1. Verify the Telegram callback signature
    if not _verify_telegram_login(data):
        raise HTTPException(status_code=401, detail="Telegram login verification failed")

    # 2. Reject old auth dates (max 24 hours old)
    if not _is_auth_date_recent(data.auth_date):
        raise HTTPException(status_code=401, detail="Login expired, please try again")

    # 3. Look up or create the user by telegram_chat_id
    telegram_chat_id = data.id
    user = get_user_by_chat_id(telegram_chat_id)
    if not user:
        from app.db.users import create_user
        display_name = data.first_name
        if data.last_name:
            display_name += f" {data.last_name}"
        if data.username:
            display_name += f" (@{data.username})"
        user = create_user(telegram_chat_id, display_name=display_name)

    # 4. Issue session token
    session_token = create_session_token(user.id)

    return {
        "session_token": session_token,
        "expires_in_hours": SESSION_EXPIRE_HOURS,
        "user": {
            "id": str(user.id),
            "telegram_chat_id": user.telegram_chat_id,
            "display_name": user.display_name,
        },
    }


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


@router.post("/telegram-link-token", response_model=TelegramLinkTokenResponse)
async def telegram_link_token(authorization: Optional[str] = Header(None)):
    """Creates a one-time token for linking the current Supabase-authenticated user to Telegram.

    This endpoint expects the Supabase access token in the `Authorization: Bearer <token>` header.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    access_token = authorization.replace("Bearer ", "").strip()
    supa_user = await _verify_supabase_token(access_token)
    supa_id = supa_user.get("id")
    if not supa_id:
        raise HTTPException(status_code=401, detail="Unable to determine Supabase user id")

    # Find or create a Grain user mapped to this Supabase user id
    try:
        grain_user = get_user_by_supabase_id(UUID(supa_id))
    except Exception:
        grain_user = None
    if not grain_user:
        display_name = None
        # Try to derive a display name from Supabase user metadata
        meta = supa_user.get("user_metadata") or {}
        display_name = meta.get("full_name") or meta.get("name") or supa_user.get("email") or "Supabase User"
        grain_user = create_user_from_supabase(UUID(supa_id), display_name=display_name)

    token = create_telegram_link_token(grain_user.id)
    return TelegramLinkTokenResponse(
        token=token,
        telegram_url=build_telegram_link_url(token),
        expires_in_minutes=10,
    )
