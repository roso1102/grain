import logging
import json
from typing import Dict, Any
from app.services.scrapers import detect_url, extract_url_content
from app.integrations.gemini import call_llm

logger = logging.getLogger("grain.understand")

async def understand(raw_input: str) -> Dict[str, Any]:
    """
    Orchestrates the understanding pipeline for an incoming raw text message.
    Consolidates intent parsing, topic classification, summarization, and entity extraction
    into a single optimized LLM call to prevent rate-limiting (429 errors).
    """
    logger.info(f"Analyzing raw input (length: {len(raw_input)})")
    
    # 1. Link Extraction
    url = detect_url(raw_input)
    source_url = None
    source_type = "telegram_text"
    content_to_analyze = raw_input
    
    if url:
        logger.info(f"URL detected: {url}. Scraping content...")
        # Always save the source_url regardless of scraping success
        source_url = url
        scraped = await extract_url_content(url)
        if scraped:
            source_type = "link"
            content_to_analyze = f"Title: {scraped['title']}\n\n{scraped['content']}"
            logger.info(f"Webpage scraped. Title: {scraped['title']}")
        else:
            logger.warning("Webpage scraping failed. Saving link only.")
            
    # 2. Build the consolidated prompt
    source_context = f"Source URL: {url}" if url else "Source: Direct text input"
    prompt = (
        "You are an expert knowledge curator for a personal AI brain.\n"
        "Your job is to deeply analyze content and extract structured, recall-optimized knowledge.\n\n"
        f"Original User Message:\n{raw_input}\n\n"
        f"Content to Analyze ({source_context}):\n{content_to_analyze[:8000]}\n\n"
        "=== TASKS ===\n\n"
        "1. INTENT (from Original User Message only):\n"
        "   - route_hint: If user explicitly says 'save to X', 'put in X', 'topic: X' → extract X. Otherwise null.\n"
        "   - personal_insight: If user adds their own thoughts/comments alongside a link → extract it. Otherwise null.\n\n"
        "2. TOPIC: One precise, capitalized topic name (1-3 words). Think like a library catalog.\n"
        "   Good examples: 'Cancer Research', 'VLSI Design', 'EV Batteries', 'Japanese Culture'\n\n"
        "3. TITLE: A clean, concise, clear title for this note (3-8 words, capitalized, NO markdown formatting, NO asterisks, NO links, e.g. 'KMSB Television Station' or 'Color Theory for Artists').\n\n"
        "4. SUMMARY — extract these fields separately:\n"
        "   - core_claim: 1 sentence — the single most important claim/finding. Recall anchor.\n"
        "   - facts: array of 2-4 concise, standalone factual statements. Each must be a specific, named claim.\n"
        "   - why_matters: 1 sentence — personal relevance or takeaway for the user.\n"
        "   - status: one of Established | Hypothesis | Debate | Speculative — epistemic confidence level.\n"
        "   - links_to: comma-separated list of 2-5 related entities, concepts, or topics.\n"
        "   Rules:\n"
        "   - Be specific and factual — no vague filler like 'the article discusses'.\n"
        "   - Name entities, people, technologies explicitly.\n"
        "   - Bold key terms with **term** syntax.\n\n"
        "5. ENTITIES: Extract key named concepts, technologies, people, and organizations.\n\n"
        "6. FACETS: Extract structured tags for grouping and cross-linking notes. Use these keys:\n"
        "   - location: Geographic places (continents, countries, regions, cities, landmarks)\n"
        "   - subject: Domain or field (e.g. \"Geology\", \"Law\", \"Biology\", \"Machine Learning\", \"Architecture\")\n"
        "   - category: High-level bucket (e.g. \"Science\", \"History\", \"Current Events\", \"Arts\", \"Technology\", \"Business\")\n"
        "   Only include a key if the content is clearly relevant to that facet. Each list should have 0-3 items.\n\n"
        "Return ONLY a valid JSON object (no code blocks, no explanation):\n"
        "{\n"
        "  \"route_hint\": null,\n"
        "  \"personal_insight\": null,\n"
        "  \"topic_name\": \"Topic Name\",\n"
        "  \"title\": \"Clear Concise Note Title\",\n"
        "  \"core_claim\": \"Single most important finding.\",\n"
        "  \"facts\": [\"Specific fact or argument one.\", \"Specific fact or argument two.\", \"Specific fact or argument three.\"],\n"
        "  \"why_matters\": \"Why this is relevant to the user personally.\",\n"
        "  \"status\": \"Established\",\n"
        "  \"links_to\": \"Related Entity A, Related Entity B, Related Entity C\",\n"
        "  \"entities\": [{\"name\": \"Entity\", \"type\": \"concept|technology|project|person\"}],\n"
        "  \"facets\": {\"location\": [], \"subject\": [], \"category\": []}\n"
        "}"
    )
    
    try:
        response = await call_llm(prompt, task="understand")
        clean_response = response.strip()
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:]
        elif clean_response.startswith("```"):
            clean_response = clean_response[3:]
        if clean_response.endswith("```"):
            clean_response = clean_response[:-3]
        clean_response = clean_response.strip()
        
        data = json.loads(clean_response)
        
        # Extract fields with safe fallbacks
        route_hint = data.get("route_hint")
        personal_insight = data.get("personal_insight")
        topic_name = data.get("topic_name") or "General"
        note_title = data.get("title")
        core_claim = data.get("core_claim")
        facts = data.get("facts") or []
        why_matters = data.get("why_matters")
        note_status = data.get("status")
        links_to = data.get("links_to")
        entities = data.get("entities") or []
        facets = data.get("facets") or {}
        
        # Build the Knowledge Card summary string with guaranteed formatting
        summary_parts = []
        if core_claim:
            summary_parts.append(f"**Core:** {core_claim}")
        if facts:
            summary_parts.append("**Facts:**")
            for f in facts:
                summary_parts.append(f"• {f}")
        if why_matters:
            summary_parts.append(f"**Why This Matters:** {why_matters}")
        if note_status:
            summary_parts.append(f"**Status:** {note_status}")
        if links_to:
            summary_parts.append(f"**Links To:** {links_to}")
        summary = "\n".join(summary_parts)
        
        # Override topic if routing hint was provided
        if route_hint:
            topic_name = route_hint
            
    except Exception as e:
        logger.error(f"Consolidated pipeline failed: {e}. Falling back to default heuristics.")
        # Fallback heuristics
        route_hint = None
        personal_insight = None
        topic_name = "General"
        core_claim = None
        facts = []
        why_matters = None
        note_status = None
        links_to = None
        entities = []
        facets = {}
        
        # Try a quick fallback topic name
        if content_to_analyze.startswith("Title:"):
            first_line = content_to_analyze.split("\n")[0]
            title_content = first_line.replace("Title:", "").strip()
            note_title = title_content
            for sep in ["|", "-", "—", ":"]:
                if sep in title_content:
                    candidate = title_content.split(sep)[0].strip()
                    if 2 < len(candidate) < 30:
                        topic_name = candidate.title()
                        break
            else:
                words = title_content.split()
                if words:
                    topic_name = " ".join(words[:3]).title()
        else:
            words = [w for w in raw_input.split() if w.isalnum()]
            if words:
                candidate = " ".join(words[:3]).title()
                if len(candidate) > 2:
                    topic_name = candidate
                    
        # Basic summary fallback — build minimal Knowledge Card
        words = content_to_analyze.split()
        if len(words) > 30:
            core_claim = " ".join(words[:30]) + "..."
        else:
            core_claim = content_to_analyze
        facts = []
        why_matters = None
        note_status = "Established"
        links_to = None
        summary_parts = [f"**Core:** {core_claim}"]
        if note_status:
            summary_parts.append(f"**Status:** {note_status}")
        summary = "\n".join(summary_parts)

    # If title is still None, derive it simply
    if not note_title:
        if content_to_analyze.startswith("Title:"):
            first_line = content_to_analyze.split("\n")[0]
            note_title = first_line.replace("Title:", "").strip()
        else:
            note_title = " ".join(raw_input.split()[:5])

    return {
        "raw_text": content_to_analyze,
        "summary": summary,
        "source_url": source_url,
        "source_type": source_type,
        "personal_insight": personal_insight,
        "topic_name": topic_name,
        "title": note_title,
        "entities": entities,
        "facets": facets,
        "core_claim": core_claim,
        "facts": facts,
        "why_matters": why_matters,
        "status": note_status,
        "links_to": links_to
    }
