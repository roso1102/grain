import logging
from typing import Dict, Any, Optional, Tuple, List
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, \
    ReplyKeyboardMarkup, KeyboardButton, InlineQueryResultArticle, InputTextMessageContent
from app.core.config import settings

logger = logging.getLogger("grain.telegram")

# Initialize the Bot client
bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

def parse_webhook_update(payload: Dict[str, Any]) -> Tuple[Optional[int], Optional[str], str, Optional[str]]:
    """
    Parses a Telegram webhook payload.
    
    Returns:
        chat_id: The ID of the Telegram chat
        text: The text content or caption of the message
        source_type: 'telegram_text' | 'link' | 'pdf' | 'screenshot'
        file_id: The file ID if an attachment was sent
    """
    try:
        update = Update.de_json(payload, bot)
        if not update or not update.message:
            return None, None, "telegram_text", None

        message = update.message
        chat_id = message.chat_id
        text = message.text or message.caption or ""
        
        # Determine source type and extract optional file
        source_type = "telegram_text"
        file_id = None

        if message.document:
            mime = message.document.mime_type or ""
            source_type = "pdf" if "pdf" in mime.lower() else "document"
            file_id = message.document.file_id
        elif message.photo:
            source_type = "screenshot"
            # Get the largest image size available
            file_id = message.photo[-1].file_id
        elif "http://" in text or "https://" in text:
            source_type = "link"

        return chat_id, text, source_type, file_id

    except Exception as e:
        logger.error(f"Error parsing Telegram webhook update: {e}")
        return None, None, "telegram_text", None


async def send_draft(chat_id: int, draft_id: int, text: str) -> None:
    """Streams a partial message draft to the user (30s ephemeral preview)."""
    try:
        await bot.send_message_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            text=text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"sendMessageDraft failed: {e}")


async def send_message(chat_id: int, text: str) -> None:
    """Sends a final message back to the Telegram user."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error sending message to Telegram chat {chat_id}: {e}")


def login_keyboard() -> InlineKeyboardMarkup:
    """Returns an inline button that opens the dashboard login page."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Log in to Grain", url="https://higrain.vercel.app/login")],
    ])


# ── Chat Action (typing indicator) ───────────────────────────────────────────

async def send_typing(chat_id: int) -> None:
    """Shows a 'typing…' indicator instantly while the LLM processes."""
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception as e:
        logger.warning(f"send_chat_action failed: {e}")


# ── Reply Keyboard (persistent command menu) ─────────────────────────────────

def grain_keyboard() -> ReplyKeyboardMarkup:
    """Returns a persistent ReplyKeyboardMarkup with common commands."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("/help"), KeyboardButton("/recent"), KeyboardButton("/ask")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Send text or /help for commands…"
    )


# ── Inline Keyboards (buttons on messages) ───────────────────────────────────

def note_buttons(shortcode: str) -> InlineKeyboardMarkup:
    """Returns inline buttons for a note card."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 View", callback_data=f"note:{shortcode}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{shortcode}"),
        ],
        [
            InlineKeyboardButton("📂 Move", callback_data=f"move:{shortcode}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"delete:{shortcode}"),
        ],
    ])


async def send_note_card(chat_id: int, text: str, shortcode: str) -> None:
    """Sends a note card with inline action buttons. Falls back to plain text on failure."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=note_buttons(shortcode),
        )
    except Exception as e:
        logger.warning(f"Failed to send note card with buttons: {e}. Falling back to plain text.")
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception as e2:
            logger.error(f"Failed to send note card even without buttons: {e2}")


# ── Inline Mode (@grainbot <query>) ─────────────────────────────────────────

async def answer_inline_query(inline_query_id: str, results: List[Dict[str, Any]]) -> None:
    """Answers an inline query from @grainbot with search results."""
    articles = []
    for r in results[:10]:
        note_id = r.get("id", "")
        title = r.get("title") or r.get("display_name", "") or "Untitled"
        summary = (r.get("summary") or "")[:200]
        topic = r.get("topic_name", "General")

        articles.append(InlineQueryResultArticle(
            id=note_id,
            title=title[:64],
            description=f"[{topic}] {summary[:120]}",
            input_message_content=InputTextMessageContent(
                message_text=f"📂 *{topic}* — {summary[:300]}",
                parse_mode="Markdown",
            ),
        ))

    try:
        await bot.answer_inline_query(inline_query_id=inline_query_id, results=articles, cache_time=30)
    except Exception as e:
        logger.error(f"Error answering inline query: {e}")


class DraftStream:
    """Context manager that streams live progress drafts and sends the final message."""

    def __init__(self, chat_id: int, draft_id: int = 1):
        self.chat_id = chat_id
        self.draft_id = draft_id

    async def update(self, text: str) -> None:
        await send_draft(self.chat_id, self.draft_id, text)

    async def finish(self, text: str) -> None:
        """Persists the final message, replacing the ephemeral draft."""
        await send_message(self.chat_id, text)
