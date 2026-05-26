import logging
from typing import List, Optional
import httpx

logger = logging.getLogger("grain.scrapers.search")

_API = "https://api.search.brave.com/res/v1/web/search"
_JINA = "https://r.jina.ai"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


async def brave_search(query, api_key, count=8):
    if not api_key:
        logger.error("BRAVE_API_KEY not configured")
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(_API, params={"q": query, "count": count}, headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.error("Brave search failed: %s", e)
        return None
    results = data.get("web", {}).get("results", [])
    if not results:
        return None
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")} for r in results]


async def brave_search_with_content(query, api_key, count=3):
    results = await brave_search(query, api_key, count)
    if not results:
        return None
    lines = [f"Search results for: {query}", ""]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        for i, r in enumerate(results, 1):
            lines.append(f"--- Result {i} ---")
            lines.append(f"Title: {r['title']}")
            lines.append(f"URL: {r['url']}")
            try:
                j = await c.get(f"{_JINA}/{r['url']}", headers={"User-Agent": _UA, "Accept": "text/plain"})
                if j.status_code == 200:
                    lines.append(j.text.strip()[:3000])
            except Exception:
                pass
            lines.append("")
    return "\n".join(lines)
