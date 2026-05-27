import logging
from typing import List, Dict, Any
from uuid import UUID
from app.db.supabase import supabase
from app.services.embedder import embed
from app.services.entity_extractor import extract_entities
from app.integrations.gemini import call_llm
from app.utils.similarity import normalize_similarity

logger = logging.getLogger("grain.retrieval_engine")


def _get_graph_expanded_notes(
    matched_ids: List[str],
    limit: int = 3,
    user_id: Optional[UUID] = None
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


async def _llm_rerank(
    query: str,
    candidates: List[Dict[str, Any]],
    max_candidates: int = 10
) -> List[Dict[str, Any]]:
    """
    LLM-based re-ranker that acts as a zero-shot cross-encoder.
    Takes top-N cosine candidates and asks the LLM to score relevance 0-5,
    then re-sorts by the combined score.
    """
    if not candidates or len(candidates) <= 1:
        return candidates

    top_n = candidates[:max_candidates]
    if len(top_n) <= 1:
        return candidates

    candidates_text = ""
    for idx, c in enumerate(top_n, start=1):
        summary = (c.get("summary") or "")[:300]
        title = c.get("title") or ""
        topic_name = c.get("topic_name") or "General"
        candidates_text += f"{idx}. [{topic_name}] {title}\n   {summary}\n\n"

    prompt = (
        "You are a relevance judge for a personal knowledge base search engine.\n\n"
        f"QUERY: {query[:500]}\n\n"
        f"CANDIDATE NOTES:\n{candidates_text}\n"
        "For each candidate, rate its relevance to the query on a scale of 0-5 where:\n"
        "  5 = Directly answers the query\n"
        "  4 = Highly relevant, covers the same specific topic\n"
        "  3 = Somewhat relevant, same general domain\n"
        "  2 = Tangentially related\n"
        "  1 = Barely related\n"
        "  0 = Not relevant at all\n\n"
        "Return ONLY a JSON object mapping candidate number to score:\n"
        '{"1": 5, "2": 2, "3": 4}'
    )

    try:
        import json
        response = await call_llm(prompt, task="classify")
        clean = response.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        scores = json.loads(clean.strip())

        for idx, c in enumerate(top_n):
            key = str(idx + 1)
            llm_score = float(scores.get(key, 2.5))
            cos_sim = c.get("similarity", 0.5)
            # Weighted blend: 40% cosine + 60% LLM
            c["similarity"] = round(0.4 * cos_sim + 0.6 * (llm_score / 5.0), 4)
            c["llm_score"] = llm_score

        # Merge re-ranked + original remaining
        reranked = sorted(top_n, key=lambda x: x.get("similarity", 0), reverse=True)
        if len(candidates) > max_candidates:
            reranked.extend(candidates[max_candidates:])
        return reranked

    except Exception as e:
        logger.warning(f"LLM re-ranker error: {e}")
        return candidates


async def search_notes(
    query_text: str,
    limit: int = 5,
    threshold: float = 0.3,
    user_id: Optional[UUID] = None
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
        query_embedding = await embed(query_text)

        # 2. Call pgvector RPC matching function
        params = {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": limit
        }
        if user_id:
            params["p_user_id"] = str(user_id)
        response = supabase.rpc("match_notes", params).execute()

        results = response.data or []
        for r in results:
            r["similarity"] = normalize_similarity(r.get("similarity"))
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
            graph_notes = _get_graph_expanded_notes(matched_ids, limit=3, user_id=user_id)
            if graph_notes:
                logger.info(f"Graph expansion added {len(graph_notes)} additional note(s).")
                results.extend(graph_notes)
        except Exception as graph_err:
            logger.error(f"Failed to apply graph expansion: {graph_err}")

        # 5. LLM Re-Ranker — cross-encoder style re-evaluation of top results
        if results:
            try:
                results = await _llm_rerank(query_text, results)
            except Exception as rerank_err:
                logger.warning(f"LLM re-ranker failed, using raw scores: {rerank_err}")

        # 6. Sort by similarity descending
        results.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)

        return results
    except Exception as e:
        logger.error(f"Error executing match_notes RPC search: {e}", exc_info=True)
        return []

