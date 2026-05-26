import logging
from typing import List, Dict, Any
from uuid import UUID
from app.db.supabase import supabase
from app.services.embedder import embed
from app.services.entity_extractor import extract_entities

logger = logging.getLogger("grain.retrieval_engine")


def _get_graph_expanded_notes(
    matched_ids: List[str],
    limit: int = 3
) -> List[Dict[str, Any]]:
    """
    Traverses the relations table to pull in 1-hop connected notes
    that are NOT already in the vector search results.

    Returns a list of note dicts with a 'relation_type' key added.
    """
    if not matched_ids:
        return []

    expanded = []
    seen_ids = set(matched_ids)

    for note_id in matched_ids:
        try:
            # Outbound edges
            out_res = supabase.table("relations")\
                .select("target_note_id, relation_type, score")\
                .eq("source_note_id", note_id)\
                .execute()
            # Inbound edges
            in_res = supabase.table("relations")\
                .select("source_note_id, relation_type, score")\
                .eq("target_note_id", note_id)\
                .execute()

            candidates = []
            for row in (out_res.data or []):
                candidates.append((row["target_note_id"], row["relation_type"], row["score"]))
            for row in (in_res.data or []):
                candidates.append((row["source_note_id"], row["relation_type"], row["score"]))

            for candidate_id, rel_type, score in candidates:
                if candidate_id not in seen_ids:
                    seen_ids.add(candidate_id)
                    # Fetch the note from Supabase
                    note_res = supabase.table("notes")\
                        .select("*")\
                        .eq("id", candidate_id)\
                        .single()\
                        .execute()
                    if note_res.data:
                        note = dict(note_res.data)
                        note["similarity"] = round(score * 0.9, 4)  # slight discount vs direct match
                        note["matched_via"] = f"graph:{rel_type}"
                        expanded.append(note)

                if len(expanded) >= limit:
                    break
            if len(expanded) >= limit:
                break
        except Exception as e:
            logger.warning(f"Graph expansion error for note {note_id}: {e}")

    return expanded


async def search_notes(
    query_text: str,
    limit: int = 5,
    threshold: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Performs semantic vector similarity search across all notes in Supabase,
    boosted by named entity overlap, then expanded with 1-hop memory graph neighbours.

    Returns:
        A list of note match dicts sorted by similarity score descending.
    """
    logger.info(f"Performing semantic search for query: '{query_text}'")
    try:
        # 1. Generate query embedding
        query_embedding = embed(query_text)

        # 2. Call pgvector RPC matching function
        response = supabase.rpc(
            "match_notes",
            {
                "query_embedding": query_embedding,
                "match_threshold": threshold,
                "match_count": limit
            }
        ).execute()

        results = response.data or []
        if not results:
            logger.info("No semantic search matches found.")
            return []

        logger.info(f"Retrieved {len(results)} semantic search results.")

        # 3. Entity Overlap Boosting
        try:
            query_entities = await extract_entities(query_text)
            query_entity_names = [e["name"].lower() for e in query_entities]

            if query_entity_names:
                logger.info(f"Extracted entities from query: {query_entity_names}")
                for note in results:
                    note_id = note["id"]
                    entities_res = supabase.table("note_entities")\
                        .select("entities(name)")\
                        .eq("note_id", str(note_id))\
                        .execute()

                    if entities_res.data:
                        note_entities = [
                            item["entities"]["name"].lower()
                            for item in entities_res.data
                            if item.get("entities")
                        ]
                        overlap = sum(1 for e in note_entities if e in query_entity_names)
                        if overlap > 0:
                            boost = 0.05 * overlap
                            note["similarity"] = note.get("similarity", 0.0) + boost
                            logger.info(f"Boosted note {note_id} by {boost:.2f} (entity overlap)")
        except Exception as ent_err:
            logger.error(f"Failed to apply entity overlap boosting: {ent_err}")

        # 4. Graph Expansion — pull in 1-hop related notes not already matched
        try:
            matched_ids = [r["id"] for r in results]
            graph_notes = _get_graph_expanded_notes(matched_ids, limit=3)
            if graph_notes:
                logger.info(f"Graph expansion added {len(graph_notes)} additional note(s).")
                results.extend(graph_notes)
        except Exception as graph_err:
            logger.error(f"Failed to apply graph expansion: {graph_err}")

        # 5. Sort by similarity descending
        results.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)

        return results
    except Exception as e:
        logger.error(f"Error executing match_notes RPC search: {e}", exc_info=True)
        return []

