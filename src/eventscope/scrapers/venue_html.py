"""Generic venue website scraper.

Strategy: prefer schema.org JSON-LD ``Event`` blocks (widely embedded by
ticketing/venue CMSs and the most stable signal), then fall back to configurable
CSS selectors for plain-HTML listings. As a side effect it harvests any
Instagram permalinks on the page — those feed the IG oEmbed enricher, which
cannot discover posts on its own.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedItem, register

IG_PERMALINK_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel)/[\w-]+/?", re.I)


def harvest_instagram_permalinks(html: str) -> list[str]:
    """Return de-duplicated Instagram post/reel permalinks found in the page."""
    seen: dict[str, None] = {}
    for match in IG_PERMALINK_RE.findall(html):
        url = match if match.endswith("/") else match + "/"
        seen.setdefault(url, None)
    return list(seen)


def _iter_jsonld_events(soup: BeautifulSoup) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        # @graph wrapper
        for cand in list(candidates):
            if isinstance(cand, dict) and "@graph" in cand:
                candidates.extend(cand["@graph"])
        for cand in candidates:
            if isinstance(cand, dict) and "Event" in str(cand.get("@type", "")):
                events.append(cand)
    return events


@register
class VenueHtmlScraper(BaseScraper):
    name = "venue_html"
    discovery = True

    def parse(self, raw: str) -> list[ScrapedItem]:
        source_name = self.options.get("source", "venue")
        base_url = self.options.get("base_url", "")
        soup = BeautifulSoup(raw, "html.parser")
        items: list[ScrapedItem] = []

        for ev in _iter_jsonld_events(soup):
            url = ev.get("url") or base_url
            name = ev.get("name") or ""
            desc = ev.get("description") or ""
            hints: dict[str, Any] = {}
            if ev.get("startDate"):
                hints["starts_at"] = ev["startDate"]
            if ev.get("endDate"):
                hints["ends_at"] = ev["endDate"]
            location = ev.get("location")
            if isinstance(location, dict):
                hints["venue_name"] = location.get("name")
                addr = location.get("address")
                if isinstance(addr, dict):
                    hints["address"] = ", ".join(
                        str(v) for v in (
                            addr.get("streetAddress"),
                            addr.get("addressLocality"),
                        ) if v
                    )
                elif isinstance(addr, str):
                    hints["address"] = addr
                geo = location.get("geo")
                if isinstance(geo, dict) and geo.get("latitude") and geo.get("longitude"):
                    hints["lat"] = float(geo["latitude"])
                    hints["lng"] = float(geo["longitude"])
            image = ev.get("image")
            if isinstance(image, list):
                image = image[0] if image else None

            items.append(
                ScrapedItem(
                    source=source_name,
                    source_url=url,
                    raw_text="\n".join(p for p in (name, desc) if p),
                    external_id=url or name or None,
                    image_url=image if isinstance(image, str) else None,
                    hints=hints,
                    payload={"jsonld": ev, "instagram_permalinks": harvest_instagram_permalinks(raw)},
                )
            )

        # Fallback: configurable CSS selector for sites without JSON-LD.
        if not items and self.options.get("item_selector"):
            for el in soup.select(self.options["item_selector"]):
                text = el.get_text(" ", strip=True)
                if not text:
                    continue
                link = el.find("a", href=True)
                url = (link["href"] if link else base_url) or base_url
                items.append(
                    ScrapedItem(
                        source=source_name,
                        source_url=url,
                        raw_text=text,
                        external_id=url or None,
                        payload={"html": str(el)},
                    )
                )
        return items

    def fetch(self) -> str:  # pragma: no cover - live path
        url = self.options["url"]
        with self._client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
