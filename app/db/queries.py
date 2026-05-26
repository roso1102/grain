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
        # Check if the error is about a missing "facets" column
        err_str = str(e).lower()
        if "facets" in err_str and ("column" in err_str or "does not exist" in err_str):
            logger.warning("facets column does not exist yet. Retrying insert without facets.")
            data.pop("facets", None)
            result = supabase.table("notes").insert(data).execute()
            if not result.data:
                raise Exception("Failed to insert note into Supabase")
            return NoteOutput(**result.data[0])
        raise e

def get_note_by_id(note_id: UUID) -> Optional[NoteOutput]:
    """Retrieves a note by its UUID."""
    result = supabase.table("notes").select("*").eq("id", str(note_id)).execute()
    if not result.data:
        return None
    return NoteOutput(**result.data[0])

def get_all_topics() -> List[TopicSchema]:
    """Retrieves all topics from the database."""
    result = supabase.table("topics").select("*").execute()
    return [TopicSchema(**row) for row in result.data]

def insert_topic(topic: TopicCreate) -> TopicSchema:
    """Inserts a new topic into the Supabase database."""
    data = topic.model_dump(mode="json", exclude_none=True)
    result = supabase.table("topics").insert(data).execute()
    if not result.data:
        raise Exception("Failed to insert topic into Supabase")
    return TopicSchema(**result.data[0])

def get_topic_by_name(name: str) -> Optional[TopicSchema]:
    """Retrieves a topic by its unique name."""
    result = supabase.table("topics").select("*").eq("name", name).execute()
    if not result.data:
        return None
    return TopicSchema(**result.data[0])

def update_topic_notion_page(topic_id: UUID, notion_page_id: str) -> None:
    """Updates a topic's associated Notion page ID."""
    supabase.table("topics").update({"notion_page_id": notion_page_id}).eq("id", str(topic_id)).execute()

def update_note_notion_fields(note_id: UUID, notion_page_id: str, notion_block_id: str, notion_last_edited: str) -> None:
    """Updates the Notion sync tracking fields on a note."""
    supabase.table("notes").update({
        "notion_page_id": notion_page_id,
        "notion_block_id": notion_block_id,
        "notion_last_edited": notion_last_edited
    }).eq("id", str(note_id)).execute()

def get_syncable_notes() -> List[NoteOutput]:
    """Retrieves all notes that have been successfully synced to Notion."""
    result = supabase.table("notes").select("*").not_.is_("notion_block_id", "null").execute()
    return [NoteOutput(**row) for row in result.data]

def update_note_raw_text(note_id: UUID, raw_text: str, last_edited: str) -> None:
    """Updates a note's raw text and syncs the updated Notion last_edited timestamp."""
    supabase.table("notes").update({
        "raw_text": raw_text,
        "notion_last_edited": last_edited
    }).eq("id", str(note_id)).execute()

def upsert_entity(entity: EntityCreate) -> EntitySchema:
    """
    Checks if an entity with the same name already exists in the database.
    If yes, returns the existing entity.
    If no, inserts the new entity and returns it.
    """
    result = supabase.table("entities").select("*").eq("name", entity.name).execute()
    if result.data:
        return EntitySchema(**result.data[0])
        
    data = entity.model_dump(mode="json", exclude_none=True)
    insert_res = supabase.table("entities").insert(data).execute()
    if not insert_res.data:
        raise Exception(f"Failed to insert entity '{entity.name}' into Supabase")
    return EntitySchema(**insert_res.data[0])

def link_note_to_entity(note_id: UUID, entity_id: UUID, confidence: float = 1.0) -> None:
    """Links a note to an entity in the note_entities table."""
    supabase.table("note_entities").upsert({
        "note_id": str(note_id),
        "entity_id": str(entity_id),
        "confidence": confidence
    }).execute()

def find_near_duplicate_note(
    embedding: List[float],
    threshold: float = 0.88,
    exclude_id: Optional[UUID] = None
) -> Optional[NoteOutput]:
    """
    Searches for an existing note whose embedding is above the given similarity
    threshold (default 0.88). Used by the enrichment engine to detect near-duplicates.

    Returns the most similar existing note, or None if no match found.
    """
    try:
        response = supabase.rpc(
            "match_notes",
            {
                "query_embedding": embedding,
                "match_threshold": threshold,
                "match_count": 2  # fetch 2 in case top result is the note itself
            }
        ).execute()

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
    new_summary: str
) -> None:
    """
    Records a merge event in the enrichment_log table for audit/traceability.
    """
    supabase.table("enrichment_log").insert({
        "source_note_id": str(source_note_id),
        "old_summary": old_summary,
        "new_summary": new_summary
    }).execute()
