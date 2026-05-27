"""Dashboard API endpoints for Grain web dashboard."""
import logging
from typing import List, Dict, Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.auth import get_current_user
from app.db.supabase import supabase
from app.db.queries import get_note_by_id

logger = logging.getLogger("grain.api.dashboard")
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ── Stats ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(user_id: UUID = Depends(get_current_user)):
    """Returns note count, topic count, entity count, and last capture time for the current user."""
    uid = str(user_id)

    note_count = supabase.table("notes").select("id", count="exact").eq("user_id", uid).execute().count or 0
    topic_count = supabase.table("topics").select("id", count="exact").eq("user_id", uid).execute().count or 0
    entity_count = supabase.table("entities").select("id", count="exact").eq("user_id", uid).execute().count or 0

    last_note = supabase.table("notes")\
        .select("created_at")\
        .eq("user_id", uid)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()

    last_capture_at = last_note.data[0]["created_at"] if last_note.data else None

    return {
        "note_count": note_count,
        "topic_count": topic_count,
        "entity_count": entity_count,
        "last_capture_at": last_capture_at,
    }


# ── Notes ─────────────────────────────────────────────────────────────────

@router.get("/notes")
async def list_notes(
    user_id: UUID = Depends(get_current_user),
    topic_id: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    facet_key: Optional[str] = Query(None),
    facet_value: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort: str = Query("created_at", pattern="^(created_at|title)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List notes for the current user with pagination and filters."""
    uid = str(user_id)

    # Resolve entity filtering first
    linked_ids = None
    if entity_id:
        linked = supabase.table("note_entities")\
            .select("note_id")\
            .eq("entity_id", entity_id)\
            .eq("user_id", uid)\
            .execute()
        linked_ids = [r["note_id"] for r in (linked.data or [])]
        if not linked_ids:
            return {"notes": [], "total": 0, "page": page, "per_page": per_page}

    # Build count query
    count_query = supabase.table("notes")\
        .select("id", count="exact")\
        .eq("user_id", uid)
    if topic_id:
        count_query = count_query.eq("topic_id", topic_id)
    if linked_ids:
        count_query = count_query.in_("id", linked_ids)
    if facet_key and facet_value:
        count_query = count_query.contains("facets", {facet_key: [facet_value]})
    if search:
        count_query = count_query.ilike("title", f"%{search}%")

    total = count_query.execute().count or 0

    # Build data query
    offset = (page - 1) * per_page
    is_desc = order == "desc"

    notes_query = supabase.table("notes")\
        .select("*")\
        .eq("user_id", uid)
    if topic_id:
        notes_query = notes_query.eq("topic_id", topic_id)
    if linked_ids:
        notes_query = notes_query.in_("id", linked_ids)
    if facet_key and facet_value:
        notes_query = notes_query.contains("facets", {facet_key: [facet_value]})
    if search:
        notes_query = notes_query.ilike("title", f"%{search}%")

    notes_res = notes_query\
        .order(sort, desc=is_desc)\
        .range(offset, offset + per_page - 1)\
        .execute()

    notes = []
    for row in (notes_res.data or []):
        notes.append({
            "id": row["id"],
            "title": row.get("title"),
            "summary": row.get("summary"),
            "source_url": row.get("source_url"),
            "source_type": row.get("source_type"),
            "topic_id": row.get("topic_id"),
            "facets": row.get("facets"),
            "created_at": row["created_at"],
        })

    return {"notes": notes, "total": total, "page": page, "per_page": per_page}


@router.get("/notes/{note_id}")
async def get_note_detail(
    note_id: UUID,
    user_id: UUID = Depends(get_current_user),
):
    """Returns a single note with full detail. Scoped to the current user."""
    note = get_note_by_id(note_id, user_id=user_id)
    if not note:
        return {"error": "Note not found"}

    # Fetch topic name
    topic_name = "General"
    if note.topic_id:
        t_res = supabase.table("topics")\
            .select("name")\
            .eq("id", str(note.topic_id))\
            .eq("user_id", str(user_id))\
            .execute()
        if t_res.data:
            topic_name = t_res.data[0]["name"]

    # Fetch linked entities
    entities_res = supabase.table("note_entities")\
        .select("entity_id, entities(name, type)")\
        .eq("note_id", str(note_id))\
        .eq("user_id", str(user_id))\
        .execute()

    entities = []
    for row in (entities_res.data or []):
        ent_data = row.get("entities") or {}
        entities.append({
            "id": row["entity_id"],
            "name": ent_data.get("name", "Unknown"),
            "type": ent_data.get("type", "concept"),
        })

    # Fetch backlinks (notes that have relations pointing TO this note)
    from app.api.graph import _fetch_related_note_ids
    edges = _fetch_related_note_ids(note_id, user_id=user_id)
    backlinks = []
    for edge in edges:
        backlinks.append({
            "note_id": edge["related_note_id"],
            "relation_type": edge["relation_type"],
            "direction": edge["direction"],
            "score": edge["score"],
        })

    return {
        "id": str(note.id),
        "raw_text": note.raw_text,
        "summary": note.summary,
        "title": note.title,
        "source_url": note.source_url,
        "source_type": note.source_type,
        "personal_insight": note.personal_insight,
        "topic_id": str(note.topic_id) if note.topic_id else None,
        "topic_name": topic_name,
        "facets": note.facets,
        "entities": entities,
        "backlinks": backlinks,
        "created_at": note.created_at.isoformat(),
    }


@router.get("/notes/{note_id}/entities")
async def get_note_entities(
    note_id: UUID,
    user_id: UUID = Depends(get_current_user),
):
    """Returns all entities linked to a note."""
    note = get_note_by_id(note_id, user_id=user_id)
    if not note:
        return {"error": "Note not found"}

    entities_res = supabase.table("note_entities")\
        .select("entity_id, entities(name, type)")\
        .eq("note_id", str(note_id))\
        .eq("user_id", str(user_id))\
        .execute()

    entities = []
    for row in (entities_res.data or []):
        ent_data = row.get("entities") or {}
        entities.append({
            "id": row["entity_id"],
            "name": ent_data.get("name", "Unknown"),
            "type": ent_data.get("type", "concept"),
        })

    return {"note_id": str(note_id), "entities": entities}


@router.put("/notes/{note_id}")
async def update_note(
    note_id: UUID,
    updates: Dict[str, Any],
    user_id: UUID = Depends(get_current_user),
):
    """Updates note fields (title, summary, topic_id, facets). Scoped to user."""
    note = get_note_by_id(note_id, user_id=user_id)
    if not note:
        return {"error": "Note not found"}

    allowed = {"title", "summary", "topic_id", "facets", "source_url", "source_type"}
    update_data = {k: v for k, v in updates.items() if k in allowed}
    if not update_data:
        return {"error": "No valid fields to update"}

    supabase.table("notes").update(update_data).eq("id", str(note_id)).eq("user_id", str(user_id)).execute()

    # Re-sync Obsidian
    try:
        from app.services.obsidian_sync import sync_note_to_obsidian
        await sync_note_to_obsidian(note_id, user_id=user_id)
    except Exception as e:
        logger.warning(f"Obsidian sync failed during dashboard update: {e}")

    return {"status": "updated", "note_id": str(note_id)}


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: UUID,
    user_id: UUID = Depends(get_current_user),
):
    """Deletes a note. Scoped to user."""
    note = get_note_by_id(note_id, user_id=user_id)
    if not note:
        return {"error": "Note not found"}

    supabase.table("notes").delete().eq("id", str(note_id)).eq("user_id", str(user_id)).execute()

    try:
        from app.services.obsidian_sync import delete_note_from_obsidian
        await delete_note_from_obsidian(note_id, user_id=user_id)
    except Exception as e:
        logger.warning(f"Obsidian delete failed during dashboard delete: {e}")

    return {"status": "deleted", "note_id": str(note_id)}


# ── Topics ────────────────────────────────────────────────────────────────

@router.get("/topics")
async def list_topics(user_id: UUID = Depends(get_current_user)):
    """Returns all topics for the current user with note counts."""
    uid = str(user_id)
    topics_res = supabase.table("topics")\
        .select("id, name, parent_id, description")\
        .eq("user_id", uid)\
        .order("name")\
        .execute()

    topics = []
    for row in (topics_res.data or []):
        note_count = supabase.table("notes")\
            .select("id", count="exact")\
            .eq("topic_id", row["id"])\
            .eq("user_id", uid)\
            .execute().count or 0

        topics.append({
            "id": row["id"],
            "name": row["name"],
            "parent_id": row.get("parent_id"),
            "description": row.get("description"),
            "note_count": note_count,
        })

    return topics


@router.get("/topics/{topic_id}/notes")
async def get_topic_notes(
    topic_id: UUID,
    user_id: UUID = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Returns notes under a specific topic."""
    uid = str(user_id)
    tid = str(topic_id)

    total = supabase.table("notes")\
        .select("id", count="exact")\
        .eq("topic_id", tid)\
        .eq("user_id", uid)\
        .execute().count or 0

    offset = (page - 1) * per_page
    notes_res = supabase.table("notes")\
        .select("id, title, summary, created_at")\
        .eq("topic_id", tid)\
        .eq("user_id", uid)\
        .order("created_at", desc=True)\
        .range(offset, offset + per_page - 1)\
        .execute()

    notes = []
    for row in (notes_res.data or []):
        notes.append({
            "id": row["id"],
            "title": row.get("title"),
            "summary": row.get("summary"),
            "created_at": row["created_at"],
        })

    return {"notes": notes, "total": total, "page": page, "per_page": per_page}


# ── Entities ──────────────────────────────────────────────────────────────

@router.get("/entities")
async def list_entities(user_id: UUID = Depends(get_current_user)):
    """Returns all entities for the current user with linked note counts."""
    uid = str(user_id)
    entities_res = supabase.table("entities")\
        .select("id, name, type")\
        .eq("user_id", uid)\
        .order("name")\
        .execute()

    entities = []
    for row in (entities_res.data or []):
        link_count = supabase.table("note_entities")\
            .select("note_id", count="exact")\
            .eq("entity_id", row["id"])\
            .eq("user_id", uid)\
            .execute().count or 0

        entities.append({
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "note_count": link_count,
        })

    return entities


@router.get("/entities/{entity_id}")
async def get_entity_detail(
    entity_id: UUID,
    user_id: UUID = Depends(get_current_user),
):
    """Returns entity detail with all linked notes."""
    uid = str(user_id)
    eid = str(entity_id)

    entity_res = supabase.table("entities")\
        .select("*")\
        .eq("id", eid)\
        .eq("user_id", uid)\
        .execute()

    if not entity_res.data:
        return {"error": "Entity not found"}

    entity = entity_res.data[0]

    # Get linked note IDs
    links_res = supabase.table("note_entities")\
        .select("note_id")\
        .eq("entity_id", eid)\
        .eq("user_id", uid)\
        .execute()

    note_ids = [r["note_id"] for r in (links_res.data or [])]

    notes = []
    if note_ids:
        notes_res = supabase.table("notes")\
            .select("id, title, summary, created_at")\
            .in_("id", note_ids)\
            .eq("user_id", uid)\
            .execute()

        for row in (notes_res.data or []):
            notes.append({
                "id": row["id"],
                "title": row.get("title"),
                "summary": row.get("summary"),
                "created_at": row["created_at"],
            })

    return {
        "id": entity["id"],
        "name": entity["name"],
        "type": entity["type"],
        "notes": notes,
    }


# ── Graph Data ────────────────────────────────────────────────────────────

@router.get("/graph-data")
async def get_graph_data(user_id: UUID = Depends(get_current_user)):
    """
    Returns all notes as nodes and all relations as links for force-directed graph.
    Scoped to the current user.
    """
    uid = str(user_id)

    # Get all notes for user (id, title, topic_id)
    notes_res = supabase.table("notes")\
        .select("id, title, topic_id")\
        .eq("user_id", uid)\
        .execute()

    # Get all relations for user
    relations_res = supabase.table("relations")\
        .select("source_note_id, target_note_id, relation_type, score")\
        .eq("user_id", uid)\
        .execute()

    # Get topic names for coloring nodes
    topic_ids = set()
    for row in (notes_res.data or []):
        if row.get("topic_id"):
            topic_ids.add(row["topic_id"])
    topic_names = {}
    if topic_ids:
        topics_res = supabase.table("topics")\
            .select("id, name")\
            .in_("id", list(topic_ids))\
            .execute()
        for row in (topics_res.data or []):
            topic_names[row["id"]] = row["name"]

    nodes = []
    note_ids = set()
    for row in (notes_res.data or []):
        note_ids.add(row["id"])
        nodes.append({
            "id": row["id"],
            "title": row.get("title") or "Untitled",
            "topic_name": topic_names.get(row.get("topic_id"), "General"),
            "topic_id": row.get("topic_id"),
        })

    links = []
    for row in (relations_res.data or []):
        # Only include links where both ends are in the user's notes
        if row["source_note_id"] in note_ids and row["target_note_id"] in note_ids:
            links.append({
                "source": row["source_note_id"],
                "target": row["target_note_id"],
                "relation_type": row["relation_type"],
                "score": row["score"],
            })

    return {"nodes": nodes, "links": links}
