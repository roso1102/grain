import logging
from typing import List
import httpx
from app.core.config import settings

logger = logging.getLogger("grain.embedder")

URL = "https://generativelanguage.googleapis.com/v1/models/text-embedding-004:embedContent"


async def embed(text: str) -> List[float]:
    """
    Generates a 768-dimensional normalized embedding via Gemini's
    text-embedding-004 REST API.  Falls back to a zero vector on failure.
    """
    if not text or not text.strip():
        return [0.0] * 768

    try:
        payload = {
            "model": "models/text-embedding-004",
            "content": {"parts": [{"text": text}]},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                URL,
                json=payload,
                params={"key": settings.GEMINI_API_KEY},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return [float(v) for v in data["embedding"]["values"]]
    except Exception as e:
        logger.error(f"Gemini embedding failed: {e}")
        return [0.0] * 768
