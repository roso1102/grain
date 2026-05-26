import logging
from app.integrations.gemini import call_llm

logger = logging.getLogger("grain.summarizer")

async def summarize_text(raw_text: str) -> str:
    """
    Generates a 2-3 sentence summary of the provided text.
    """
    if not raw_text or not raw_text.strip():
        return ""
        
    prompt = (
        "You are an expert knowledge assistant. Summarize the following text "
        "in exactly 2 to 3 concise, informative sentences. "
        "Do not include any intro, outro, preamble, or conversational filler. "
        "Focus purely on the factual content and key ideas.\n\n"
        f"Text to summarize:\n{raw_text}\n\n"
        "Summary:"
    )
    try:
        summary = await call_llm(prompt)
        return summary
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        # Fallback to truncated text on failure
        words = raw_text.split()
        if len(words) > 30:
            return " ".join(words[:30]) + "..."
        return raw_text
