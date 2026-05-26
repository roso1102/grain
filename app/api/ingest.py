import logging
from typing import Optional, Any
from fastapi import APIRouter, Request, BackgroundTasks
from pydantic import BaseModel

from app.core.logger import logger
from app.integrations.telegram import parse_webhook_update, send_message
from app.services.understand import understand
from app.services.topic_snapper import snap_topic
from app.services.embedder import embed
from app.services.retrieval_engine import search_notes
from app.services.notion_sync import sync_note_to_notion
from app.services.relation_engine import build_relations_for_note
from app.services.enrichment_engine import try_enrich
from app.db.queries import insert_note
from app.models.note import NoteInput

router = APIRouter(tags=["Ingestion"])

class ManualIngestRequest(BaseModel):
    text: str
    source_type: str = "manual"
    source_url: Optional[str] = None

async def process_telegram_ingestion(
    chat_id: int, 
    raw_input: str, 
    source_type: str, 
    file_id: Optional[str] = None
):
    """
    Background worker that runs the full ingestion pipeline:
    1. Parse & extract URL/insight/hints
    2. Scrape webpages if URL is present
    3. Generate summary & classify topic via LLM
    4. Save topic & note to Supabase DB
    5. Send summary/topic confirmation back to user
    """
    try:
        # Check if the input is a semantic search command
        clean_input = raw_input.strip()
        if clean_input.startswith("/ask"):
            query = clean_input[4:].strip()
            if not query:
                await send_message(chat_id, "⚠️ Please provide a query (e.g. `/ask FinFET vs GAAFET`)")
                return
                
            results = await search_notes(query, limit=3, threshold=0.2)
            if not results:
                await send_message(chat_id, f"🔍 No matching notes found for query: '{query}'")
                return
                
            reply = f"🔍 *Semantic Search Results for:* '{query}'\n\n"
            for idx, r in enumerate(results, start=1):
                reply += (
                    f"{idx}. *[{r.get('topic_name', 'General')}]* (Similarity: {r.get('similarity', 0.0):.2f})\n"
                    f"📝 {r['summary']}\n"
                )
                if r.get("personal_insight"):
                    reply += f"💡 _Insight:_ {r['personal_insight']}\n"
                if r.get("source_url"):
                    reply += f"🔗 [Link]({r['source_url']})\n"
                reply += "\n"
            await send_message(chat_id, reply)
            return

        logger.info(f"Processing Telegram note for chat_id={chat_id}")
        
        # 1. Run understand orchestrator
        parsed_data = await understand(raw_input)
        
        # 2. Snap topic to existing similar topic or create new one
        topic_name = parsed_data["topic_name"]
        topic_id, snapped_topic_name = await snap_topic(topic_name)
            
        # 3. Generate summary embedding
        note_embedding = embed(parsed_data["summary"])
            
        # 3a. Run enrichment check — merge if near-duplicate exists (sim >= 0.88)
        was_enriched, enriched_note_id = await try_enrich(
            new_raw_text=parsed_data["raw_text"],
            new_summary=parsed_data["summary"],
            new_embedding=note_embedding
        )

        if was_enriched and enriched_note_id:
            logger.info(f"Note merged into existing note {enriched_note_id} via enrichment.")
            # Grab Core line for compact enrichment reply
            summary_text = parsed_data["summary"]
            core_line = ""
            for sl in summary_text.split("\n"):
                sl_stripped = sl.strip()
                if sl_stripped.startswith("**Core:**"):
                    core_line = sl_stripped[len("**Core:**"):].strip().rstrip(".").replace("**", "")
                    break
            reply = (
                f"🌾 *Grain Enriched!*\n\n"
                f"Your note was merged into an existing capture on the same topic.\n"
                f"📂 *Topic:* {snapped_topic_name}\n"
            )
            if core_line:
                reply += f"🔑 *Core:* {core_line}\n"
            else:
                reply += f"📝 *Summary:* {parsed_data['summary'][:120]}\n"
            await send_message(chat_id, reply)
            return

        # 4. Insert note (no near-duplicate found)
        note_input = NoteInput(
            raw_text=parsed_data["raw_text"],
            summary=parsed_data["summary"],
            source_url=parsed_data["source_url"],
            source_type=parsed_data["source_type"] if source_type == "telegram_text" else source_type,
            personal_insight=parsed_data["personal_insight"],
            topic_id=topic_id,
            embedding=note_embedding,
            facets=parsed_data.get("facets") or {}
        )
        saved_note = insert_note(note_input)
        logger.info(f"Successfully saved note {saved_note.id} in Supabase.")
        
        # 5. Sync note to Notion
        try:
            await sync_note_to_notion(saved_note.id, custom_title=parsed_data.get("title"))
        except Exception as e:
            logger.error(f"Failed to sync note to Notion: {e}", exc_info=True)
            
        # 6. Extract key entities
        try:
            from app.db.queries import upsert_entity, link_note_to_entity
            from app.models.entity import EntityCreate
            
            entities = parsed_data.get("entities", [])
            for ent in entities:
                ent_name = ent.get("name")
                ent_type = ent.get("type")
                if ent_name and ent_type:
                    ent_emb = embed(ent_name)
                    entity_schema = upsert_entity(EntityCreate(name=ent_name, type=ent_type, embedding=ent_emb))
                    link_note_to_entity(saved_note.id, entity_schema.id)
                    logger.info(f"Linked entity '{ent_name}' to note {saved_note.id}.")
        except Exception as e:
            logger.error(f"Failed to extract/link entities: {e}", exc_info=True)

        # 6b. Build memory graph relations for this note
        try:
            edges = await build_relations_for_note(saved_note.id, parsed_data["summary"])
            if edges > 0:
                logger.info(f"Created {edges} relation edge(s) for note {saved_note.id}.")
        except Exception as e:
            logger.error(f"Failed to build memory graph relations: {e}", exc_info=True)

        # 7. Formulate response and reply to Telegram
        summary_text = parsed_data["summary"]
        # Show a compact version in Telegram — Core + Facts summary
        core_line = ""
        facts_lines = []
        status_line = ""
        for sl in summary_text.split("\n"):
            sl_stripped = sl.strip()
            if sl_stripped.startswith("**Core:**"):
                core_line = sl_stripped[len("**Core:**"):].strip().rstrip(".")
                # Remove bold markers for Telegram plain text
                core_line = core_line.replace("**", "")
            elif sl_stripped.startswith("•") or sl_stripped.startswith("-"):
                fact = sl_stripped.lstrip("•- ").strip().replace("**", "")
                if fact:
                    facts_lines.append(fact)
            elif sl_stripped.startswith("**Status:**"):
                status_line = sl_stripped[len("**Status:**"):].strip().replace("**", "")

        reply = (
            f"🌾 *Grain Captured!*\n\n"
            f"📂 *Topic:* {snapped_topic_name}\n"
        )
        if core_line:
            reply += f"🔑 *Core:* {core_line}\n\n"
        if facts_lines:
            for f in facts_lines[:3]:
                reply += f"• {f}\n"
            reply += "\n"
        if status_line:
            reply += f"📊 *Status:* {status_line}\n"
            
        await send_message(chat_id, reply)
        
    except Exception as e:
        logger.error(f"Error in ingestion pipeline: {e}", exc_info=True)
        await send_message(chat_id, f"❌ Failed to process capture: {str(e)}")

