import logging
import time
from typing import Optional, Any
from uuid import UUID
from fastapi import APIRouter, Request, BackgroundTasks, Depends, Header
from pydantic import BaseModel

from app.core.logger import logger
from app.core.config import settings
from app.api.auth import get_current_user_optional
from app.integrations.telegram import parse_webhook_update, send_message
from app.services.understand import understand
from app.services.topic_snapper import snap_topic
from app.services.embedder import embed
from app.services.retrieval_engine import search_notes
from app.db.users import get_or_create_user_by_chat_id, get_user_by_id
from app.services.relation_engine import build_relations_for_note
from app.services.enrichment_engine import try_enrich
from app.db.queries import insert_note
from app.db.supabase import supabase
from app.models.note import NoteInput
from app.integrations.telegram import DraftStream, send_typing, grain_keyboard, send_note_card
from app.utils.similarity import normalize_similarity

router = APIRouter(tags=["Ingestion"])

class ManualIngestRequest(BaseModel):
    text: str
    source_type: str = "manual"
    source_url: Optional[str] = None

# ── Auth helper ───────────────────────────────────────────────────────────

async def resolve_user_id(x_user_id: Optional[str] = Header(None)) -> Optional[UUID]:
    """Resolves X-User-Id header to a UUID, or returns None if absent/invalid."""
    if not x_user_id:
        return None
    try:
        user = get_user_by_id(UUID(x_user_id))
        if user:
            return user.id
    except Exception:
        pass
    logger.warning(f"Invalid X-User-Id header: {x_user_id}")
    return None

