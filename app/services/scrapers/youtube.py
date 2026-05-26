import logging
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse
import httpx
from .base import BaseScraper

logger = logging.getLogger("grain.scrapers.youtube")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_JINA = "https://r.jina.ai"
_MAX = 15000


class YouTubeScraper(BaseScraper):
    name = "youtube"

    def can_handle(self, url):
        d = urlparse(url).netloc.lower()
        return "youtube.com" in d or "youtu.be" in d

    def _vid_id(self, url):
        p = urlparse(url)
        if "youtu.be" in p.netloc:
            return p.path.lstrip("/").split("?")[0]
        return parse_qs(p.query).get("v", [None])[0]

    async def _subs(self, vid):
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            t = YouTubeTranscriptApi.get_transcript(vid, languages=["en", "en-GB", "en-US"])
            if not t:
                return None
            text = " ".join(s["text"] for s in t)
            if len(text) > _MAX:
                text = text[:_MAX] + "\n\n[Content truncated...]"
            return text
        except Exception as e:
            logger.warning("Transcript failed for %s: %s", vid, e)
            return None

    async def scrape(self, url):
        vid = self._vid_id(url)
        if not vid:
            return None
        subs = await self._subs(vid)
        if subs:
            return {"url": url, "title": f"YouTube Video {vid}", "content": f"Video transcript:\n\n{subs}"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                r = await c.get(f"{_JINA}/{url}", headers={"User-Agent": _UA, "Accept": "text/plain"})
                r.raise_for_status()
                content = r.text.strip()[:_MAX]
            if content:
                return {"url": url, "title": "YouTube Video", "content": content}
        except Exception as e:
            logger.error("YouTube fallback failed: %s", e)
        return None
