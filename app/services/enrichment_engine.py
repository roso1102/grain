import logging
from typing import Optional, Tuple
from uuid import UUID
import json

from app.integrations.gemini import call_llm
from app.services.embedder import embed
from app.db.queries import (
    find_near_duplicate_note,
    update_note_content,
    log_enrichment,
)
from app.models.note import NoteOutput

logger = logging.getLogger("grain.enrichment_engine")

# Similarity threshold above which two notes are considered near-duplicates
# Calibrated from empirical similarity data: rephrased same-topic notes score 0.83–0.91
ENRICHMENT_THRESHOLD = 0.84


async def _merge_summaries(existing_summary: str, new_raw_text: str) -> str:
    """
    Asks Gemini to merge new information into the existing Knowledge Card.

    Returns the merged Knowledge Card string, or raises on failure.
    """
    prompt = (
        "You are a knowledge curator merging two overlapping pieces of information.\n\n"
        f"EXISTING KNOWLEDGE (Knowledge Card):\n{existing_summary}\n\n"
        f"NEW INFORMATION to incorporate:\n{new_raw_text}\n\n"
        "Extract and merge the new information into the existing Knowledge Card. "
        "Return ONLY a valid JSON object with these fields:\n"
        '{\n'
        '  "core_claim": "Merged single most important finding.",\n'
        '  "facts": ["Consolidated fact one.", "Consolidated fact two."],\n'
        '  "why_matters": "Updated relevance for the user.",\n'
        '  "status": "Established|Hypothesis|Debate|Speculative",\n'
        '  "links_to": "Entity A, Entity B"\n'
        '}\n\n'
        "Rules:\n"
        "- Bold key terms with **term** syntax.\n"
        "- Deduplicate facts — keep the best version.\n"
        "- If status or facts changed based on new info, update them.\n"
        "- Do NOT lose information from the existing knowledge.\n"
        "- No code blocks, no explanation. JSON only."
    )
    response = await call_llm(prompt, task="enrich")
    result = response.strip()
    # Strip code blocks if present
    if result.startswith("```json"):
        result = result[7:]
    elif result.startswith("```"):
        result = result[3:]
    if result.endswith("```"):
        result = result[:-3]
    result = result.strip()

    data = json.loads(result)

    # Assemble Knowledge Card string with guaranteed formatting
    parts = []
    if data.get("core_claim"):
        parts.append(f"**Core:** {data['core_claim']}")
    if data.get("facts"):
        parts.append("**Facts:**")
        for f in data["facts"]:
            parts.append(f"• {f}")
    if data.get("why_matters"):
        parts.append(f"**Why This Matters:** {data['why_matters']}")
    if data.get("status"):
        parts.append(f"**Status:** {data['status']}")
    if data.get("links_to"):
        parts.append(f"**Links To:** {data['links_to']}")
    return "\n".join(parts)


async def try_enrich(
    new_raw_text: str,
    new_summary: str,
    new_embedding: list,
    user_id: Optional[UUID] = None,
) -> Tuple[bool, Optional[UUID]]:
    """
    Phase 6 Enrichment Engine entry point.

    Before saving a new note, checks whether any existing note has a summary
    embedding similarity above ENRICHMENT_THRESHOLD (0.88).

    If a near-duplicate is found:
      - Sends both summaries to Gemini to produce a merged summary.
      - Updates the existing note's raw_text, summary, and embedding in-place.
      - Logs the merge to enrichment_log.
      - Returns (True, existing_note_id) — caller should NOT insert a new note.

    If no near-duplicate is found:
      - Returns (False, None) — caller should proceed with normal insertion.

    Fallback:
      - If LLM merge fails for any reason, returns (False, None) so the new
        note is saved normally.

    Args:
        new_raw_text:  The raw input text of the incoming note.
        new_summary:   The LLM-generated summary of the incoming note.
        new_embedding: The embedding vector of the incoming note's summary.

    Returns:
        (was_merged: bool, merged_into_note_id: Optional[UUID])
    """
    logger.info("Enrichment engine: checking for near-duplicate notes...")

    try:
        # 1. Search for an existing note above the similarity threshold
        existing_note: Optional[NoteOutput] = find_near_duplicate_note(
            embedding=new_embedding,
            threshold=ENRICHMENT_THRESHOLD,
            user_id=user_id
        )

        if not existing_note:
            logger.info(f"No near-duplicate found above threshold={ENRICHMENT_THRESHOLD}. Inserting new note.")
            return False, None

        logger.info(
            f"Near-duplicate detected! Existing note: {existing_note.id} "
            f"Summary preview: '{(existing_note.summary or '')[:60]}...'"
        )

        # 2. Ask LLM to merge
        merged_summary = await _merge_summaries(
            existing_summary=existing_note.summary or "",
            new_raw_text=new_raw_text
        )

        if not merged_summary or len(merged_summary.strip()) < 10:
            logger.warning("LLM merge produced empty/short output. Falling back to normal insertion.")
            return False, None

        # 3. Embed the merged summary
        merged_embedding = await embed(merged_summary)

        # 4. Construct merged raw_text (append new content to existing)
        merged_raw_text = (
            f"{existing_note.raw_text}\n\n---\n[Enriched on capture]\n{new_raw_text}"
        )

        # 5. Update the existing note in-place
        old_summary = existing_note.summary or ""
        update_note_content(
            note_id=existing_note.id,
            new_raw_text=merged_raw_text,
            new_summary=merged_summary,
            new_embedding=merged_embedding
        )
        logger.info(f"Updated existing note {existing_note.id} with merged content.")

        # 6. Log the enrichment event
        log_enrichment(
            source_note_id=existing_note.id,
            old_summary=old_summary,
            new_summary=merged_summary,
            user_id=user_id
        )
        logger.info(f"Enrichment merge logged for note {existing_note.id}.")

        return True, existing_note.id

    except Exception as e:
        logger.error(
            f"Enrichment engine failed unexpectedly: {e}. Falling back to normal insertion.",
            exc_info=True
        )
        return False, None
