import json
import logging
from typing import Dict, Optional
from app.integrations.gemini import call_llm

logger = logging.getLogger("grain.intent_parser")

async def parse_intent(raw_text: str) -> Dict[str, Optional[str]]:
    """
    Parses the user's message to extract:
    - route_hint: E.g. "save to VLSI" -> "VLSI"
    - personal_insight: E.g. "this is super cool" -> "this is super cool"
    
    Returns:
        A dict: {"route_hint": str | None, "personal_insight": str | None}
    """
    if not raw_text or not raw_text.strip():
        return {"route_hint": None, "personal_insight": None}

    prompt = (
        "You are an intent parser for a personal knowledge operating system.\n"
        "Analyze the user message and extract:\n"
        "1. 'route_hint': If the user explicitly specifies a category, topic or directory to save the note to "
        "(e.g., 'save to VLSI', 'put in EV batteries', 'VLSI', 'topic: VLSI'), extract the target topic name. Otherwise, null.\n"
        "2. 'personal_insight': If the user adds their own comment, reflection, or note alongside a link or main text "
        "(e.g., 'this looks super useful for my VLSI exam', 'I should use this in Gate prep'), extract that personal annotation. Otherwise, null.\n\n"
        f"User Message:\n{raw_text}\n\n"
        "Return ONLY a valid JSON object with keys 'route_hint' and 'personal_insight'. "
        "Do not include any formatting, markdown blocks, or other text. Example:\n"
        '{"route_hint": "VLSI", "personal_insight": "Review for exam."}'
    )
    try:
        response = await call_llm(prompt)
        clean_response = response.strip()
        # Remove any potential code block wrapper
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:]
        elif clean_response.startswith("```"):
            clean_response = clean_response[3:]
        if clean_response.endswith("```"):
            clean_response = clean_response[:-3]
        clean_response = clean_response.strip()

        data = json.loads(clean_response)
        return {
            "route_hint": data.get("route_hint"),
            "personal_insight": data.get("personal_insight")
        }
    except Exception as e:
        logger.error(f"Failed to parse intent: {e}")
        return {"route_hint": None, "personal_insight": None}
