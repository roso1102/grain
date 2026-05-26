import logging
from typing import Dict, Optional
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
import trafilatura
from .base import BaseScraper

logger = logging.getLogger("grain.scrapers.web")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_JINA = "https://r.jina.ai"
_MAX = 15000


class WebScraper(BaseScraper):
    name = "web"

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)

    async def scrape(self, url: str) -> Optional[Dict[str, str]]:
        # 1. Try Jina Reader (fastest, best output)
        result = await self._jina(url)
        if result:
            return result

        # 2. Try trafilatura (good extraction, handles most sites)
        result = await self._trafilatura(url)
        if result:
            return result

        # 3. Fallback: raw BeautifulSoup
        result = await self._soup(url)
        if result:
            return result

        logger.warning("All web scraping methods failed for %s", url)
        return None

    async def _jina(self, url: str) -> Optional[Dict[str, str]]:
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True,
                headers={"User-Agent": _UA, "Accept": "text/plain"},
            ) as c:
                r = await c.get(f"{_JINA}/{url}")
                if r.status_code != 200:
                    return None
                content = r.text.strip()
                if not content:
                    return None
                if len(content) > _MAX:
                    content = content[:_MAX] + "\n\n[Content truncated...]"

                # Jina returns metadata as first few lines: "Title: ...\nURL: ...\n\n..."
                title = "Web Page"
                for line in content.split("\n")[:5]:
                    if line.lower().startswith("title:"):
                        title = line.split(":", 1)[1].strip()
                        break

                return {"url": url, "title": title, "content": content}
        except Exception as e:
            logger.debug("Jina failed for %s: %s", url, e)
            return None

    async def _trafilatura(self, url: str) -> Optional[Dict[str, str]]:
        try:
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True,
                headers={"User-Agent": _UA},
            ) as c:
                r = await c.get(url)
                if r.status_code != 200:
                    return None
                html = r.text
        except Exception as e:
            logger.debug("trafilatura fetch failed for %s: %s", url, e)
            return None

        try:
            text = trafilatura.extract(html, output_format="txt", include_comments=False)
            if not text or len(text.strip()) < 50:
                return None
            content = text.strip()
            if len(content) > _MAX:
                content = content[:_MAX] + "\n\n[Content truncated...]"

            title = trafilatura.bare_extraction(html).get("title") or "Web Page"

            return {"url": url, "title": title, "content": content}
        except Exception as e:
            logger.debug("trafilatura extract failed for %s: %s", url, e)
            return None

    async def _soup(self, url: str) -> Optional[Dict[str, str]]:
        try:
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True,
                headers={"User-Agent": _UA},
            ) as c:
                r = await c.get(url)
                if r.status_code != 200:
                    return None
                html = r.text
        except Exception as e:
            logger.debug("Soup fetch failed for %s: %s", url, e)
            return None

        try:
            soup = BeautifulSoup(html, "lxml")

            # Remove unwanted elements
            for tag in soup.select("script, style, nav, footer, header, aside, noscript"):
                tag.decompose()

            title = soup.title.get_text(strip=True) if soup.title else "Web Page"

            # Try main-content selectors, then fallback to body
            main = soup.select_one("article, main, .post-content, .entry-content, .content, #content")
            if not main:
                main = soup.body
            if not main:
                return None

            text = main.get_text("\n", strip=True)
            if len(text) < 50:
                return None

            if len(text) > _MAX:
                text = text[:_MAX] + "\n\n[Content truncated...]"

            return {"url": url, "title": title, "content": text}
        except Exception as e:
            logger.debug("Soup extract failed for %s: %s", url, e)
            return None
