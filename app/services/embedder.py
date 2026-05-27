import logging
from typing import List
import httpx
from app.core.config import settings

logger = logging.getLogger("grain.embedder")

DIM = 3072

URL = "https://generativelanguage.googleapis.com/v1/models/gemini-embedding-001:embedContent"


async def embed(text: str) -> List[float]:
    """
    Generates a 3072-dimensional normalized embedding via Geminis's
    gemini-embedding-001 REST API.  Falls back to a zero vector on failure.
    """
    if not text or not text.strip():
        return [0.0] * DIM

    try:
        payload = {
            "model": "models/gemini-embedding-001",
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
        return [0.0] * DIM
