"""Tests for scrapers module — URL routing and domain dispatch."""

from unittest.mock import AsyncMock, patch
import pytest

from app.services.scrapers import detect_url, extract_url_content
from app.services.scrapers.web import WebScraper
from app.services.scrapers.youtube import YouTubeScraper
from app.services.scrapers.rss import RSSScraper


# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

def test_detect_url_plain_text():
    result = detect_url("hello world")
    assert result is None


def test_detect_url_http():
    result = detect_url("check https://example.com out")
    assert result == "https://example.com"


def test_detect_url_multiple():
    result = detect_url("first https://a.com and https://b.com")
    assert result == "https://a.com"


# ---------------------------------------------------------------------------
# Domain routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.services.scrapers.youtube.YouTubeScraper.scrape")
@patch("app.services.scrapers.web.WebScraper.scrape")
async def test_router_youtube_permalink(mock_web, mock_yt):
    mock_yt.return_value = {"url": "u", "title": "T", "content": "C"}
    result = await extract_url_content("https://www.youtube.com/watch?v=abc")
    assert result is not None
    mock_yt.assert_awaited_once()
    mock_web.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.scrapers.rss.RSSScraper.scrape")
@patch("app.services.scrapers.web.WebScraper.scrape")
async def test_router_rss_feed(mock_web, mock_rss):
    mock_rss.return_value = {"url": "u", "title": "T", "content": "C"}
    result = await extract_url_content("https://example.com/rss")
    assert result is not None
    mock_rss.assert_awaited_once()
    mock_web.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.scrapers.web.WebScraper.scrape")
async def test_router_falls_back_to_web(mock_web):
    mock_web.return_value = {"url": "u", "title": "T", "content": "C"}
    result = await extract_url_content("https://arstechnica.com/article")
    assert result is not None
    mock_web.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_returns_none_when_all_fail():
    with patch.object(WebScraper, "scrape", return_value=None):
        with patch.object(YouTubeScraper, "scrape", return_value=None):
            with patch.object(RSSScraper, "scrape", return_value=None):
                result = await extract_url_content("https://broken.com")
                assert result is None


# ---------------------------------------------------------------------------
# Scraper domain detection
# ---------------------------------------------------------------------------

def test_youtube_can_handle():
    yt = YouTubeScraper()
    assert yt.can_handle("https://youtube.com/watch?v=abc")
    assert yt.can_handle("https://youtu.be/abc")
    assert not yt.can_handle("https://vimeo.com/123")


def test_rss_can_handle():
    rss = RSSScraper()
    assert rss.can_handle("https://example.com/feed")
    assert rss.can_handle("https://blog.com/rss.xml")
    assert rss.can_handle("https://site.com/atom")
    assert not rss.can_handle("https://example.com/post")


def test_web_can_handle_any():
    web = WebScraper()
    assert web.can_handle("https://example.com")
    assert web.can_handle("https://x.com/user/status/1")
    assert web.can_handle("https://reddit.com/r/python")

