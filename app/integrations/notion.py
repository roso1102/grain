import logging
import re
from typing import Dict, Any, Tuple, List, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger("grain.notion")

NOTION_API_URL = "https://api.notion.com/v1"

def _get_headers() -> Dict[str, str]:
    if not settings.NOTION_API_KEY:
        raise ValueError("NOTION_API_KEY is not configured in environment.")
    return {
        "Authorization": f"Bearer {settings.NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

# ---------------------------------------------------------------------------
# Rich Text Helpers
# ---------------------------------------------------------------------------

def _plain_rich_text(text: str) -> List[Dict]:
    """Creates a plain rich_text element."""
    return [{"type": "text", "text": {"content": text}}]

def _link_rich_text(text: str, url: str) -> List[Dict]:
    """Creates a linked rich_text element."""
    return [{"type": "text", "text": {"content": text, "link": {"url": url}}}]

def _parse_inline_markdown(text: str) -> List[Dict]:
    """
    Parses a line of text with inline markdown (bold **x**, italic _x_) and
    converts it to a list of Notion rich_text objects.
    Notion does NOT render markdown syntax — we must use the rich_text API properly.
    """
    rich_texts = []
    # Pattern: **bold**, _italic_, or plain text
    pattern = r'(\*\*(.+?)\*\*|_(.+?)_|[^*_]+)'
    for match in re.finditer(pattern, text):
        full = match.group(0)
        if full.startswith("**") and full.endswith("**"):
            inner = match.group(2)
            rich_texts.append({
                "type": "text",
                "text": {"content": inner},
                "annotations": {"bold": True}
            })
        elif full.startswith("_") and full.endswith("_"):
            inner = match.group(3)
            rich_texts.append({
                "type": "text",
                "text": {"content": inner},
                "annotations": {"italic": True}
            })
        else:
            rich_texts.append({
                "type": "text",
                "text": {"content": full}
            })
    return rich_texts if rich_texts else _plain_rich_text(text)

# ---------------------------------------------------------------------------
# Block Builders
# ---------------------------------------------------------------------------

def _heading_block(text: str, level: int = 2) -> Dict:
    """Creates a heading_2 or heading_3 block."""
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": _plain_rich_text(text)}
    }

def _paragraph_block(rich_texts: List[Dict]) -> Dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_texts}
    }

def _bullet_block(rich_texts: List[Dict]) -> Dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_texts}
    }

def _callout_block(text: str, emoji: str = "💡") -> Dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": _parse_inline_markdown(text),
            "icon": {"type": "emoji", "emoji": emoji}
        }
    }

def _divider_block() -> Dict:
    return {"object": "block", "type": "divider", "divider": {}}

def _quote_block(text: str) -> Dict:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": _parse_inline_markdown(text)}
    }

def _bookmark_block(url: str, caption: str = "") -> Dict:
    block = {
        "object": "block",
        "type": "bookmark",
        "bookmark": {"url": url}
    }
    if caption:
        block["bookmark"]["caption"] = _plain_rich_text(caption)
    return block

# ---------------------------------------------------------------------------
# Structured Note Page Builder
# ---------------------------------------------------------------------------

def build_note_blocks(
    summary: str,
    source_url: Optional[str] = None,
    personal_insight: Optional[str] = None,
    source_type: str = "manual"
) -> List[Dict]:
    """
    Builds a rich, well-structured list of Notion blocks for a Knowledge Card.
    
    Parses the structured summary format and renders each section as an
    appropriate Notion block type:
    
        **Core:** ...          →  quote block
        **Facts:**             →  bulleted list items
        **Why This Matters:**  →  callout with 💡
        **Status:**            →  paragraph (gray italic)
        **Links To:**          →  paragraph

    Then appends:
        ---  (divider)
        🔗 Source  (bookmark block, only if URL present)
        💡 Insight  (callout, only if present)
        Capture type tag  (gray italic)
    """
    blocks = []

    # ── Parse Knowledge Card sections ──────────────────────────────────────
    lines = summary.split("\n")
    current_section = None
    fact_items = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Strip leading markdown bullets or stars for content detection
        cleaned = line.lstrip("*•- ").strip()

        # Detect section headers
        if line.startswith("**Core:**"):
            core_text = line[len("**Core:**"):].strip()
            if core_text:
                blocks.append(_quote_block(core_text))
            current_section = "core"

        elif line.startswith("**Facts:**"):
            current_section = "facts"

        elif line.startswith("**Why This Matters:**"):
            # Flush any pending fact bullets
            _flush_facts(blocks, fact_items)
            current_section = "why"
            matter_text = line[len("**Why This Matters:**"):].strip()
            if matter_text:
                blocks.append(_callout_block(matter_text, emoji="💡"))

        elif line.startswith("**Status:**"):
            current_section = "status"
            status_text = line[len("**Status:**"):].strip()
            if status_text:
                blocks.append(_paragraph_block([{
                    "type": "text",
                    "text": {"content": status_text},
                    "annotations": {"italic": True, "color": "gray"}
                }]))

        elif line.startswith("**Links To:**"):
            current_section = "links"
            links_text = line[len("**Links To:**"):].strip()
            if links_text:
                blocks.append(_paragraph_block([{
                    "type": "text",
                    "text": {"content": f"🔗 {links_text}"}
                }]))

        elif current_section == "facts" and cleaned:
            # Collect bullet items (whether or not they have a leading bullet marker)
            if cleaned.startswith("• ") or cleaned.startswith("- "):
                cleaned = cleaned[2:].strip()
            if cleaned:
                fact_items.append(cleaned)

        else:
            # Fallback: lines not matching known sections render as plain paragraphs
            # (e.g. lines from legacy summaries or unexpected formatting)
            blocks.append(_paragraph_block(_parse_inline_markdown(cleaned)))

    # Flush any remaining fact bullets
    _flush_facts(blocks, fact_items)

    # ── Divider ────────────────────────────────────────────────────────────
    blocks.append(_divider_block())

    # ── Source link ────────────────────────────────────────────────────────
    if source_url:
        blocks.append(_heading_block("🔗 Source", level=3))
        blocks.append(_bookmark_block(source_url))

    # ── Personal insight ───────────────────────────────────────────────────
    if personal_insight:
        blocks.append(_callout_block(personal_insight, emoji="💡"))

    # ── Capture type tag ───────────────────────────────────────────────────
    type_label = {
        "link": "Captured from web link",
        "telegram_text": "Captured via Telegram",
        "manual": "Manually ingested",
        "pdf": "Extracted from PDF",
        "screenshot": "Extracted from image"
    }.get(source_type, "Captured note")

    blocks.append(_paragraph_block([{
        "type": "text",
        "text": {"content": type_label},
        "annotations": {"italic": True, "color": "gray"}
    }]))

    return blocks


