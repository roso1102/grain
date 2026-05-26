import logging
import random
from typing import Dict, Optional
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger("grain.scrapers.twitter")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_JINA = "https://r.jina.ai"
_MAX = 15000

# Public Nitter instances — shuffled so load is spread
_NITTER_INSTANCES = [
    "nitter.net",
    "nitter.cz",
    "nitter.1d4.us",
    "nitter.kavin.rocks",
    "nitter.snopyta.org",
    "nitter.freedit.eu",
    "nitter.nixnet.email",
]
random.shuffle(_NITTER_INSTANCES)


class TwitterScraper(BaseScraper):
    name = "twitter"

    def can_handle(self, url: str) -> bool:
        d = urlparse(url).netloc.lower()
        return any(x in d for x in ("twitter.com", "x.com", "nitter."))

    async def scrape(self, url: str) -> Optional[Dict[str, str]]:
        # Normalize the path — strip domain, keep /user/status/id
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        # Try Nitter instances first
        for instance in _NITTER_INSTANCES:
            nitter_url = f"https://{instance}{path}"
            result = await self._scrape_nitter(nitter_url)
            if result:
                # Tell the caller the real source URL
                result["url"] = url
                return result
            logger.debug("Nitter instance %s failed for %s", instance, url)

        # Fallback: Jina Reader
        logger.info("All Nitter instances failed for %s, trying Jina fallback", url)
        return await self._jina_fallback(url)

    async def _scrape_nitter(self, url: str) -> Optional[Dict[str, str]]:
        try:
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True,
                headers={"User-Agent": _UA},
            ) as c:
                r = await c.get(url)
                if r.status_code != 200:
                    return None
        except Exception as e:
            logger.debug("Nitter fetch failed: %s", e)
            return None

        soup = BeautifulSoup(r.text, "lxml")

        # --- Author ---
        author_el = soup.select_one(".username")
        author = author_el.get_text(strip=True) if author_el else "Unknown"

        # --- Display name ---
        name_el = soup.select_one(".full-name")
        display_name = name_el.get_text(strip=True) if name_el else ""

        # --- Tweet text ---
        content_el = soup.select_one(".content .tweet-content")
        if not content_el:
            return None
        tweet_text = content_el.get_text("\n", strip=True)
        if not tweet_text:
            return None

        # --- Date ---
        date_el = soup.select_one(".tweet-date a")
        date = date_el.get("title", "") if date_el else ""

        # --- Stats ---
        stats = {}
        for stat in soup.select(".tweet-stat"):
            label = stat.get("title", "")
            value = stat.get_text(strip=True)
            stats[label] = value
        replies = stats.get("replies", "")
        retweets = stats.get("retweets", "")
        likes = stats.get("likes", "")

        # --- Build content ---
        lines = []
        if display_name:
            lines.append(f"**{display_name}** (@{author})")
        else:
            lines.append(f"@{author}")
        if date:
            lines.append(f"Date: {date}")
        lines.append("")
        lines.append(tweet_text)
        lines.append("")
        if replies or retweets or likes:
            parts = [f"{replies} replies" if replies else "",
                     f"{retweets} retweets" if retweets else "",
                     f"{likes} likes" if likes else ""]
            lines.append(" | ".join(p for p in parts if p))

        content = "\n".join(lines)
        if len(content) > _MAX:
            content = content[:_MAX] + "\n\n[Content truncated...]"

        return {"url": url, "title": f"Tweet by @{author}", "content": content}

    async def _jina_fallback(self, url: str) -> Optional[Dict[str, str]]:
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True,
                headers={"User-Agent": _UA, "Accept": "text/plain"},
            ) as c:
                r = await c.get(f"{_JINA}/{url}")
                if r.status_code != 200:
                    return None
                content = r.text.strip()[:_MAX]
                return {"url": url, "title": "Tweet", "content": content} if content else None
        except Exception as e:
            logger.error("Jina fallback failed for twitter %s: %s", url, e)
            return None
