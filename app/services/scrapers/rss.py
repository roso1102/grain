import logging
from typing import Dict, Optional
from urllib.parse import urlparse
import httpx
from .base import BaseScraper

logger = logging.getLogger("grain.scrapers.rss")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_MAX_ENTRIES = 20
_MAX_CHARS = 15000


class RSSScraper(BaseScraper):
    name = "rss"

    _IND = ("/feed", "/rss", "/atom", ".xml", "/feed/", "rss.xml", "atom.xml")

    def can_handle(self, url):
        path = urlparse(url).path.lower()
        return any(i in path for i in self._IND)

    async def scrape(self, url):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                r = await c.get(url, headers={"User-Agent": _UA})
                r.raise_for_status()
        except Exception as e:
            logger.error("RSS fetch failed for %s: %s", url, e)
            return None

        import feedparser
        feed = feedparser.parse(r.text)
        if not feed.entries:
            logger.warning("RSS feed %s has no entries", url)
            return None

        ftitle = feed.feed.get("title", "RSS Feed")
        lines = ["# " + ftitle, "Source: " + url, ""]

        for entry in feed.entries[:_MAX_ENTRIES]:
            title = entry.get("title", "Untitled")
            link = entry.get("link", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            published = entry.get("published", "") or entry.get("updated", "")
            lines.append("## " + title)
            if published:
                lines.append("Published: " + published)
            if link:
                lines.append("Link: " + link)
            if summary:
                lines.append(summary)
            lines.append("")

        content = "\n".join(lines)
        if len(content) > _MAX_CHARS:
            content = content[:_MAX_CHARS] + "\n\n[Content truncated...]"

        return {"url": url, "title": ftitle, "content": content}
