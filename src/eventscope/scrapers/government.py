"""Government / municipal events scraper.

NEW source (not in the original docx): municipalities publish a "agenda
cultural" — stable, public, low legal risk, and authoritative for civic events.
Layouts vary, so this scraper is driven by a small selector config:

    get_scraper(
        "government",
        source="gov:lomas",
        base_url="https://lomasdezamora.gob.ar",
        item_selector=".evento",
        title_selector="h3",
        date_selector=".fecha",
        location_selector=".lugar",
    )

Field selectors are optional; when absent the scraper falls back to the item's
full text (the LLM extractor recovers the structured fields downstream).
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, ScrapedItem, register


def _sel_text(el: Tag, selector: str | None) -> str | None:
    if not selector:
        return None
    found = el.select_one(selector)
    return found.get_text(" ", strip=True) if found else None


@register
class GovernmentScraper(BaseScraper):
    name = "government"
    discovery = True

    def parse(self, raw: str) -> list[ScrapedItem]:
        source_name = self.options.get("source", "gov")
        base_url = self.options.get("base_url", "")
        item_selector = self.options.get("item_selector", "article")
        soup = BeautifulSoup(raw, "html.parser")
        items: list[ScrapedItem] = []

        for el in soup.select(item_selector):
            title = _sel_text(el, self.options.get("title_selector"))
            date_text = _sel_text(el, self.options.get("date_selector"))
            location = _sel_text(el, self.options.get("location_selector"))

            link = el.find("a", href=True)
            url = urljoin(base_url, link["href"]) if link else base_url
            full_text = el.get_text(" ", strip=True)
            if not (title or full_text):
                continue

            hints: dict[str, str] = {}
            if date_text:
                hints["date_text"] = date_text
            if location:
                hints["location_text"] = location

            # Compose the text fed to the LLM, leading with the strongest signals.
            text = "\n".join(
                p for p in (title, date_text, location, full_text) if p
            )
            items.append(
                ScrapedItem(
                    source=source_name,
                    source_url=url,
                    raw_text=text,
                    external_id=url or title or None,
                    hints=hints,
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
