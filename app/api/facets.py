import logging
from typing import Dict, List
from fastapi import APIRouter

from app.db.supabase import supabase

logger = logging.getLogger("grain.api.facets")
router = APIRouter(prefix="/facets", tags=["Facets"])


def _collect_facet(key: str, value: str, acc: Dict[str, List[str]], is_list: bool = True):
    """Recursively collect facet values from Supabase's JSONB representation."""
    if is_list:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item and item not in acc.get(key, []):
                    acc.setdefault(key, []).append(item)
    else:
        # Handle scalar facets (non-list) — currently all facets are list-based
        pass


@router.get("")
async def get_facets():
    """
    GET /facets

    Aggregates all unique facet values across all notes.
    Returns a map of facet key -> sorted list of unique values.

    Example:
    {
        "location": ["Nova Scotia", "Malignant Cove", "Japan", "Tokyo"],
        "subject": ["Geology", "Law", "Machine Learning"],
        "category": ["Science", "Technology"]
    }
    """
    try:
        result = supabase.table("notes").select("facets").execute()
        rows = result.data or []

        # Merge facets from all notes
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

        # Sort each list for consistent display
        for key in merged:
            merged[key].sort()

        return merged
    except Exception as e:
        logger.warning(f"Failed to fetch facets: {e}")
        # Column may not exist yet — migration might need to be run
        return {}
