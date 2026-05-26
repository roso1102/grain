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
from app.services.relation_engine import build_relations_for_note
from app.services.enrichment_engine import try_enrich
from app.db.queries import insert_note
from app.db.supabase import supabase
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
        clean_input = raw_input.strip()
        
        # ── Route Telegram commands ──────────────────────────────────────
        if clean_input.startswith("/note") or clean_input.startswith("/edit") or \
           clean_input.startswith("/fact") or clean_input.startswith("/retitle") or \
           clean_input.startswith("/delete"):
            await _handle_note_command(chat_id, clean_input)
            return
        
        # Check if the input is a semantic search command
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
            core_line = parsed_data.get("core_claim", "")
            if core_line:
                core_line = core_line.replace("**", "").rstrip(".")
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
        
        # 5. Sync note to Obsidian
        try:
            from app.services.obsidian_sync import sync_note_to_obsidian
            await sync_note_to_obsidian(saved_note.id)
        except Exception as e:
            logger.error(f"Failed to sync note to Obsidian: {e}", exc_info=True)
            
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
        from app.services.obsidian_sync import make_shortcode
        shortcode = make_shortcode(saved_note.id)
        core_line = parsed_data.get("core_claim", "")
        facts_list = parsed_data.get("facts", [])
        why_line = parsed_data.get("why_matters")
        status_line = parsed_data.get("status")

        # Strip bold markers for Telegram plain text
        if core_line:
            core_line = core_line.replace("**", "").rstrip(".")
        if why_line:
            why_line = why_line.replace("**", "")

        reply = (
            f"🌾 *Grain Captured!*\n\n"
            f"📂 *Topic:* {snapped_topic_name}\n"
            f"🆔 *ID:* `{shortcode}`\n"
        )
        if core_line:
            reply += f"🔑 *Core:* {core_line}\n\n"
        if facts_list:
            for f in facts_list[:3]:
                text = f.replace("**", "")
                reply += f"• {text}\n"
            reply += "\n"
        if why_line:
            reply += f"💡 *Why This Matters:* {why_line}\n"
        if status_line:
            status_line = status_line.replace("**", "")
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

