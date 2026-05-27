import logging
from typing import List, Optional
from uuid import UUID
from app.db.supabase import supabase
from app.models.note import NoteInput, NoteOutput
from app.models.topic import TopicCreate, TopicSchema
from app.models.entity import EntityCreate, EntitySchema

logger = logging.getLogger("grain.db.queries")

def insert_note(note: NoteInput) -> NoteOutput:
    """Inserts a new note into the Supabase database."""
    data = note.model_dump(mode="json", exclude_none=True)
    try:
        result = supabase.table("notes").insert(data).execute()
        if not result.data:
            raise Exception("Failed to insert note into Supabase")
        return NoteOutput(**result.data[0])
    except Exception as e:
        # Retry without columns that may not exist yet
        err_str = str(e).lower()
        popped = []
        for col in ("facets", "title"):
            if col in err_str and ("column" in err_str or "does not exist" in err_str):
                data.pop(col, None)
                popped.append(col)
        if popped:
            logger.warning(f"Columns {popped} don't exist yet. Retrying insert without them.")
            result = supabase.table("notes").insert(data).execute()
            if not result.data:
                raise Exception("Failed to insert note into Supabase")
            return NoteOutput(**result.data[0])
        raise e

def get_note_by_id(note_id: UUID, user_id: Optional[UUID] = None) -> Optional[NoteOutput]:
    """Retrieves a note by its UUID, optionally scoped to a user."""
    query = supabase.table("notes").select("*").eq("id", str(note_id))
    if user_id:
        query = query.eq("user_id", str(user_id))
    result = query.execute()
    if not result.data:
        return None
    return NoteOutput(**result.data[0])

def get_all_topics(user_id: Optional[UUID] = None) -> List[TopicSchema]:
    """Retrieves all topics from the database, optionally filtered by user."""
    query = supabase.table("topics").select("*")
    if user_id:
        query = query.eq("user_id", str(user_id))
    result = query.execute()
    return [TopicSchema(**row) for row in result.data]

def insert_topic(topic: TopicCreate) -> TopicSchema:
    """Inserts a new topic into the Supabase database."""
    data = topic.model_dump(mode="json", exclude_none=True)
    result = supabase.table("topics").insert(data).execute()
    if not result.data:
        raise Exception("Failed to insert topic into Supabase")
    return TopicSchema(**result.data[0])

def get_topic_by_name(name: str, user_id: Optional[UUID] = None) -> Optional[TopicSchema]:
    """Retrieves a topic by its name, optionally scoped to a user."""
    query = supabase.table("topics").select("*").eq("name", name)
    if user_id:
        query = query.eq("user_id", str(user_id))
    result = query.execute()
    if not result.data:
        return None
    return TopicSchema(**result.data[0])

def get_notes_by_topic_id(topic_id: UUID, user_id: Optional[UUID] = None, limit: int = 200) -> list:
    """Retrieves notes belonging to a specific topic, with their embeddings."""
    query = supabase.table("notes").select("id, embedding").eq("topic_id", str(topic_id))
    if user_id:
        query = query.eq("user_id", str(user_id))
    result = query.limit(limit).execute()
    return result.data or []

def upsert_entity(entity: EntityCreate) -> EntitySchema:
    """
    Checks if an entity with the same name already exists (optionally scoped by user).
    If yes, returns the existing entity.
    If no, inserts the new entity and returns it.
    """
    query = supabase.table("entities").select("*").eq("name", entity.name)
    if entity.user_id:
        query = query.eq("user_id", str(entity.user_id))
    result = query.execute()
    if result.data:
        return EntitySchema(**result.data[0])

    data = entity.model_dump(mode="json", exclude_none=True)
    insert_res = supabase.table("entities").insert(data).execute()
    if not insert_res.data:
        raise Exception(f"Failed to insert entity '{entity.name}' into Supabase")
    return EntitySchema(**insert_res.data[0])

def link_note_to_entity(
    note_id: UUID,
    entity_id: UUID,
    user_id: Optional[UUID] = None,
    confidence: float = 1.0
) -> None:
    """Links a note to an entity in the note_entities table."""
    data = {
        "note_id": str(note_id),
        "entity_id": str(entity_id),
        "confidence": confidence
    }
    if user_id:
        data["user_id"] = str(user_id)
    supabase.table("note_entities").upsert(data).execute()

def find_near_duplicate_note(
    embedding: List[float],
    threshold: float = 0.88,
    exclude_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None
) -> Optional[NoteOutput]:
    """
    Searches for an existing note whose embedding is above the given similarity
    threshold (default 0.88). Used by the enrichment engine to detect near-duplicates.

    Returns the most similar existing note, or None if no match found.
    """
    try:
        params = {
            "query_embedding": embedding,
            "match_threshold": threshold,
            "match_count": 2  # fetch 2 in case top result is the note itself
        }
        if user_id:
            params["p_user_id"] = str(user_id)
        response = supabase.rpc("match_notes", params).execute()

        matches = response.data or []
        for match in matches:
            if exclude_id and match["id"] == str(exclude_id):
                continue
            return get_note_by_id(UUID(match["id"]))
    except Exception:
        pass
    return None

def update_note_content(
    note_id: UUID,
    new_raw_text: str,
    new_summary: str,
    new_embedding: List[float]
) -> None:
    """
    Updates an existing note's raw_text, summary, and embedding in-place.
    Used when the enrichment engine merges a new note into an existing one.
    """
    supabase.table("notes").update({
        "raw_text": new_raw_text,
        "summary": new_summary,
        "embedding": new_embedding
    }).eq("id", str(note_id)).execute()

def log_enrichment(
    source_note_id: UUID,
    old_summary: str,
    new_summary: str,
    user_id: Optional[UUID] = None
) -> None:
    """
    Records a merge event in the enrichment_log table for audit/traceability.
    """
    data = {
        "source_note_id": str(source_note_id),
        "old_summary": old_summary,
        "new_summary": new_summary
    }
    if user_id:
        data["user_id"] = str(user_id)
    supabase.table("enrichment_log").insert(data).execute()
