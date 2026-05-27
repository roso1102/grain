import logging
from typing import List, Dict, Any
from uuid import UUID

from app.services.retrieval_engine import search_notes
from app.services.obsidian_sync import make_shortcode
from app.integrations.gemini import call_llm
from app.db.supabase import supabase
from app.utils.similarity import normalize_similarity

logger = logging.getLogger("grain.recall")


def _gather_citations(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    citations = []
    seen_shortcodes = set()
    for r in results:
        note_id = r.get("id")
        if not note_id:
            continue
        try:
            shortcode = make_shortcode(UUID(note_id))
        except Exception:
            shortcode = str(note_id)[:6]
        if shortcode in seen_shortcodes:
            continue
        seen_shortcodes.add(shortcode)
        summary = (r.get("summary") or "")[:200]
        citations.append({
            "shortcode": shortcode,
            "topic": r.get("topic_name", "General"),
            "source_url": r.get("source_url") or "",
            "summary_snippet": summary,
        })
    return citations


def _build_context_block(results: List[Dict[str, Any]]) -> str:
    blocks = []
    for idx, r in enumerate(results, start=1):
        note_id = r.get("id", "")
        try:
            shortcode = make_shortcode(UUID(note_id))
        except Exception:
            shortcode = str(note_id)[:6]

        topic = r.get("topic_name", "General")
        summary = (r.get("summary") or "").strip()
        title = (r.get("title") or "").strip()
        source_url = r.get("source_url") or ""
        similarity = normalize_similarity(r.get("similarity", 0.0))
        matched_via = r.get("matched_via", "vector")

        entity_names = []
        try:
            ent_res = supabase.table("note_entities")\
                .select("entities(name)")\
                .eq("note_id", note_id)\
                .execute()
            entity_names = [
                item["entities"]["name"]
                for item in (ent_res.data or [])
                if item.get("entities")
            ]
        except Exception:
            pass

        related_summaries = []
        try:
            out_rel = supabase.table("relations")\
                .select("target_note_id, relation_type")\
                .eq("source_note_id", note_id)\
                .execute()
            in_rel = supabase.table("relations")\
                .select("source_note_id, relation_type")\
                .eq("target_note_id", note_id)\
                .execute()
            seen_rel = set()
            for row in (out_rel.data or []) + (in_rel.data or []):
                rid = row.get("target_note_id") or row.get("source_note_id")
                rtype = row.get("relation_type", "related_to")
                if rid and rid not in seen_rel:
                    seen_rel.add(rid)
                    try:
                        sc = make_shortcode(UUID(rid))
                        related_summaries.append(f"{sc} ({rtype})")
                    except Exception:
                        related_summaries.append(f"{str(rid)[:6]} ({rtype})")
        except Exception:
            pass

        block = (
            f"[{idx}] Shortcode: `{shortcode}` | Topic: {topic} | "
            f"Relevance: {similarity:.2f} | Source: {matched_via}\n"
        )
        if title:
            block += f"    Title: {title}\n"
        if entity_names:
            block += f"    Entities: {', '.join(entity_names)}\n"
        if related_summaries:
            block += f"    Related Notes: {', '.join(related_summaries[:5])}\n"
        if source_url:
            block += f"    URL: {source_url}\n"
        block += f"    Content: {summary[:400]}\n"
        blocks.append(block)

    return "\n".join(blocks)


async def recall_answer(question: str, limit: int = 8) -> Dict[str, Any]:
    logger.info(f"Recall: searching for '{question}'")
    results = await search_notes(question, limit=limit, threshold=0.15)
    if not results:
        logger.info("Recall: no results found")
        return {
            "answer": "I couldn't find any relevant notes in your knowledge base.",
            "citations": [],
            "raw_response": "",
        }

    # Filter out low-relevance noise to keep context focused
    results_filtered = [r for r in results if r.get("similarity", 0) >= 0.4]
    if not results_filtered:
        results_filtered = results[:3]

    logger.info(f"Recall: retrieved {len(results_filtered)} relevant notes (filtered from {len(results)})")
    context_block = _build_context_block(results_filtered)
    citations = _gather_citations(results_filtered)

    prompt = (
        "You are a personal knowledge assistant. Answer the user's question by drawing on "
        "both the notes below and your own general knowledge. These notes are from the user's "
        "personal knowledge base (Grain PKOS).\n\n"
        "Instructions:\n"
        "- Use the notes as a starting point, then connect the dots using what you know\n"
        "- Identify relationships even when they're implicit — e.g., cuckoos and sparrows are related via brood parasitism\n"
        "- If you genuinely don't know something, say so\n"
        "- Always reference which notes you used by their shortcodes in backticks (e.g. `aB3kZ9`)\n"
        "- When mentioning a note's topic, prefix it with \U0001f4c2\n"
        "- Structure your answer clearly with short paragraphs\n\n"
        "USER QUESTION:\n"
        f"{question}\n\n"
        "KNOWLEDGE NOTES (ordered by relevance):\n"
        f"{context_block}\n\n"
        "Now answer the question. Be specific about what came from the notes vs. what you added from your own knowledge."
    )

    raw_response = await call_llm(prompt, task="recall")
    answer = raw_response.strip()

    if citations:
        citation_lines = ["\n\n\u2014\n\U0001f4da *Sources:*"]
        for c in citations[:6]:
            parts = f"`{c['shortcode']}` \U0001f4c2 {c['topic']}"
            if c.get("source_url"):
                parts += f" \u00b7 [Link]({c['source_url']})"
            citation_lines.append(f"\u2022 {parts}")
        if len(citations) > 6:
            citation_lines.append(f"\u2022 *+{len(citations) - 6} more notes*")
        answer += "\n".join(citation_lines)

    return {"answer": answer, "citations": citations, "raw_response": raw_response}
