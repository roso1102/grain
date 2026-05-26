import logging
from uuid import UUID
from datetime import datetime
from app.core.config import settings
from app.db.queries import (
    get_note_by_id,
    update_note_notion_fields,
    update_topic_notion_page,
    get_syncable_notes,
    update_note_raw_text
)
from app.db.supabase import supabase
from app.models.topic import TopicSchema
from app.integrations.notion import (
    create_page,
    create_note_subpage,
    get_block
)

logger = logging.getLogger("grain.notion_sync")


def _make_note_title(note) -> str:
    """
    Derives a clean, meaningful title for the per-note Notion sub-page.
    Uses the first sentence of the summary, trimmed to 60 chars.
    """
    summary = (note.summary or "").strip()
    # Remove any leading emoji/bullet
    for prefix in ["🌾", "📋", "•", "-", "*"]:
        summary = summary.lstrip(prefix).strip()

    # Use first sentence
    for sep in [".", "!", "?", "\n"]:
        idx = summary.find(sep)
        if 15 < idx < 80:
            return summary[:idx].strip()

    # Fallback: first 60 chars
    return summary[:60].strip() or f"Note ({str(note.id)[:8]})"


async def sync_note_to_notion(note_id: UUID, custom_title: Optional[str] = None) -> None:
    """
    Syncs a note to Notion with full rich formatting.

    Structure:
      Workspace Root
      └── Topic Page  (e.g. "Oncology")
          └── Note Sub-page  (e.g. "Turmeric has not been clinically proven...")
                - 📋 Summary  (heading + formatted paragraphs)
                - 🔗 Source   (bookmark block)
                - 💡 Insight  (callout, if present)
    """
    logger.info(f"Syncing note {note_id} to Notion...")

    # 1. Fetch note
    note = get_note_by_id(note_id)
    if not note:
        logger.error(f"Note {note_id} not found. Skipping sync.")
        return

    if not note.topic_id:
        logger.warning(f"Note {note_id} has no topic. Skipping sync.")
        return

    # 2. Fetch topic
    topic_res = supabase.table("topics").select("*").eq("id", str(note.topic_id)).execute()
    if not topic_res.data:
        logger.error(f"Topic {note.topic_id} not found. Skipping sync.")
        return
    topic = TopicSchema(**topic_res.data[0])

    # 3. Ensure topic-level page exists in Notion
    notion_page_id = topic.notion_page_id
    if not notion_page_id:
        logger.info(f"No Notion page for topic '{topic.name}'. Creating topic page...")
        try:
            notion_page_id = await create_page(settings.NOTION_WORKSPACE_ID, topic.name)
            update_topic_notion_page(topic.id, notion_page_id)
            logger.info(f"Created topic page '{topic.name}': {notion_page_id}")
        except Exception as e:
            logger.error(f"Failed to create topic page for '{topic.name}': {e}")
            return

    # 4. Create a new per-note sub-page with rich content blocks
    try:
        note_title = custom_title or _make_note_title(note)
        note_page_id, last_edited_time = await create_note_subpage(
            topic_page_id=notion_page_id,
            title=note_title,
            summary=note.summary or "",
            source_url=note.source_url,
            personal_insight=note.personal_insight,
            source_type=note.source_type or "manual"
        )
        logger.info(f"Created note sub-page '{note_title}' under topic '{topic.name}': {note_page_id}")

        # 5. Save tracking IDs back to Supabase
        update_note_notion_fields(note.id, note_page_id, note_page_id, last_edited_time)
        logger.info("Successfully saved Notion page reference to Supabase note.")

    except Exception as e:
        logger.error(f"Failed to create note sub-page: {e}", exc_info=True)


async def poll_notion_updates() -> None:
    """
    Background task that polls Notion for edits to synced blocks
    and writes them back to Supabase notes raw_text.
    """
    logger.info("Polling Notion for updates...")
    try:
        notes = get_syncable_notes()
        logger.info(f"Found {len(notes)} synced notes to check.")
    except Exception as e:
        logger.error(f"Failed to retrieve syncable notes from DB: {e}")
        return

    for note in notes:
        if not note.notion_block_id:
            continue

        try:
            # Fetch current block state from Notion
            notion_last_edited_str, notion_text = await get_block(note.notion_block_id)

            # Parse timestamps safely
            notion_time = datetime.fromisoformat(notion_last_edited_str.replace("Z", "+00:00"))
            supabase_time = note.notion_last_edited

            # Ensure timezone-aware comparison
            if supabase_time and supabase_time.tzinfo is None:
                supabase_time = supabase_time.replace(tzinfo=notion_time.tzinfo)

            # Check if Notion block was edited after last Supabase sync
            if supabase_time is None or notion_time > supabase_time:
                logger.info(
                    f"Detected Notion update on block {note.notion_block_id} "
                    f"(Notion: {notion_time} > Supabase: {supabase_time})"
                )
                cleaned_text = notion_text.strip()
                if cleaned_text.startswith("🌾"):
                    cleaned_text = cleaned_text[1:].strip()

                update_note_raw_text(note.id, cleaned_text, notion_last_edited_str)
                logger.info(f"Synced Notion edits back to note {note.id}.")

        except Exception as e:
            logger.error(f"Failed to poll update for block {note.notion_block_id}: {e}")
