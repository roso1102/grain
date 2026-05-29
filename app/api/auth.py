"""Supabase Auth JWT verification for the web dashboard."""
from typing import Optional
from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

from app.core.config import settings
from app.core.logger import logger
from app.db.users import get_user_by_id, create_telegram_link_token
from app.db.users import get_user_by_supabase_id

router = APIRouter(prefix="/auth", tags=["Auth"])


class TelegramLinkTokenResponse(BaseModel):
    token: str
    telegram_url: str
    expires_in_minutes: int


def build_telegram_link_url(token: str) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"


def verify_supabase_jwt(token: str) -> dict:
    """Decode a Supabase access token locally using the JWT secret.
    Returns the decoded payload (contains 'sub' = Supabase user UUID).
    """
    if not settings.SUPABASE_JWT_SECRET:
        raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET not configured")
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired, please log in again")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def _extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract the Bearer token from the Authorization header."""
    if not authorization:
        return ""
    return authorization.replace("Bearer ", "").strip()


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> UUID:
    """Dependency: verifies the Supabase access token and returns the Grain user UUID.
    Raises 401 if missing, invalid, or user not provisioned.
    """
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    payload = verify_supabase_jwt(token)
    supabase_user_id = payload.get("sub")
    if not supabase_user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    grain_user = get_user_by_supabase_id(UUID(supabase_user_id))
    if not grain_user:
        raise HTTPException(status_code=401, detail="User not provisioned")

    return grain_user.id


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
) -> Optional[UUID]:
    """Same as get_current_user but returns None instead of 401.
    Used for dual-auth endpoints that also accept X-User-Id header.
    """
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    try:
        payload = verify_supabase_jwt(token)
        supabase_user_id = payload.get("sub")
        if not supabase_user_id:
            return None
        grain_user = get_user_by_supabase_id(UUID(supabase_user_id))
        return grain_user.id if grain_user else None
    except HTTPException:
        return None


# ── Endpoints ────────────────────────────────────────────────────────────


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
    """Creates a one-time token for linking the current user's Telegram account.
    Requires a valid Supabase access token.
    """
    user_id = await get_current_user(authorization)
    token = create_telegram_link_token(user_id)
    return TelegramLinkTokenResponse(
        token=token,
        telegram_url=build_telegram_link_url(token),
        expires_in_minutes=10,
    )
