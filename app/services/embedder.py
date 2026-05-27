import logging
from typing import List
from google.genai import types
from app.integrations.gemini import gemini_client

logger = logging.getLogger("grain.embedder")

model_name = "text-embedding-004"


async def embed(text: str) -> List[float]:
    """
    Generates a 768-dimensional normalized embedding via Gemini's text-embedding-004 API.
    Falls back to a zero vector on failure.
    """
    if not text or not text.strip():
        return [0.0] * 384

    try:
        response = await gemini_client.aio.models.embed_content(
            model=model_name,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=384),
        )
        values = response.embeddings[0].values
        return [float(v) for v in values]
    except Exception as e:
        logger.error(f"Gemini embedding failed: {e}")
        return [0.0] * 384
