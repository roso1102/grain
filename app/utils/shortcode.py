import logging
from typing import Optional
from uuid import UUID

from app.db.supabase import supabase

logger = logging.getLogger("grain.shortcode")

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def make_shortcode(note_id: UUID) -> str:
    """Derives a 6-character base62 code from a UUID for easy reference."""
    val = int(str(note_id).replace("-", "")[:12], 16)
    code = []
    for _ in range(6):
        code.append(BASE62[val % 62])
        val //= 62
    return "".join(reversed(code))


def resolve_shortcode(code: str, user_id: Optional[UUID] = None) -> Optional[UUID]:
    """Resolves a shortcode back to a UUID by scanning notes."""
    try:
        query = supabase.table("notes").select("id")
        if user_id:
            query = query.eq("user_id", str(user_id))
        notes = query.execute()
        for row in (notes.data or []):
            if make_shortcode(UUID(row["id"])) == code:
                return UUID(row["id"])
    except Exception as e:
        logger.error(f"Failed to resolve shortcode {code}: {e}")
    return None
