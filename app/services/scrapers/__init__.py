import logging, re
from typing import Dict, Optional
from urllib.parse import urlparse

from .twitter import TwitterScraper
from .youtube import YouTubeScraper
from .reddit import RedditScraper
from .rss import RSSScraper
from .web import WebScraper

logger = logging.getLogger("grain.scrapers")

# Order matters: specific scrapers before generic ones
SCRAPERS = [
    TwitterScraper(),
    YouTubeScraper(),
    RedditScraper(),
    RSSScraper(),
    WebScraper(),
]

_URL_RE = re.compile(r"https?://\S+")


def detect_url(text: str) -> Optional[str]:
    m = _URL_RE.search(text)
    return m.group(0) if m else None


async def extract_url_content(url: str) -> Optional[Dict[str, str]]:
    domain = urlparse(url).hostname or ""
    for s in SCRAPERS:
        if s.can_handle(url):
            try:
                r = await s.scrape(url)
                if r:
                    return r
            except Exception as e:
                logger.warning("Scraper=%s failed: %s", s.name, e)
    return None
