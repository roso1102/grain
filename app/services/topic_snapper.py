import logging
from typing import Tuple
from uuid import UUID
from app.core.config import settings
from app.services.embedder import embed
from app.utils.similarity import cosine_similarity
from app.db.queries import get_all_topics, insert_topic
from app.models.topic import TopicCreate

logger = logging.getLogger("grain.topic_snapper")

async def snap_topic(proposed_name: str) -> Tuple[UUID, str]:
    """
    Checks if a topic with a similar semantic meaning already exists.
    If yes, returns the existing topic's ID and name.
    If no, creates a new topic with its generated embedding and returns its ID and name.
    """
    proposed_name_clean = proposed_name.strip()
    logger.info(f"Snapping topic: '{proposed_name_clean}'")
    
    # 1. Embed proposed topic name
    proposed_embedding = embed(proposed_name_clean)
    
    # 2. Get all existing topics
    try:
        existing_topics = get_all_topics()
    except Exception as e:
        logger.error(f"Error fetching topics from DB: {e}")
        existing_topics = []
        
    best_match_topic = None
    best_similarity = -1.0
    
    # 3. Compare proposed embedding with existing ones
    for topic in existing_topics:
        if topic.embedding:
            similarity = cosine_similarity(proposed_embedding, topic.embedding)
            logger.debug(f"Similarity with '{topic.name}': {similarity:.4f}")
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_topic = topic
                
    # 4. Check if max similarity exceeds threshold
    threshold = settings.TOPIC_SNAP_THRESHOLD
    if best_match_topic and best_similarity >= threshold:
        logger.info(
            f"Snapped proposed topic '{proposed_name_clean}' to existing topic "
            f"'{best_match_topic.name}' (similarity: {best_similarity:.4f} >= {threshold})"
        )
        return best_match_topic.id, best_match_topic.name
        
    # 5. Create new topic with embedding
    logger.info(
        f"No similar topic found (best similarity: {best_similarity:.4f} < {threshold}). "
        f"Creating new topic '{proposed_name_clean}'."
    )
    try:
        new_topic = insert_topic(TopicCreate(
            name=proposed_name_clean,
            description=f"Automated topic category for {proposed_name_clean}",
            embedding=proposed_embedding
        ))
        return new_topic.id, new_topic.name
    except Exception as e:
        logger.error(f"Failed to insert new topic '{proposed_name_clean}': {e}")
        # Fallback to get_topic_by_name to handle race conditions / unique constraint violations
        from app.db.queries import get_topic_by_name
        existing = get_topic_by_name(proposed_name_clean)
        if existing:
            return existing.id, existing.name
        raise e
