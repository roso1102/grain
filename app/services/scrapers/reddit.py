import logging
import re
from typing import Dict, Optional
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger("grain.scrapers.reddit")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_JINA = "https://r.jina.ai"
_MAX = 15000
_MAX_COMMENTS = 15


class RedditScraper(BaseScraper):
    name = "reddit"

    _OLD_REDDIT = "old.reddit.com"

    def can_handle(self, url: str) -> bool:
        d = urlparse(url).netloc.lower()
        return "reddit.com" in d or "redd.it" in d

    async def scrape(self, url: str) -> Optional[Dict[str, str]]:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        # Only handle post pages (not subreddit listings or user profiles)
        if not re.search(r"/comments/\w+", path):
            logger.debug("Reddit URL %s is not a post, skipping", url)
            return None

        # Rewrite to old.reddit.com for clean HTML
        old_url = f"https://{self._OLD_REDDIT}{path}"
        result = await self._scrape_old_reddit(old_url)
        if result:
            result["url"] = url
            return result

        # Fallback: Jina Reader
        logger.info("Old Reddit failed for %s, trying Jina fallback", url)
        return await self._jina_fallback(url)

    async def _scrape_old_reddit(self, url: str) -> Optional[Dict[str, str]]:
        try:
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True,
                headers={"User-Agent": _UA},
            ) as c:
                r = await c.get(url)
                if r.status_code != 200:
                    return None
        except Exception as e:
            logger.debug("Old Reddit fetch failed: %s", e)
            return None

        soup = BeautifulSoup(r.text, "lxml")

        # --- Title ---
        title_el = soup.select_one("a.title")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title:
            return None

        # --- Subreddit ---
        subreddit_el = soup.select_one(".redditname a, .side .titlebox h1")
        subreddit = subreddit_el.get_text(strip=True) if subreddit_el else ""

        # --- Author ---
        author_el = soup.select_one(".tagline .author")
        author = author_el.get_text(strip=True) if author_el else "Unknown"

        # --- Domain / flair ---
        domain_el = soup.select_one(".domain")
        domain = domain_el.get_text(strip=True).strip("()") if domain_el else ""

        # --- Post body (self-text) ---
        body_el = soup.select_one(".usertext-body .md")
        body = body_el.get_text("\n", strip=True) if body_el else ""

        # --- Score ---
        score_el = soup.select_one(".score.unvoted, .score.likes")
        score = score_el.get_text(strip=True) if score_el else ""

        # --- Comments ---
        comments = []
        for entry in soup.select(".commentarea .entry .usertext-body .md"):
            text = entry.get_text("\n", strip=True)
            if text:
                comments.append(text)
                if len(comments) >= _MAX_COMMENTS:
                    break

        # --- Build content ---
        lines = []
        lines.append(f"# {title}")
        if subreddit:
            lines.append(f"Subreddit: r/{subreddit}")
        if author:
            lines.append(f"Author: u/{author}")
        if score:
            lines.append(f"Score: {score}")
        if domain:
            lines.append(f"Domain: {domain}")
        lines.append("")

        if body:
            lines.append(body)
            lines.append("")

        if comments:
            lines.append("---")
            lines.append(f"**Top Comments ({len(comments)})**")
            lines.append("")
            for i, comment in enumerate(comments, 1):
                lines.append(f"**Comment {i}:**")
                lines.append(comment)
                lines.append("")

        content = "\n".join(lines)
        if len(content) > _MAX:
            content = content[:_MAX] + "\n\n[Content truncated...]"

        return {"url": url, "title": title, "content": content}

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
                return {"url": url, "title": "Reddit Post", "content": content} if content else None
        except Exception as e:
            logger.error("Jina fallback failed for reddit %s: %s", url, e)
            return None
