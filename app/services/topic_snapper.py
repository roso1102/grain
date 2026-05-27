import logging
from typing import Tuple, Optional, List
from uuid import UUID
from app.core.config import settings
from app.services.embedder import embed
from app.services.topic_review import review_topic_merge
from app.utils.similarity import cosine_similarity
from app.db.queries import get_all_topics, insert_topic, get_notes_by_topic_id, get_topic_by_name
from app.models.topic import TopicCreate

logger = logging.getLogger("grain.topic_snapper")


def compute_topic_centroid(topic_id: UUID) -> Optional[List[float]]:
    """
    Computes the centroid embedding of all notes under a topic.
    Returns the averaged embedding vector, or None if no notes with embeddings exist.
    """
    notes = get_notes_by_topic_id(topic_id)
    embeddings = []
    for note in notes:
        emb = note.get("embedding")
        if emb:
            # Handle both list and string representations from Supabase
            if isinstance(emb, str):
                try:
                    emb = [float(x) for x in emb.strip("[]").split(",") if x.strip()]
                except (ValueError, AttributeError):
                    continue
            if isinstance(emb, list) and len(emb) > 0:
                embeddings.append(emb)

    if not embeddings:
        return None

    # Average the embeddings
    dim = len(embeddings[0])
    centroid = [0.0] * dim
    for emb in embeddings:
        for i in range(dim):
            centroid[i] += emb[i] / len(embeddings)
    return centroid


async def snap_topic(
    proposed_name: str,
    broader_topic: Optional[str] = None,
) -> Tuple[UUID, str]:
    """
    Checks if a topic with a similar semantic meaning already exists.
    If yes, returns the existing topic's ID and name.
    If no, creates a new topic with its generated embedding and returns its ID and name.

    When broader_topic is provided, the new/selected topic gets a parent_id pointing
    to the broader topic (found or created). When matching, prefers centroid-based
    similarity (from notes under the topic) over topic-name-only similarity.
    """
    proposed_name_clean = proposed_name.strip()
    logger.info(f"Snapping topic: '{proposed_name_clean}'")

    # ── Resolve broader_topic into a parent_id ──────────────────────────
    parent_id: Optional[UUID] = None
    if broader_topic and broader_topic.strip():
        bt_clean = broader_topic.strip()
        # Try to find existing broader topic
        parent_topic = get_topic_by_name(bt_clean)
        if parent_topic:
            parent_id = parent_topic.id
        else:
            # Embed and create the broader topic
            bt_emb = embed(bt_clean)
            try:
                new_parent = insert_topic(TopicCreate(
                    name=bt_clean,
                    description=f"Broad category for {bt_clean}",
                    embedding=bt_emb
                ))
                parent_id = new_parent.id
            except Exception as e:
                logger.warning(f"Failed to create broader topic '{bt_clean}': {e}")

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
        # Skip the topic we're trying to create (by name)
        if topic.name.lower() == proposed_name_clean.lower():
            return topic.id, topic.name

        # Prefer centroid-based comparison when possible
        candidate_embedding = None
        if topic.id:
            centroid = compute_topic_centroid(topic.id)
            if centroid:
                candidate_embedding = centroid

        # Fall back to topic-name embedding
        if candidate_embedding is None:
            candidate_embedding = topic.embedding

        if candidate_embedding:
            similarity = cosine_similarity(proposed_embedding, candidate_embedding)
            logger.debug(f"Similarity with '{topic.name}': {similarity:.4f}")
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_topic = topic

    # 4. Check if max similarity exceeds threshold
    threshold = settings.TOPIC_SNAP_THRESHOLD
    review_threshold = settings.TOPIC_REVIEW_THRESHOLD

    if best_match_topic and best_similarity >= threshold:
        logger.info(
            f"Snapped proposed topic '{proposed_name_clean}' to existing topic "
            f"'{best_match_topic.name}' (similarity: {best_similarity:.4f} >= {threshold})"
        )
        # Update parent_id if broader_topic was provided and topic exists
        if parent_id and best_match_topic.parent_id != parent_id:
            try:
                from app.db.supabase import supabase
                supabase.table("topics").update({"parent_id": str(parent_id)}).eq("id", str(best_match_topic.id)).execute()
                logger.info(f"Set parent_id={parent_id} on topic '{best_match_topic.name}'")
            except Exception as e:
                logger.warning(f"Failed to update parent_id: {e}")
        return best_match_topic.id, best_match_topic.name

    # 4b. Near-miss — LLM review zone
    if best_match_topic and best_similarity >= review_threshold:
        logger.info(
            f"Near-miss topic snap (sim={best_similarity:.4f} in [{review_threshold}, {threshold})). "
            f"Reviewing '{proposed_name_clean}' vs existing '{best_match_topic.name}'..."
        )
        try:
            review = await review_topic_merge(
                proposed_name=proposed_name_clean,
                existing_topic_name=best_match_topic.name,
                existing_topic_id=best_match_topic.id,
                similarity=best_similarity,
            )
            action = review.get("action", "separate")
            if action == "merge":
                logger.info(f"LLM review → MERGE: {review.get('reasoning')}")
                if parent_id and best_match_topic.parent_id != parent_id:
                    try:
                        from app.db.supabase import supabase
                        supabase.table("topics").update({"parent_id": str(parent_id)}).eq("id", str(best_match_topic.id)).execute()
                    except Exception as e:
                        logger.warning(f"Failed to update parent_id: {e}")
                return best_match_topic.id, best_match_topic.name
            elif action == "broader":
                logger.info(f"LLM review → BROADER: {review.get('reasoning')}")
                # Create new topic with the existing topic as its parent
                try:
                    new_topic = insert_topic(TopicCreate(
                        name=proposed_name_clean,
                        description=f"Automated topic subtopic under {best_match_topic.name}",
                        embedding=proposed_embedding,
                        parent_id=best_match_topic.id,
                    ))
                    return new_topic.id, new_topic.name
                except Exception as e:
                    logger.error(f"Failed to insert new topic '{proposed_name_clean}': {e}")
                    existing = get_topic_by_name(proposed_name_clean)
                    if existing:
                        return existing.id, existing.name
                    raise e
            else:
                logger.info(f"LLM review → SEPARATE: {review.get('reasoning')}. Creating new topic.")
        except Exception as e:
            logger.warning(f"Topic review failed ({e}), falling through to create new topic.")

    # 5. Create new topic with embedding
    logger.info(
        f"No similar topic found (best similarity: {best_similarity:.4f} < {threshold}). "
        f"Creating new topic '{proposed_name_clean}'."
    )
    try:
        new_topic = insert_topic(TopicCreate(
            name=proposed_name_clean,
            description=f"Automated topic category for {proposed_name_clean}",
            embedding=proposed_embedding,
            parent_id=parent_id,
        ))
        return new_topic.id, new_topic.name
    except Exception as e:
        logger.error(f"Failed to insert new topic '{proposed_name_clean}': {e}")
        existing = get_topic_by_name(proposed_name_clean)
        if existing:
            return existing.id, existing.name
        raise e
