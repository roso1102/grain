import logging
from typing import List
from sentence_transformers import SentenceTransformer
from app.core.config import settings

logger = logging.getLogger("grain.embedder")

logger.info(f"Initializing embedding model: {settings.EMBEDDING_MODEL_NAME}...")
try:
    # Load sentence transformer model onto memory (runs locally on CPU)
    model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
    logger.info("Embedding model loaded successfully.")
except Exception as e:
    logger.critical(f"Failed to load embedding model: {e}", exc_info=True)
    raise e

def embed(text: str) -> List[float]:
    """
    Generates a 384-dimensional normalized float list embedding for the input text.
    """
    if not text or not text.strip():
        return [0.0] * 384
    try:
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        return [0.0] * 384