async def process_telegram_ingestion(
    chat_id: int, 
    raw_input: str, 
    source_type: str, 
    file_id: Optional[str] = None,
    user_id: Optional[Any] = None,
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
        if clean_input == "/help" or clean_input == "/start" or \
           clean_input.startswith("/note") or clean_input.startswith("/edit") or \
           clean_input.startswith("/fact") or clean_input.startswith("/retitle") or \
           clean_input.startswith("/delete") or clean_input.startswith("/ask") or \
           clean_input.startswith("/status") or clean_input.startswith("/move") or \
           clean_input.startswith("/recent") or clean_input.startswith("/think"):
            await send_typing(chat_id)
            await _handle_note_command(chat_id, clean_input, user_id=user_id)
            return
        
        logger.info(f"Processing Telegram note for chat_id={chat_id}")
        t0 = time.time()
        await send_typing(chat_id)
        stream = DraftStream(chat_id, draft_id=1)
        await stream.update("🧠 Analyzing content...")

        # 1. Run understand orchestrator
        parsed_data = await understand(raw_input)
        logger.info(f"[TIMING] understand() took {time.time()-t0:.1f}s")

        # 2. Snap topic
        await stream.update(f"🏷️ Classifying topic...\n📂 *Topic:* {parsed_data.get('topic_name', '?')}")
        t1 = time.time()
        topic_name = parsed_data["topic_name"]
        broader_topic = parsed_data.get("broader_topic")
        topic_id, snapped_topic_name = await snap_topic(topic_name, broader_topic=broader_topic, user_id=user_id)
        logger.info(f"[TIMING] snap_topic() took {time.time()-t1:.1f}s")

        # 3. Generate embedding + enrichment
        await stream.update(f"📂 Topic: {snapped_topic_name}\n📝 Building summary...")
        t2 = time.time()
        note_embedding = await embed(parsed_data["summary"])
        logger.info(f"[TIMING] embed() took {time.time()-t2:.1f}s")

        t3 = time.time()
        was_enriched, enriched_note_id = await try_enrich(
            new_raw_text=parsed_data["raw_text"],
            new_summary=parsed_data["summary"],
            new_embedding=note_embedding,
            user_id=user_id
        )

        logger.info(f"[TIMING] try_enrich() took {time.time()-t3:.1f}s")

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
            await stream.finish(reply)
            logger.info(f"[TIMING] TOTAL enriched pipeline: {time.time()-t0:.1f}s")
            return

        # 4. Insert note (no near-duplicate found)
        t4 = time.time()
        note_input = NoteInput(
            raw_text=parsed_data["raw_text"],
            summary=parsed_data["summary"],
            title=parsed_data.get("title"),
            source_url=parsed_data["source_url"],
            source_type=parsed_data["source_type"] if source_type == "telegram_text" else source_type,
            personal_insight=parsed_data["personal_insight"],
            topic_id=topic_id,
            embedding=note_embedding,
            facets=parsed_data.get("facets") or {},
            user_id=user_id
        )
        saved_note = insert_note(note_input)
        logger.info(f"[TIMING] insert_note() took {time.time()-t4:.1f}s")

        # ── Build capture reply → send instantly (user sees result < 2s) ─
        from app.services.obsidian_sync import make_shortcode, _note_filename
        from urllib.parse import quote
        shortcode = make_shortcode(saved_note.id)
        core_line = parsed_data.get("core_claim", "")
        facts_list = parsed_data.get("facts", [])
        why_line = parsed_data.get("why_matters")
        status_line = parsed_data.get("status")
        title = parsed_data.get("title", "")

        # Build Obsidian deep link (as plain text — Telegram blocks obsidian:// in buttons)
        vault_name = settings.OBSIDIAN_VAULT_PATH.rstrip("/\\").split("\\")[-1].split("/")[-1]
        md_filename = _note_filename(snapped_topic_name, title or core_line or "Untitled")

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

        # Onboarding: track note count and guide on first captures
        note_count = _get_note_count(chat_id)
        _set_note_count(chat_id, note_count + 1)
        onboarding = ""
        if note_count == 0:
            onboarding = (
                "\n---\n☝️ *First capture!*\n"
                "You can `Edit`, `Move`, or `Delete` this note using the buttons above.\n"
                "Send `/help` to see all commands."
            )
        elif note_count == 1:
            onboarding = (
                "\n---\n🚀 *Second note!*\n"
                "Try `/ask solar` to search across your notes.\n"
                "Or type `@grainbot` in any chat to search inline."
            )
        elif note_count == 2:
            onboarding = (
                "\n---\n🎉 *Third note — you're on a roll!*\n"
                "You can `/move X Topic` to re-route any note.\n"
                "Or `/status X Hypothesis` to flag tentative ideas."
            )
        reply += onboarding

        # Add Obsidian link as plain text (clickable on mobile, copy-paste on desktop)
        reply += f"\n\n📄 `obsidian://open?vault={vault_name}&file=Grain/{quote(md_filename, safe='')}`"

        await send_note_card(chat_id, reply, shortcode)
        logger.info(f"[TIMING] Reply sent at {time.time()-t0:.1f}s — user gets instant feedback")

        # ── Background: syncing, entities, relations (user doesn't wait) ─
        t5 = time.time()
        try:
            from app.services.obsidian_sync import sync_note_to_obsidian
            await sync_note_to_obsidian(saved_note.id, user_id=user_id)
        except Exception as e:
            logger.error(f"Obsidian sync failed: {e}")
        logger.info(f"[TIMING] obsidian_sync() took {time.time()-t5:.1f}s (background)")

        t6 = time.time()
        try:
            from app.db.queries import upsert_entity, link_note_to_entity
            from app.models.entity import EntityCreate
            entities = parsed_data.get("entities", [])
            for ent in entities:
                ent_name = ent.get("name")
                ent_type = ent.get("type")
                if ent_name and ent_type:
                    ent_emb = await embed(ent_name)
                    entity_schema = upsert_entity(EntityCreate(name=ent_name, type=ent_type, embedding=ent_emb, user_id=user_id))
                    link_note_to_entity(saved_note.id, entity_schema.id, user_id=user_id)
        except Exception as e:
            logger.error(f"Entity linking failed: {e}")
        logger.info(f"[TIMING] entity extraction took {time.time()-t6:.1f}s (background)")

        t7 = time.time()
        try:
            edges = await build_relations_for_note(saved_note.id, parsed_data["summary"], user_id=user_id)
            if edges > 0:
                logger.info(f"Created {edges} relation edge(s).")
        except Exception as e:
            logger.error(f"Relation building failed: {e}")
        logger.info(f"[TIMING] relations took {time.time()-t7:.1f}s (background)")
        logger.info(f"[TIMING] TOTAL pipeline: {time.time()-t0:.1f}s (user saw reply at ~{t4-t0:.1f}s)")

    except Exception as e:
        logger.error(f"Error in ingestion pipeline: {e}", exc_info=True)
        await send_message(chat_id, f"❌ Failed to process capture: {str(e)}")

# ── Onboarding tracking (per-chat note count) ──────────────────────────────

def _get_note_count(chat_id: int) -> int:
    """Returns how many notes this chat has captured (used for onboarding)."""
    try:
        result = supabase.rpc("get_chat_note_count", {"p_chat_id": chat_id}).execute()
        if result.data is not None:
            return int(result.data)
    except Exception:
        pass
    # Fallback: count all notes (we don't track per-chat in notes table)
    try:
        result = supabase.table("notes").select("id", count="exact").execute()
        return result.count or 0
    except Exception:
        return 0


def _set_note_count(chat_id: int, count: int) -> None:
    """Updates the note count for a chat (best-effort, no-op if table doesn't exist)."""
    try:
        supabase.table("agent_state").upsert({
            "chat_id": chat_id,
            "note_count": count,
        }).execute()
    except Exception:
        pass


# ── Pending actions ─────────────────────────────────────────────────────────

_pending_actions: dict = {}


@router.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint that receives incoming messages from Telegram Bot Webhook.
    Handles messages, inline queries (@grainbot), and callback queries (button presses).
    """
    try:
        # ── Verify Telegram webhook secret (if configured) ──────────────
        if settings.TELEGRAM_WEBHOOK_SECRET:
            received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if received_secret != settings.TELEGRAM_WEBHOOK_SECRET:
                logger.warning("Webhook rejected: invalid X-Telegram-Bot-Api-Secret-Token")
                return {"status": "forbidden"}

        payload = await request.json()
        
        # ── Inline query (@grainbot <query>) ─────────────────────────────
        if "inline_query" in payload:
            iq = payload["inline_query"]
            query = (iq.get("query") or "").strip()
            iq_id = iq.get("id", "")
            if query and iq_id:
                from app.services.retrieval_engine import search_notes
                from app.integrations.telegram import answer_inline_query
                # Inline queries don't carry a chat_id; search without user scoping
                results = await search_notes(query, limit=5, threshold=0.2, user_id=None)
                await answer_inline_query(iq_id, results)
            return {"status": "ok"}
        
        # ── Check if this is a reply to a pending action prompt ──────────
        if "message" in payload and "text" in payload["message"]:
            chat_id = payload["message"]["chat"]["id"]
            text = payload["message"].get("text", "").strip()
            reply_to = payload["message"].get("reply_to_message")
            
            if chat_id in _pending_actions:
                pending = _pending_actions.pop(chat_id)
                action = pending["action"]
                shortcode = pending["shortcode"]
                
                if action == "edit":
                    full = f"/edit {shortcode} {text}"
                elif action == "move":
                    full = f"/move {shortcode} {text}"
                elif action == "delete":
                    if text.lower() in ("yes", "y", "confirm"):
                        full = f"/delete {shortcode}"
                    else:
                        await send_message(chat_id, "❌ Delete cancelled.")
                        return {"status": "ok"}
                else:
                    full = text
                
                await send_typing(chat_id)
                await _handle_note_command(chat_id, full)
                return {"status": "ok"}

        # ── Callback query (button press) ────────────────────────────────
        if "callback_query" in payload:
            cq = payload["callback_query"]
            data = cq.get("data", "")
            chat_id = cq["message"]["chat"]["id"]
            msg_id = cq["message"]["message_id"]

            from app.integrations.telegram import bot as tg_bot
            try:
                await tg_bot.answer_callback_query(callback_query_id=cq["id"])
            except Exception:
                pass

            parts = data.split(":", 1)
            if len(parts) == 2:
                action, shortcode = parts

                if action == "note":
                    await send_typing(chat_id)
                    await _handle_note_command(chat_id, f"/note {shortcode}")
                
                elif action == "edit":
                    _pending_actions[chat_id] = {"action": "edit", "shortcode": shortcode}
                    await tg_bot.send_message(
                        chat_id=chat_id,
                        text=f"✏️ Reply with the new content for `{shortcode}`:",
                        parse_mode="Markdown",
                    )
                
                elif action == "move":
                    _pending_actions[chat_id] = {"action": "move", "shortcode": shortcode}
                    await tg_bot.send_message(
                        chat_id=chat_id,
                        text=f"📂 Reply with the new topic name for `{shortcode}`:",
                        parse_mode="Markdown",
                    )
                
                elif action == "delete":
                    _pending_actions[chat_id] = {"action": "delete", "shortcode": shortcode}
                    await tg_bot.send_message(
                        chat_id=chat_id,
                        text=f"🗑️ Reply *yes* to delete `{shortcode}`:",
                        parse_mode="Markdown",
                    )

            return {"status": "ok"}
        
        # ── Regular message ──────────────────────────────────────────────
        chat_id, text, source_type, file_id = parse_webhook_update(payload)
        
        if chat_id is not None and text:
            # Phase 0: resolve user identity at webhook entry
            try:
                user = get_or_create_user_by_chat_id(chat_id)
                user_id = user.id
            except Exception as e:
                logger.warning(f"Failed to resolve user for chat_id {chat_id}: {e}")
                user_id = None

            background_tasks.add_task(
                process_telegram_ingestion,
                chat_id=chat_id,
                raw_input=text,
                source_type=source_type,
                file_id=file_id,
                user_id=user_id
            )
            
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook routing error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

async def _send_help(chat_id: int) -> None:
    """Sends a formatted list of all Telegram commands with reply keyboard."""
    from app.integrations.telegram import grain_keyboard
    help_text = (
        "🌾 *Grain PKOS Commands*\n\n"
        "*Capture a note*\n"
        "Just send any text or link → auto-saved\n\n"
        "*Commands*\n"
        "`/note <ID>` — Show a note\n"
        "`/ask <query>` — Semantic search across notes\n"
        "`/think <question>` — Ask complex questions, get connected answers with citations\n"
        "`/edit <ID> <text>` — Replace content, re-run LLM\n"
        "`/fact <ID> <text>` — Append a fact\n"
        "`/retitle <ID> <title>` — Change the title\n"
        "`/status <ID> <value>` — Set status (Established, Hypothesis, Debate, Speculative)\n"
        "`/move <ID> <topic>` — Change topic\n"
        "`/delete <ID>` — Delete note + Obsidian file\n"
        "`/recent [N]` — Show last N notes (default 10)\n"
        "`/help` — Show this message\n\n"
        "_Tip: shortcodes are 6-char IDs shown on capture_"
    )
    try:
        from app.integrations.telegram import bot as tg_bot
        await tg_bot.send_message(chat_id=chat_id, text=help_text, parse_mode="Markdown", reply_markup=grain_keyboard())
    except Exception as e:
        logger.warning(f"Failed to send help with keyboard: {e}")
        await send_message(chat_id, help_text)


async def _handle_ask_command(chat_id: int, query: str, user_id: Optional[UUID] = None) -> None:
    """Semantic search via LLM re-ranker, formatted for Telegram."""
    from app.services.retrieval_engine import search_notes
    from app.services.obsidian_sync import make_shortcode
    from uuid import UUID

    results = await search_notes(query, limit=5, threshold=0.2)
    if not results:
        await send_message(chat_id, f"🔍 No matching notes found for: '{query}'")
        return

    reply = f"🔍 *Search: {query}*\n\n"
    for idx, r in enumerate(results[:5], start=1):
        sim = normalize_similarity(r.get("similarity", 0.0))
        llm_score = r.get("llm_score")
        topic_name = r.get("topic_name", "General")
        summary = (r.get("summary") or "")[:300]
        source_url = r.get("source_url")
        via = r.get("matched_via", "")

        score_display = f"✨ LLM: {llm_score}/5 · " if llm_score else ""
        via_display = f" ({via})" if via else ""
        reply += f"{idx}. *[{topic_name}]* {score_display}Σ={sim:.2f}{via_display}\n"

        # Strip bold for Telegram's Markdown rendering
        core_line = summary.replace("**", "").split("\n")[0].strip()
        core_line = core_line.replace("Core:", "").strip() if core_line.startswith("Core:") else core_line[:80]
        reply += f"   📝 {core_line}\n"
        if source_url:
            reply += f"   🔗 [Source]({source_url})\n"
        reply += "\n"

    await send_message(chat_id, reply)


async def _handle_think_command(chat_id: int, question: str, user_id: Optional[UUID] = None) -> None:
    """Conversational recall: hybrid search + LLM synthesis, returns cited answer."""
    from app.services.recall_engine import recall_answer

    await send_typing(chat_id)
    result = await recall_answer(question, limit=8, user_id=user_id)
    answer = result["answer"]
    await send_message(chat_id, answer)


async def _handle_recent_command(chat_id: int, count: int, user_id: Optional[UUID] = None) -> None:
    from app.services.obsidian_sync import make_shortcode as mk_shortcode
    from uuid import UUID
    query = supabase.table("notes").select("id, title, created_at").order("created_at", desc=True).limit(count)
    if user_id:
        query = query.eq("user_id", str(user_id))
    notes_res = query.execute()
    note_rows = notes_res.data or []
    if not note_rows:
        await send_message(chat_id, "📭 No notes yet.")
        return
    reply = f"🕐 *Recent {len(note_rows)} Notes*\n\n"
    for row in note_rows:
        sc = mk_shortcode(UUID(row["id"]))
        title = (row.get("title") or "Untitled")[:60]
        reply += f"`{sc}` — {title}\n"
    try:
        from app.integrations.telegram import bot as tg_bot
        await tg_bot.send_message(chat_id=chat_id, text=reply, parse_mode="Markdown", reply_markup=grain_keyboard())
    except Exception:
        await send_message(chat_id, reply)


async def _handle_note_command(chat_id: int, text: str, user_id: Optional[UUID] = None) -> None:
    """
    Handles Telegram commands for editing notes.
    /note <shortcode>           → Show note
    /edit <shortcode> <text>    → Replace raw_text, re-run LLM pipeline
    /fact <shortcode> <fact>    → Append a fact, regenerate summary
    /retitle <shortcode> <title>→ Update note title
    /delete <shortcode>         → Delete note
    """
    from app.services.obsidian_sync import make_shortcode, resolve_shortcode, \
        sync_note_to_obsidian, delete_note_from_obsidian, _note_filename, vault_dir
    from app.db.queries import get_note_by_id

    # ── /ask — requires query, not shortcode ─────────────────────────────
    lower = text.lower().strip()
    if lower == "/help":
        await _send_help(chat_id)
        return
    if lower == "/start":
        # Personalized welcome screen
        user_info = None
        if user_id:
            try:
                user_info = get_user_by_id(user_id)
            except Exception:
                pass
        if user_info and user_info.display_name:
            welcome = (
                f"🌾 *Welcome to Grain, {user_info.display_name}!*\n\n"
                f"Your Personal Knowledge OS is ready.\n"
                f"🆔 Your ID: `{str(user_info.id)[:8]}...`\n\n"
                f"*Getting started:*\n"
                f"• Send any text or link — I'll capture and organize it\n"
                f"• Use `/ask <query>` to search your knowledge\n"
                f"• Use `/think <question>` for deep recall with citations\n"
                f"• Type `@grainbot <query>` in any chat for inline search\n\n"
                f"Send `/help` for all commands."
            )
        else:
            welcome = (
                f"🌾 *Welcome to Grain!*\n\n"
                f"Your Personal Knowledge OS is ready.\n\n"
                f"*Getting started:*\n"
                f"• Send any text or link — I'll capture and organize it\n"
                f"• Use `/ask <query>` to search your knowledge\n"
                f"• Use `/think <question>` for deep recall with citations\n\n"
                f"Send `/help` for all commands."
            )
        from app.integrations.telegram import bot as tg_bot
        try:
            await tg_bot.send_message(chat_id=chat_id, text=welcome, parse_mode="Markdown", reply_markup=grain_keyboard())
        except Exception as e:
            logger.warning(f"Failed to send welcome: {e}")
            await send_message(chat_id, welcome)
        return
    if lower.startswith("/ask "):
        query = text[4:].strip()
        if not query:
            await send_message(chat_id, "⚠️ Please provide a query (e.g. `/ask cuckoo bird`)")
            return
        await _handle_ask_command(chat_id, query)
        return
    if lower.startswith("/think "):
        query = text[6:].strip()
        if not query:
            await send_message(chat_id, "⚠️ Please provide a question (e.g. `/think How does ODAS relate to EV range?`)")
            return
        await _handle_think_command(chat_id, query)
        return
    if lower == "/recent" or lower.startswith("/recent "):
        parts_r = text.split(maxsplit=1)
        count = 10
        if len(parts_r) >= 2:
            try:
                count = int(parts_r[1])
            except ValueError:
                pass
        count = min(count, 30)
        await _handle_recent_command(chat_id, count)
        return

    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        await send_message(chat_id, "⚠️ Usage: `/note <ID>` or `/edit <ID> <new text>` or `/fact <ID> <new fact>`")
        return

    cmd = parts[0].lower()
    shortcode = parts[1]
    note_id = resolve_shortcode(shortcode, user_id=user_id)

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
        await send_note_card(chat_id, reply, shortcode)
        return

    # ── /delete ──────────────────────────────────────────────────────────
    if cmd == "/delete":
        supabase.table("notes").delete().eq("id", str(note_id)).execute()
        await delete_note_from_obsidian(note_id, user_id=user_id)
        await send_message(chat_id, f"🗑️ Note `{shortcode}` deleted.")
        return

    # ── /retitle — update title column ──────────────────────────────────
    if cmd == "/retitle":
        if len(parts) < 3:
            await send_message(chat_id, "⚠️ Usage: `/retitle <ID> <new title>`")
            return
        new_title = parts[2].strip()
        supabase.table("notes").update({"title": new_title}).eq("id", str(note_id)).execute()
        await sync_note_to_obsidian(note_id, user_id=user_id)
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
            await sync_note_to_obsidian(note_id, user_id=user_id)
        await send_message(chat_id, f"✅ Fact added to `{shortcode}`")
        return

    # ── /edit — full re-process ──────────────────────────────────────────
    if cmd == "/edit" and len(parts) >= 3:
        new_text = parts[2].strip()
        # Re-run the LLM pipeline
        parsed_data = await understand(new_text)
        note_embedding = await embed(parsed_data["summary"])

        # Preserve original topic ID — don't re-snap (edit = content change, not topic change)
        existing_note = get_note_by_id(note_id)
        original_topic_id = str(existing_note.topic_id) if existing_note and existing_note.topic_id else None
        original_title = existing_note.title if existing_note else ""

        # Delete the old .md file before re-syncing (title may have changed → different filename)
        if original_topic_id and original_title:
            try:
                t_res = supabase.table("topics").select("name").eq("id", original_topic_id).execute()
                old_topic_name = t_res.data[0]["name"] if t_res.data else "General"
                old_filename = _note_filename(old_topic_name, original_title)
                old_path = vault_dir() / old_filename
                if old_path.exists():
                    old_path.unlink()
                    logger.info(f"Deleted old file {old_filename} before edit re-sync")
            except Exception as e:
                logger.warning(f"Failed to delete old file before edit: {e}")

        update_data = {
            "raw_text": parsed_data["raw_text"],
            "summary": parsed_data["summary"],
            "title": parsed_data.get("title"),
            "embedding": note_embedding,
            "source_url": parsed_data.get("source_url"),
            "source_type": parsed_data.get("source_type", "manual"),
            "facets": parsed_data.get("facets") or {},
        }
        if original_topic_id:
            update_data["topic_id"] = original_topic_id

        supabase.table("notes").update(update_data).eq("id", str(note_id)).execute()

        await sync_note_to_obsidian(note_id, user_id=user_id)
        await send_message(chat_id, f"✅ Note `{shortcode}` updated with new content.")
        return

    # ── /status — change epistemic status ───────────────────────────────
    if cmd == "/status":
        if len(parts) < 3:
            await send_message(chat_id, "⚠️ Usage: `/status <ID> Established|Hypothesis|Debate|Speculative`")
            return
        new_status = parts[2].strip().capitalize()
        valid = {"Established", "Hypothesis", "Debate", "Speculative"}
        if new_status not in valid:
            await send_message(chat_id, f"⚠️ Invalid status. Use: {', '.join(valid)}")
            return
        note = get_note_by_id(note_id)
        if not note or not note.summary:
            await send_message(chat_id, f"❌ Note `{shortcode}` not found or has no summary.")
            return
        # Replace or append status line in summary
        lines = note.summary.split("\n")
        replaced = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("**Status:**"):
                new_lines.append(f"**Status:** {new_status}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"\n**Status:** {new_status}")
        supabase.table("notes").update({"summary": "\n".join(new_lines)}).eq("id", str(note_id)).execute()
        await sync_note_to_obsidian(note_id, user_id=user_id)
        await send_message(chat_id, f"📊 Status for `{shortcode}` set to: {new_status}")
        return

    # ── /move — change topic ────────────────────────────────────────────
    if cmd == "/move":
        if len(parts) < 3:
            await send_message(chat_id, "⚠️ Usage: `/move <ID> <new topic name>`")
            return
        new_topic = parts[2].strip()
        topic_id, snapped_name = await snap_topic(new_topic, user_id=user_id)
        supabase.table("notes").update({"topic_id": str(topic_id)}).eq("id", str(note_id)).execute()
        await sync_note_to_obsidian(note_id, user_id=user_id)
        await send_message(chat_id, f"📂 Note `{shortcode}` moved to topic: {snapped_name}")
        return

    # ── /recent — list recent notes (handled above)
    if cmd == "/recent":
        return

    await send_message(chat_id, f"⚠️ Unknown command: {cmd}")

async def process_entity_extraction_bg(note_id: Any, entities: list, user_id: Optional[UUID] = None):
    """Background task to embed and store pre-extracted entities for manually ingested notes."""
    try:
        from app.db.queries import upsert_entity, link_note_to_entity
        from app.models.entity import EntityCreate
        
        for ent in entities:
            ent_name = ent.get("name")
            ent_type = ent.get("type")
            if ent_name and ent_type:
                ent_emb = await embed(ent_name)
                entity_schema = upsert_entity(EntityCreate(name=ent_name, type=ent_type, embedding=ent_emb, user_id=user_id))
                link_note_to_entity(note_id, entity_schema.id, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed background entity extraction for note {note_id}: {e}", exc_info=True)

@router.post("/ingest-note")
async def ingest_note(
    req: ManualIngestRequest,
    background_tasks: BackgroundTasks,
    header_user_id: Optional[UUID] = Depends(resolve_user_id),
    session_user_id: Optional[UUID] = Depends(get_current_user_optional),
):
    """
    API endpoint to manually ingest a note without Telegram.
    Auth via session JWT (dashboard) or X-User-Id header (REST API).
    """
    user_id = session_user_id or header_user_id
    try:
        parsed_data = await understand(req.text)
        topic_name = parsed_data["topic_name"]
        
        # Snap topic
        topic_id, snapped_topic_name = await snap_topic(topic_name, user_id=user_id)
        
        # Generate summary embedding
        note_embedding = await embed(parsed_data["summary"])
            
        note_input = NoteInput(
            raw_text=parsed_data["raw_text"],
            summary=parsed_data["summary"],
            title=parsed_data.get("title"),
            source_url=req.source_url or parsed_data["source_url"],
            source_type=req.source_type,
            personal_insight=parsed_data["personal_insight"],
            topic_id=topic_id,
            embedding=note_embedding,
            facets=parsed_data.get("facets") or {},
            user_id=user_id
        )
        
        # Enrichment check — merge if near-duplicate exists (sim >= 0.88)
        was_enriched, enriched_note_id = await try_enrich(
            new_raw_text=parsed_data["raw_text"],
            new_summary=parsed_data["summary"],
            new_embedding=note_embedding,
            user_id=user_id
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
        background_tasks.add_task(sync_note_to_obsidian, saved_note.id, user_id)
        
        # Extract and link entities in background
        background_tasks.add_task(process_entity_extraction_bg, saved_note.id, parsed_data.get("entities", []), user_id)

        # Build memory graph relations in background
        background_tasks.add_task(build_relations_for_note, saved_note.id, parsed_data["summary"], user_id)
        
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