def _flush_facts(blocks: List[Dict], fact_items: List[str]) -> None:
    """Appends any collected fact bullets as Notion bulleted list items."""
    if not fact_items:
        return
    for item in fact_items:
        blocks.append(_bullet_block(_parse_inline_markdown(item)))
    fact_items.clear()


# ---------------------------------------------------------------------------
# Notion API Calls
# ---------------------------------------------------------------------------

async def create_page(parent_page_id: str, title: str) -> str:
    """
    Creates a new sub-page under the specified parent page (topic-level page).
    Returns the new page ID.
    """
    url = f"{NOTION_API_URL}/pages"
    headers = _get_headers()
    payload = {
        "parent": {"page_id": parent_page_id.replace("-", "")},
        "properties": {
            "title": {
                "title": [{"text": {"content": title}}]
            }
        }
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["id"]


async def create_note_subpage(
    topic_page_id: str,
    title: str,
    summary: str,
    source_url: Optional[str] = None,
    personal_insight: Optional[str] = None,
    source_type: str = "manual"
) -> Tuple[str, str]:
    """
    Creates a fully-structured note sub-page under a topic page.
    
    Returns:
        (page_id, last_edited_time)
    """
    url = f"{NOTION_API_URL}/pages"
    headers = _get_headers()

    children_blocks = build_note_blocks(
        summary=summary,
        source_url=source_url,
        personal_insight=personal_insight,
        source_type=source_type
    )

    payload = {
        "parent": {"page_id": topic_page_id.replace("-", "")},
        "properties": {
            "title": {
                "title": [{"text": {"content": title}}]
            }
        },
        "children": children_blocks
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["id"], data.get("last_edited_time", "")


async def append_blocks(page_id: str, blocks: List[Dict]) -> Tuple[str, str]:
    """
    Appends a list of rich blocks to a Notion page.
    Returns (first_block_id, last_edited_time).
    """
    url = f"{NOTION_API_URL}/blocks/{page_id.replace('-', '')}/children"
    headers = _get_headers()
    payload = {"children": blocks}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.patch(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        block = data["results"][0]
        return block["id"], block.get("last_edited_time", "")


async def append_paragraph_block(page_id: str, text: str) -> Tuple[str, str]:
    """Legacy plain-text paragraph append. Still used by poll_notion_updates."""
    return await append_blocks(page_id, [_paragraph_block(_plain_rich_text(text))])


async def update_paragraph_block(block_id: str, text: str) -> str:
    """Updates the content of an existing paragraph block."""
    url = f"{NOTION_API_URL}/blocks/{block_id.replace('-', '')}"
    headers = _get_headers()
    payload = {
        "paragraph": {
            "rich_text": _plain_rich_text(text)
        }
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.patch(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["last_edited_time"]


async def get_block(block_id: str) -> Tuple[str, str]:
    """Retrieves the metadata of a block. Returns (last_edited_time, text_content)."""
    url = f"{NOTION_API_URL}/blocks/{block_id.replace('-', '')}"
    headers = _get_headers()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        last_edited_time = data["last_edited_time"]
        text_content = ""
        block_type = data.get("type")
        if block_type == "paragraph":
            rich_texts = data["paragraph"]["rich_text"]
            if rich_texts:
                text_content = "".join([t["text"]["content"] for t in rich_texts])

        return last_edited_time, text_content


async def get_page(page_id: str) -> Dict[str, Any]:
    url = f"{NOTION_API_URL}/pages/{page_id.replace('-', '')}"
    headers = _get_headers()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


async def search_pages(query: str) -> List[Dict[str, Any]]:
    url = f"{NOTION_API_URL}/search"
    headers = _get_headers()
    payload = {
        "query": query,
        "filter": {"value": "page", "property": "object"}
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
