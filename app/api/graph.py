import logging
from typing import List, Dict, Any
from uuid import UUID

from fastapi import APIRouter

from app.db.supabase import supabase
from app.db.queries import get_note_by_id

logger = logging.getLogger("grain.api.graph")
router = APIRouter(tags=["Memory Graph"])


def _fetch_related_note_ids(note_id: UUID) -> List[Dict[str, Any]]:
    """
    Fetches all 1-hop relation edges for a given note from the `relations` table.
    Returns edges where the note is either the source or the target.
    """
    note_id_str = str(note_id)

    # Edges where note is the source
    source_res = supabase.table("relations")\
        .select("target_note_id, relation_type, score")\
        .eq("source_note_id", note_id_str)\
        .execute()

    # Edges where note is the target (bidirectional lookup)
    target_res = supabase.table("relations")\
        .select("source_note_id, relation_type, score")\
        .eq("target_note_id", note_id_str)\
        .execute()

    edges = []
    for row in (source_res.data or []):
        edges.append({
            "related_note_id": row["target_note_id"],
            "relation_type": row["relation_type"],
            "score": row["score"],
            "direction": "outbound"
        })
    for row in (target_res.data or []):
        edges.append({
            "related_note_id": row["source_note_id"],
            "relation_type": row["relation_type"],
            "score": row["score"],
            "direction": "inbound"
        })
    return edges


@router.get("/related-notes/{note_id}")
async def get_related_notes(note_id: UUID):
    """
    GET /related-notes/{note_id}

    Traverses the memory graph to return all 1-hop related notes for a given note.
    Includes relation type, direction, and similarity score for each edge.

    Returns:
        A dict with the source note's summary and a list of related note objects.
    """
    logger.info(f"Fetching related notes for note_id={note_id}")

    # Verify source note exists
    source_note = get_note_by_id(note_id)
    if not source_note:
        return {"error": f"Note {note_id} not found.", "related_notes": []}

    # Fetch all relation edges
    edges = _fetch_related_note_ids(note_id)

    if not edges:
        return {
            "note_id": str(note_id),
            "source_summary": source_note.summary,
            "total_related": 0,
            "related_notes": []
        }

    # Enrich each edge with the related note's metadata
    related_notes = []
    for edge in edges:
        related_id = UUID(edge["related_note_id"])
        related_note = get_note_by_id(related_id)
        if related_note:
            related_notes.append({
                "note_id": str(related_note.id),
                "summary": related_note.summary,
                "topic_id": str(related_note.topic_id) if related_note.topic_id else None,
                "source_url": related_note.source_url,
                "relation_type": edge["relation_type"],
                "direction": edge["direction"],
                "score": edge["score"],
                "created_at": related_note.created_at.isoformat()
            })

    # Sort by score descending
    related_notes.sort(key=lambda x: x["score"], reverse=True)

    logger.info(f"Returning {len(related_notes)} related notes for {note_id}.")
    return {
        "note_id": str(note_id),
        "source_summary": source_note.summary,
        "total_related": len(related_notes),
        "related_notes": related_notes
    }
