"""Backward-compatible shim — delegates to scrapers module."""

from app.services.scrapers import detect_url, extract_url_content

# Alias for backward compatibility
extract_link_content = extract_url_content

