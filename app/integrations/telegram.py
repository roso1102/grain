import logging
from typing import Dict, Any, Optional, Tuple
from telegram import Bot, Update
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

async def send_message(chat_id: int, text: str) -> None:
    """Sends a text message back to the Telegram user."""
    try:
        # Ensure we run this async against Telegram API
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error sending message to Telegram chat {chat_id}: {e}")
