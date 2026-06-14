"""Fixture-based scraper tests — zero network, zero credentials."""
from __future__ import annotations

from eventscope.scrapers import get_scraper, list_scrapers
from eventscope.scrapers.instagram_oembed import (
    fallback_embed_html,
    shortcode_from_permalink,
)
from eventscope.scrapers.venue_html import harvest_instagram_permalinks

from .conftest import load_fixture


def test_all_four_sources_registered():
    names = set(list_scrapers())
    assert {"eventbrite", "venue_html", "government", "instagram_oembed"} <= names


def test_eventbrite_parse():
    items = get_scraper("eventbrite").parse(load_fixture("eventbrite_response.json"))
    assert len(items) == 2
    jazz = items[0]
    assert jazz.source == "eventbrite"
    assert jazz.external_id == "1234567890"
    assert jazz.hints["is_free"] is True
    assert jazz.hints["lat"] == -34.8005
    assert "jazz" in jazz.raw_text.lower()


def test_venue_html_parses_jsonld_and_harvests_instagram():
    html = load_fixture("venue_page.html")
    items = get_scraper("venue_html", source="venue:cc", base_url="https://cc.example").parse(html)
    assert len(items) == 1
    ev = items[0]
    assert ev.hints["lat"] == -34.7990
    assert ev.hints["venue_name"] == "Centro Cultural Adrogué"
    # Instagram permalinks are harvested for the oEmbed enricher.
    permalinks = ev.payload["instagram_permalinks"]
    assert "https://www.instagram.com/p/AbCdEf123/" in permalinks
    assert "https://instagram.com/reel/XyZ987/" in permalinks


def test_government_parse_with_selectors():
    html = load_fixture("government_page.html")
    items = get_scraper(
        "government",
        source="gov:lomas",
        base_url="https://municipio.example",
        item_selector=".evento",
        title_selector=".titulo",
        date_selector=".fecha",
        location_selector=".lugar",
    ).parse(html)
    assert len(items) == 2
    feria = items[0]
    assert feria.source == "gov:lomas"
    assert feria.hints["date_text"] == "25 de julio de 2026"
    assert feria.hints["location_text"] == "Plaza Brown, Adrogué"
    assert feria.source_url == "https://municipio.example/eventos/feria-emprendedores"


def test_instagram_oembed_parse():
    raw = load_fixture("instagram_oembed.json")
    scraper = get_scraper("instagram_oembed", permalink="https://www.instagram.com/p/AbCdEf123/")
    items = scraper.parse(raw)
    assert len(items) == 1
    ig = items[0]
    assert ig.source == "instagram"
    assert ig.external_id == "AbCdEf123"
    assert "electrónica" in ig.raw_text.lower()
    assert ig.image_url == "https://scontent.cdninstagram.com/thumb.jpg"
    assert "AbCdEf123" in ig.payload["embed_html"]


def test_instagram_is_enrichment_not_discovery():
    assert get_scraper("instagram_oembed").discovery is False


def test_instagram_helpers():
    assert shortcode_from_permalink("https://www.instagram.com/p/AbCdEf123/") == "AbCdEf123"
    assert shortcode_from_permalink("https://instagram.com/reel/XyZ987") == "XyZ987"
    assert shortcode_from_permalink("https://example.com/nope") is None
    embed = fallback_embed_html("https://www.instagram.com/p/AbCdEf123/")
    assert "AbCdEf123/embed/" in embed


def test_harvest_instagram_permalinks_dedups():
    html = '<a href="https://www.instagram.com/p/X1/">a</a> https://www.instagram.com/p/X1/'
    assert harvest_instagram_permalinks(html) == ["https://www.instagram.com/p/X1/"]