async def _handle_note_command(chat_id: int, text: str) -> None:
    """
    Handles Telegram commands for editing notes.
    /note <shortcode>           → Show note
    /edit <shortcode> <text>    → Replace raw_text, re-run LLM pipeline
    /fact <shortcode> <fact>    → Append a fact, regenerate summary
    /retitle <shortcode> <title>→ Update note title
    /delete <shortcode>         → Delete note
    """
    from app.services.obsidian_sync import make_shortcode, resolve_shortcode, \
        sync_note_to_obsidian, delete_note_from_obsidian
    from app.db.queries import get_note_by_id

    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        await send_message(chat_id, "⚠️ Usage: `/note <ID>` or `/edit <ID> <new text>` or `/fact <ID> <new fact>`")
        return

    cmd = parts[0].lower()
    shortcode = parts[1]
    note_id = resolve_shortcode(shortcode)

    if not note_id:
        await send_message(chat_id, f"❌ No note found with ID `{shortcode}`")
        return

    # ── /note — show note ────────────────────────────────────────────────
    if cmd == "/note":
        note = get_note_by_id(note_id)
        if not note:
            await send_message(chat_id, f"❌ Note `{shortcode}` not found.")
            return
        topic_res = supabase.table("topics").select("name").eq("id", str(note.topic_id)).execute()
        topic_name = topic_res.data[0]["name"] if topic_res.data else "General"

        # Parse summary for display
        core = ""
        facts = []
        status = ""
        for line in (note.summary or "").split("\n"):
            s = line.strip()
            if s.startswith("**Core:**"):
                core = s[len("**Core:**"):].strip().replace("**", "")
            elif s.startswith("•"):
                facts.append(s.lstrip("• ").strip().replace("**", ""))
            elif s.startswith("**Status:**"):
                status = s[len("**Status:**"):].strip().replace("**", "")

        reply = f"📂 *Topic:* {topic_name}\n🆔 *ID:* `{shortcode}`\n"
        if core:
            reply += f"🔑 *Core:* {core}\n"
        for f in facts[:3]:
            reply += f"• {f}\n"
        if status:
            reply += f"📊 *Status:* {status}\n"
        if note.source_url:
            reply += f"🔗 [Source]({note.source_url})\n"
        await send_message(chat_id, reply)
        return

    # ── /delete ──────────────────────────────────────────────────────────
    if cmd == "/delete":
        supabase.table("notes").delete().eq("id", str(note_id)).execute()
        await delete_note_from_obsidian(note_id)
        await send_message(chat_id, f"🗑️ Note `{shortcode}` deleted.")
        return

    # ── /retitle — just rename, no LLM ──────────────────────────────────
    if cmd == "/retitle":
        if len(parts) < 3:
            await send_message(chat_id, "⚠️ Usage: `/retitle <ID> <new title>`")
            return
        new_title = parts[2].strip()
        # The title isn't stored in DB — it's derived from **Core:**
        # Instead, we update the summary by replacing the **Core:** line
        note = get_note_by_id(note_id)
        if note and note.summary:
            new_summary = note.summary
            lines = note.summary.split("\n")
            for i, line in enumerate(lines):
                if line.strip().startswith("**Core:**"):
                    lines[i] = f"**Core:** {new_title}"
                    new_summary = "\n".join(lines)
                    break
            supabase.table("notes").update({"summary": new_summary}).eq("id", str(note_id)).execute()
            await sync_note_to_obsidian(note_id)
        await send_message(chat_id, f"✏️ Note `{shortcode}` retitled to: {new_title}")
        return

    # ── /fact — append a fact without re-running LLM ─────────────────────
    if cmd == "/fact":
        if len(parts) < 3:
            await send_message(chat_id, "⚠️ Usage: `/fact <ID> <new fact>`")
            return
        new_fact = parts[2].strip()
        note = get_note_by_id(note_id)
        if note and note.summary:
            # Append fact to the Facts section
            lines = note.summary.split("\n")
            inserted = False
            new_lines = []
            in_facts = False
            for line in lines:
                new_lines.append(line)
                if line.strip().startswith("**Facts:**"):
                    in_facts = True
                elif in_facts and line.strip().startswith("**") and not line.strip().startswith("**Facts:**"):
                    # Insert before the next section header
                    new_lines.insert(-1, f"• {new_fact}")
                    inserted = True
                    in_facts = False
            if not inserted:
                # Facts was the last section, append at end
                new_lines.append(f"• {new_fact}")
            supabase.table("notes").update({"summary": "\n".join(new_lines)}).eq("id", str(note_id)).execute()
            await sync_note_to_obsidian(note_id)
        await send_message(chat_id, f"✅ Fact added to `{shortcode}`")
        return

    # ── /edit — full re-process ──────────────────────────────────────────
    if cmd == "/edit" and len(parts) >= 3:
        new_text = parts[2].strip()
        # Re-run the full understand pipeline
        parsed_data = await understand(new_text)
        topic_name = parsed_data["topic_name"]
        topic_id, snapped_topic_name = await snap_topic(topic_name)
        note_embedding = embed(parsed_data["summary"])

        supabase.table("notes").update({
            "raw_text": parsed_data["raw_text"],
            "summary": parsed_data["summary"],
            "embedding": note_embedding,
            "source_url": parsed_data.get("source_url"),
            "source_type": parsed_data.get("source_type", "manual"),
            "topic_id": str(topic_id),
            "facets": parsed_data.get("facets") or {},
        }).eq("id", str(note_id)).execute()

        await sync_note_to_obsidian(note_id)
        await send_message(chat_id, f"✅ Note `{shortcode}` updated with new content.")
        return

    await send_message(chat_id, f"⚠️ Unknown command: {cmd}")

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
        
        # Sync note to Obsidian in background
        from app.services.obsidian_sync import sync_note_to_obsidian
        background_tasks.add_task(sync_note_to_obsidian, saved_note.id)
        
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
