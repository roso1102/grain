import logging
from typing import Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.db.supabase import supabase

logger = logging.getLogger("grain.api.facets")
router = APIRouter(prefix="/facets", tags=["Facets"])


@router.get("")
async def get_facets(user_id: UUID = Depends(get_current_user)):
    """
    GET /facets

    Aggregates all unique facet values across the current user's notes.
    Returns a map of facet key -> sorted list of unique values.

    Example:
    {
        "location": ["Nova Scotia", "Malignant Cove", "Japan", "Tokyo"],
        "subject": ["Geology", "Law", "Machine Learning"],
        "category": ["Science", "Technology"]
    }
    """
    try:
        result = supabase.table("notes").select("facets").eq("user_id", str(user_id)).execute()
        rows = result.data or []

        merged: Dict[str, List[str]] = {}
        for row in rows:
            facets = row.get("facets") or {}
            if not isinstance(facets, dict):
                continue
            for key, values in facets.items():
                if isinstance(values, list):
                    for v in values:
                        if isinstance(v, str) and v and v not in merged.setdefault(key, []):
                            merged[key].append(v)
                elif isinstance(values, str) and values and values not in merged.setdefault(key, []):
                    merged[key].append(values)

        for key in merged:
            merged[key].sort()

        return merged
    except Exception as e:
        logger.warning(f"Failed to fetch facets: {e}")
        return {}
