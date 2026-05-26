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
        "4. SUMMARY: Write a comprehensive, high-quality, recall-optimized summary that answers:\n"
        "   - What is this about? (core subject/claim)\n"
        "   - What are the key facts, findings, or arguments?\n"
        "   - Why does it matter or what is the takeaway?\n"
        "   Rules:\n"
        "   - 4-6 sentences to ensure it is detailed and useful for learning.\n"
        "   - Plain prose — NO markdown asterisks (*), NO bullet points, NO hashtags in general text.\n"
        "   - Bold key terms using **term** syntax (will be converted to Notion bold).\n"
        "   - Be specific and factual — avoid vague phrases like 'the article discusses'.\n"
        "   - If the content is about a person/org/product, name them explicitly.\n\n"
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
        "  \"summary\": \"The full recall-optimized summary.\",\n"
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
        summary = data.get("summary")
        entities = data.get("entities") or []
        facets = data.get("facets") or {}
        
        # Override topic if routing hint was provided
        if route_hint:
            topic_name = route_hint
            
    except Exception as e:
        logger.error(f"Consolidated pipeline failed: {e}. Falling back to default heuristics.")
        # Fallback heuristics
        route_hint = None
        personal_insight = None
        topic_name = "General"
        entities = []
        facets = {}
        note_title = None
        
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
                    
        # Basic summary fallback
        words = content_to_analyze.split()
        if len(words) > 30:
            summary = " ".join(words[:30]) + "..."
        else:
            summary = content_to_analyze

    # If title is still None, derive it simply
    if not note_title:
        if content_to_analyze.startswith("Title:"):
            first_line = content_to_analyze.split("\n")[0]
            note_title = first_line.replace("Title:", "").strip()
        else:
            note_title = " ".join(raw_input.split()[:5])

    # Format the summary to include the source URL if it's a link and link is missing in the summary text
    if source_url and source_url not in summary:
        summary += f"\n\n🔗 **Source:** {source_url}"
        
    return {
        "raw_text": content_to_analyze,
        "summary": summary,
        "source_url": source_url,
        "source_type": source_type,
        "personal_insight": personal_insight,
        "topic_name": topic_name,
        "title": note_title,
        "entities": entities,
        "facets": facets
    }