@router.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint that receives incoming messages from Telegram Bot Webhook.
    """
    try:
        payload = await request.json()
        chat_id, text, source_type, file_id = parse_webhook_update(payload)
        
        if chat_id is not None and text:
            # Delegate heavy lifting to background worker to prevent webhook timeouts
            background_tasks.add_task(
                process_telegram_ingestion,
                chat_id=chat_id,
                raw_input=text,
                source_type=source_type,
                file_id=file_id
            )
            
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook routing error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

async def process_entity_extraction_bg(note_id: Any, entities: list):
    """Background task to embed and store pre-extracted entities for manually ingested notes."""
    try:
        from app.db.queries import upsert_entity, link_note_to_entity
        from app.models.entity import EntityCreate
        
        for ent in entities:
            ent_name = ent.get("name")
            ent_type = ent.get("type")
            if ent_name and ent_type:
                ent_emb = embed(ent_name)
                entity_schema = upsert_entity(EntityCreate(name=ent_name, type=ent_type, embedding=ent_emb))
                link_note_to_entity(note_id, entity_schema.id)
    except Exception as e:
        logger.error(f"Failed background entity extraction for note {note_id}: {e}", exc_info=True)

@router.post("/ingest-note")
async def ingest_note(req: ManualIngestRequest, background_tasks: BackgroundTasks):
    """
    API endpoint to manually ingest a note without Telegram.
    """
    try:
        parsed_data = await understand(req.text)
        topic_name = parsed_data["topic_name"]
        
        # Snap topic
        topic_id, snapped_topic_name = await snap_topic(topic_name)
        
        # Generate summary embedding
        note_embedding = embed(parsed_data["summary"])
            
        note_input = NoteInput(
            raw_text=parsed_data["raw_text"],
            summary=parsed_data["summary"],
            source_url=req.source_url or parsed_data["source_url"],
            source_type=req.source_type,
            personal_insight=parsed_data["personal_insight"],
            topic_id=topic_id,
            embedding=note_embedding,
            facets=parsed_data.get("facets") or {}
        )
        
        # Enrichment check — merge if near-duplicate exists (sim >= 0.88)
        was_enriched, enriched_note_id = await try_enrich(
            new_raw_text=parsed_data["raw_text"],
            new_summary=parsed_data["summary"],
            new_embedding=note_embedding
        )

        if was_enriched and enriched_note_id:
            logger.info(f"Enrichment fired: merged into existing note {enriched_note_id}.")
            return {
                "status": "enriched",
                "note_id": str(enriched_note_id),
                "topic": snapped_topic_name,
                "summary": parsed_data["summary"],
                "personal_insight": parsed_data["personal_insight"],
                "enriched": True
            }

        saved_note = insert_note(note_input)
        
        # Sync note to Notion in background
        background_tasks.add_task(sync_note_to_notion, saved_note.id, parsed_data.get("title"))
        
        # Extract and link entities in background
        background_tasks.add_task(process_entity_extraction_bg, saved_note.id, parsed_data.get("entities", []))

        # Build memory graph relations in background
        background_tasks.add_task(build_relations_for_note, saved_note.id, parsed_data["summary"])
        
        return {
            "status": "success",
            "note_id": str(saved_note.id),
            "topic": snapped_topic_name,
            "summary": parsed_data["summary"],
            "personal_insight": parsed_data["personal_insight"]
        }
    except Exception as e:
        logger.error(f"Manual ingestion error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
