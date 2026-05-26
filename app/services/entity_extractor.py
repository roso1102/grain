import json
import logging
from typing import List, Dict
from app.integrations.gemini import call_llm

logger = logging.getLogger("grain.entity_extractor")

async def extract_entities(summary: str) -> List[Dict[str, str]]:
    """
    Extracts key named entities (concepts, technologies, projects, persons) 
    from the note summary using the Gemini LLM.
    
    Returns:
        List of dicts: [{"name": str, "type": str}]
    """
    if not summary or not summary.strip():
        return []
        
    prompt = (
        "You are an expert named entity extractor.\n"
        "Analyze the following text and extract key concepts, technologies, projects, and people.\n"
        "Categorize each extracted entity into one of these exact types:\n"
        "- 'concept': scientific or academic fields, abstract models, algorithms\n"
        "- 'technology': hardware components, software libraries, frameworks, devices\n"
        "- 'project': specific repositories, working groups, exams, codebases\n"
        "- 'person': authors, developers, historical key entities\n\n"
        f"Text to parse:\n{summary}\n\n"
        "Return ONLY a valid JSON list of objects containing the keys 'name' and 'type'. "
        "Do not include markdown headers or code block tags. Example output:\n"
        '[{"name": "GAAFET", "type": "technology"}, {"name": "VLSI Design", "type": "concept"}]'
    )
    
    try:
        response = await call_llm(prompt)
        clean_response = response.strip()
        
        # Clean potential markdown wrappers
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:]
        elif clean_response.startswith("```"):
            clean_response = clean_response[3:]
        if clean_response.endswith("```"):
            clean_response = clean_response[:-3]
        clean_response = clean_response.strip()
        
        parsed = json.loads(clean_response)
        
        # Validate shape and output
        validated = []
        allowed_types = {"concept", "technology", "project", "person"}
        for item in parsed:
            name = item.get("name")
            itype = item.get("type")
            if name and itype in allowed_types:
                validated.append({
                    "name": name.strip(),
                    "type": itype
                })
        return validated
    except Exception as e:
        logger.error(f"Failed to extract entities: {e}")
        return []
