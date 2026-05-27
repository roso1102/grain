import logging
import json
from typing import List, Optional, Dict, Any
from uuid import UUID

from app.db.supabase import supabase
from app.services.embedder import embed
from app.integrations.gemini import call_llm
from app.models.relation import RelationCreate
from app.utils.similarity import normalize_similarity

logger = logging.getLogger("grain.relation_engine")

# Minimum cosine similarity before LLM is consulted about the relation type
RELATION_SIMILARITY_THRESHOLD = 0.75

# Allowed relation types (matching DB constraint)
VALID_RELATION_TYPES = {"related_to", "extends", "contradicts", "depends_on"}


def _insert_relation(source_id: UUID, target_id: UUID, relation_type: str, score: float, user_id: Optional[UUID] = None) -> None:
    """Inserts a single relation edge into the relations table."""
    data = {
        "source_note_id": str(source_id),
        "target_note_id": str(target_id),
        "relation_type": relation_type,
        "score": round(score, 4)
    }
    if user_id:
        data["user_id"] = str(user_id)
    supabase.table("relations").upsert(data).execute()


async def batch_classify_relations(source_summary: str, candidates: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Classifies relationships between the source note and multiple candidate notes in a single batch LLM call.
    
    Returns:
        Dict mapping candidate ID string to relation type ('extends', 'contradicts', 'depends_on', 'related_to').
    """
    if not candidates:
        return {}
        
    candidates_text = ""
    for idx, cand in enumerate(candidates, start=1):
        candidates_text += f"Candidate {idx} (ID: {cand['id']}): {cand.get('summary', '')}\n\n"
        
    prompt = (
        "You are a knowledge graph reasoning engine.\n"
        "Analyze the relationship between the Source Note and each of the Candidate Notes.\n\n"
        f"Source Note:\n{source_summary}\n\n"
        f"Candidate Notes:\n{candidates_text}\n"
        "For each Candidate Note, classify its relationship to the Source Note using one of these types:\n"
        "- 'extends': The Candidate Note builds upon, expands, or adds detail to the Source Note\n"
        "- 'contradicts': The Candidate Note conflicts with or disputes the Source Note\n"
        "- 'depends_on': The Candidate Note requires or is built upon concepts in the Source Note\n"
        "- 'related_to': The Candidate Note is related to the Source Note, but doesn't fit the above\n\n"
        "Return ONLY a valid JSON object mapping each Candidate ID string to its relation type. "
        "Do not include markdown blocks or any other explanation. Example output:\n"
        '{"uuid-1": "extends", "uuid-2": "related_to"}'
    )
    
    try:
        response = await call_llm(prompt, task="relations")
        clean_response = response.strip()
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:]
        elif clean_response.startswith("```"):
            clean_response = clean_response[3:]
        if clean_response.endswith("```"):
            clean_response = clean_response[:-3]
        clean_response = clean_response.strip()
        
        data = json.loads(clean_response)
        result = {}
        for cand in candidates:
            cand_id = cand["id"]
            rel = data.get(cand_id, "related_to").strip().lower()
            if rel not in VALID_RELATION_TYPES:
                rel = "related_to"
            result[cand_id] = rel
        return result
    except Exception as e:
        logger.error(f"Batch relation classification failed: {e}")
        # Fallback all to related_to
        return {cand["id"]: "related_to" for cand in candidates}


def get_top_similar_notes(
    note_id: UUID,
    note_embedding: List[float],
    limit: int = 5,
    threshold: float = RELATION_SIMILARITY_THRESHOLD,
    user_id: Optional[UUID] = None
) -> List[Dict[str, Any]]:
    """
    Finds the top-k most similar existing notes via pgvector ANN search,
    excluding the source note itself.
    """
    try:
        params = {
            "query_embedding": note_embedding,
            "match_threshold": threshold,
            "match_count": limit + 1  # +1 to account for the note itself
        }
        if user_id:
            params["p_user_id"] = str(user_id)
        response = supabase.rpc("match_notes", params).execute()

        results = response.data or []
        for r in results:
            r["similarity"] = normalize_similarity(r.get("similarity"))
        # Exclude the note we are comparing against
        return [r for r in results if r["id"] != str(note_id)][:limit]
    except Exception as e:
        logger.error(f"Failed to fetch similar notes for relation engine: {e}")
        return []


async def build_relations_for_note(note_id: UUID, summary: str, user_id: Optional[UUID] = None) -> int:
    """
    Core entry point of the relation engine.
    
    After a note is saved:
    1. Embeds the summary and searches for similar existing notes.
    2. For pairs with similarity > RELATION_SIMILARITY_THRESHOLD:
       - Asks Gemini in batch to classify the relation types.
       - Inserts the edges into the `relations` table.

    Args:
        note_id: UUID of the newly saved note.
        summary: The note's LLM-generated summary text.

    Returns:
        The number of new relation edges created.
    """
    logger.info(f"Building memory graph relations for note {note_id}...")
    
    if not summary or not summary.strip():
        logger.warning(f"Empty summary for note {note_id}, skipping relation building.")
        return 0

    # 1. Embed the summary
    note_embedding = await embed(summary)

    # 2. Find top similar notes above threshold
    similar_notes = get_top_similar_notes(note_id, note_embedding, user_id=user_id)

    if not similar_notes:
        logger.info(f"No similar notes found above threshold for note {note_id}.")
        return 0

    logger.info(f"Found {len(similar_notes)} candidates for relation edges.")
    edges_created = 0

    # 3. Batch classify relation types
    try:
        classifications = await batch_classify_relations(summary, similar_notes)
    except Exception as e:
        logger.error(f"Failed to batch classify relations: {e}")
        classifications = {cand["id"]: "related_to" for cand in similar_notes}

    # 4. Insert relation for each similar note
    for candidate in similar_notes:
        candidate_id = candidate["id"]
        similarity = candidate.get("similarity", 0.0)
        relation_type = classifications.get(candidate_id, "related_to")

        logger.info(
            f"Inserting classified relation: note {note_id} <-> {candidate_id} ({relation_type}, sim={similarity:.3f})"
        )

        _insert_relation(
            source_id=note_id,
            target_id=UUID(candidate_id),
            relation_type=relation_type,
            score=similarity,
            user_id=user_id
        )
        logger.info(f"Inserted relation '{relation_type}' between {note_id} and {candidate_id}.")
        edges_created += 1

    return edges_created
