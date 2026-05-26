import logging
from app.integrations.gemini import call_llm

logger = logging.getLogger("grain.classifier")

async def classify_topic(raw_text: str, summary: str) -> str:
    """
    Classifies a note into a single, concise topic name (a short phrase, capitalized).
    
    Examples: "Machine Learning", "VLSI Design", "Japanese Language", "EV Batteries".
    """
    prompt = (
        "You are an expert knowledge base organizer. Classify the following note into "
        "a single, concise, capitalized topic name (1-3 words). "
        "Examples of topic names: 'Machine Learning', 'VLSI Design', 'Japanese Language', 'EV Batteries', 'GATE Prep'.\n\n"
        f"Raw Text:\n{raw_text}\n\n"
        f"Summary:\n{summary}\n\n"
        "Return ONLY the topic name. Do not include any quotes, preamble, formatting, or extra text."
    )
    try:
        topic_name = await call_llm(prompt, task="classify")
        # Clean up any potential markdown or punctuation formatting
        topic_name = topic_name.strip().strip('"').strip("'").strip(".")
        return topic_name if topic_name else "General"
    except Exception as e:
        logger.error(f"Failed to classify topic: {e}")
        # Try to extract a meaningful fallback topic from raw_text or summary
        if raw_text.startswith("Title:"):
            # Extract title line
            first_line = raw_text.split("\n")[0]
            title_content = first_line.replace("Title:", "").strip()
            # Split by common title separators
            for sep in ["|", "-", "—", ":"]:
                if sep in title_content:
                    candidate = title_content.split(sep)[0].strip()
                    if 2 < len(candidate) < 30:
                        return candidate.title()
            # If no separator or first part is too long, return first 3 words
            words = title_content.split()
            if words:
                return " ".join(words[:3]).title()
                
        # If plain text, extract first 2-3 words if possible
        words = [w for w in raw_text.split() if w.isalnum()]
        if words:
            candidate = " ".join(words[:3]).title()
            if len(candidate) > 2:
                return candidate
                
        return "General"
