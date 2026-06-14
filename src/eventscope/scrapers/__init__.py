"""Scraper framework and source implementations.

Importing this package registers every built-in scraper in the registry.
"""
from .base import BaseScraper, ScrapedItem, get_scraper, list_scrapers, register

# Import side-effects register the scrapers.
from . import eventbrite, government, instagram_oembed, venue_html  # noqa: E402,F401

__all__ = [
    "BaseScraper",
    "ScrapedItem",
    "register",
    "get_scraper",
    "list_scrapers",
]
