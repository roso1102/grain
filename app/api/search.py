from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from uuid import UUID

from app.api.auth import get_current_user_optional
from app.services.retrieval_engine import search_notes
from app.utils.ranking import rank_search_results
from app.db.users import get_user_by_id

router = APIRouter(prefix="/search", tags=["Search"])

class SearchRequest(BaseModel):
    query: str
    limit: int = 5
    threshold: float = 0.3

class SearchResult(BaseModel):
    id: str
    raw_text: Optional[str] = None
    summary: str
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    personal_insight: Optional[str] = None
    topic_id: str
    topic_name: Optional[str] = None
    similarity: float
    matched_via: Optional[str] = None


async def _resolve_user_id(x_user_id: Optional[str] = Header(None)) -> Optional[UUID]:
    """Resolves X-User-Id header to a UUID, or returns None if absent/invalid."""
    if not x_user_id:
        return None
    try:
        user = get_user_by_id(UUID(x_user_id))
        if user:
            return user.id
    except Exception:
        pass
    return None


@router.post("", response_model=List[SearchResult])
async def semantic_search(
    req: SearchRequest,
    header_user_id: Optional[UUID] = Depends(_resolve_user_id),
    session_user_id: Optional[UUID] = Depends(get_current_user_optional),
):
    """
    API endpoint that performs semantic vector search on captured knowledge.
    Auth via session JWT (dashboard) or X-User-Id header (REST API).
    """
    user_id = session_user_id or header_user_id
    try:
        raw_results = await search_notes(
            req.query, 
            limit=req.limit, 
            threshold=req.threshold,
            user_id=user_id,
        )
        ranked = rank_search_results(raw_results)
        
        results = []
        for r in ranked:
            results.append(SearchResult(
                id=str(r["id"]),
                raw_text=r.get("raw_text"),
                summary=r.get("summary") or "",
                source_url=r.get("source_url"),
                source_type=r.get("source_type"),
                personal_insight=r.get("personal_insight"),
                topic_id=str(r["topic_id"]) if r.get("topic_id") else "",
                topic_name=r.get("topic_name") or "General",
                similarity=r.get("similarity", 0.0),
                matched_via=r.get("matched_via")
            ))
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
