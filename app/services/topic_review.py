"""
Topic Review — LLM-based merge-or-keep decision for near-miss topic snaps.

When snap_topic() finds a similarity score between TOPIC_REVIEW_THRESHOLD and
TOPIC_SNAP_THRESHOLD, this module asks an LLM to make the final call:
  - merge: snap to the existing topic (score was conservative)
  - separate: create a new topic (they're genuinely different)
  - broader: merge but set the existing topic as the broader parent

This prevents false snaps from cosine-similarity edge cases while still
catching topics that are semantically the same but vector-distant.
"""

import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

from app.core.config import settings
from app.integrations.gemini import call_llm
from app.db.supabase import supabase
from app.db.queries import get_note_by_id

logger = logging.getLogger("grain.topic_review")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_sample_notes(topic_id: UUID, max_notes: int = 3) -> List[Dict[str, Any]]:
    """Fetches a small sample of notes under a topic for LLM context."""
    try:
        result = supabase.table("notes").select(
            "id, title, summary"
        ).eq("topic_id", str(topic_id)).limit(max_notes).execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"Failed to fetch sample notes for topic {topic_id}: {e}")
        return []


# ── Main review function ─────────────────────────────────────────────────────

async def review_topic_merge(
    proposed_name: str,
    existing_topic_name: str,
    existing_topic_id: UUID,
    similarity: float,
) -> Dict[str, Any]:
    """
    Asks the LLM to decide whether a proposed topic should merge into an
    existing topic, stay separate, or be reclassified under a broader parent.

    Args:
        proposed_name: The name of the new topic being proposed.
        existing_topic_name: The name of the near-miss existing topic.
        existing_topic_id: UUID of the existing topic.
        similarity: Cosine similarity between the two (0.0–1.0).

    Returns:
        dict with keys:
          - action: "merge" | "separate" | "broader"
          - reasoning: str — LLM's explanation
          - target_topic_name: str (same as existing_topic_name on merge/broader)
    """
    # Gather context — sample notes so the LLM can judge by content, not just name
    sample_notes = _get_sample_notes(existing_topic_id, max_notes=3)
    notes_context = ""
    if sample_notes:
        parts = []
        for n in sample_notes:
            title = n.get("title") or "Untitled"
            summary_snippet = (n.get("summary") or "")[:300]
            parts.append(f"- **{title}**\n  {summary_snippet}")
        notes_context = "Existing notes under this topic:\n" + "\n".join(parts)
    else:
        notes_context = "(No notes yet under this topic.)"

    prompt = (
        "You are a topic classification reviewer for a personal knowledge base.\n\n"
        f"A new note has been proposed under the topic **\"{proposed_name}\"**.\n"
        f"It is similar (cosine similarity={similarity:.2f}) to the existing topic "
        f"**\"{existing_topic_name}\"**.\n\n"
        f"{notes_context}\n\n"
        "Decide which action to take:\n"
        '  - "merge": The proposed topic means the same thing as the existing topic. '
        "Snap the note to the existing topic.\n"
        '  - "separate": The proposed topic is genuinely different. '
        "Create a new topic for it.\n"
        '  - "broader": The proposed topic is a subtopic of the existing topic. '
        'Set the existing topic as the parent (broader) and create the new topic.\n\n'
        "Return ONLY a JSON object with these fields:\n"
        "{\n"
        '  "action": "merge|separate|broader",\n'
        '  "reasoning": "Short explanation of why this decision was made."\n'
        "}"
    )

    try:
        response = await call_llm(prompt, task="classify")
        # Strip code fences if present
        clean = response.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        data = json.loads(clean)
        action = data.get("action", "separate")
        reasoning = data.get("reasoning", "")

        # Validate action
        if action not in ("merge", "separate", "broader"):
            logger.warning(f"LLM returned invalid action '{action}'. Defaulting to separate.")
            action = "separate"

        logger.info(
            f"Topic review: '{proposed_name}' vs '{existing_topic_name}' "
            f"(sim={similarity:.2f}) → {action}. Reasoning: {reasoning}"
        )

        return {
            "action": action,
            "reasoning": reasoning,
            "target_topic_name": existing_topic_name if action in ("merge", "broader") else None,
        }

    except Exception as e:
        logger.error(f"Topic review LLM call failed: {e}. Defaulting to separate.")
        return {
            "action": "separate",
            "reasoning": f"LLM review failed: {e}",
            "target_topic_name": None,
        }
