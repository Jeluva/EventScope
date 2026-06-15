"""Almirante Brown municipal events scraper.

Uses the WordPress REST API exposed by brown.gob.ar to retrieve posts tagged
with noticia_categoria=162 (Cultura).  Each WP post becomes one ScrapedItem
whose raw_text (title + excerpt) feeds the LLM extractor downstream.

Options accepted by __init__:
    base_url      -- default https://www.brown.gob.ar
    categoria_id  -- WP term ID (default 162 = Cultura)
    per_page      -- items per API page (default 20, max 100)
"""
from __future__ import annotations

import re
from typing import Any

from .base import BaseScraper, ScrapedItem, register
from .venue_html import harvest_instagram_permalinks


def _clean(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


@register
class AlmiranteBrownScraper(BaseScraper):
    name = "almirante_brown"
    discovery = True

    _DEFAULT_BASE = "https://www.brown.gob.ar"
    _CULTURA_ID = 162

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        items: list[ScrapedItem] = []
        for post in raw:
            title = _clean(post.get("title", {}).get("rendered", ""))
            if not title:
                continue

            post_id = str(post.get("id", ""))
            link = post.get("link", self._DEFAULT_BASE)
            date_str = post.get("date", "")
            excerpt = _clean(post.get("excerpt", {}).get("rendered", ""))
            content_html = post.get("content", {}).get("rendered", "")

            raw_text = "\n".join(p for p in (title, excerpt) if p)
            ig_links = harvest_instagram_permalinks(content_html) if content_html else []

            hints: dict[str, Any] = {}
            if date_str:
                hints["date_text"] = date_str[:10]  # "YYYY-MM-DD"

            items.append(
                ScrapedItem(
                    source="gov:brown",
                    source_url=link,
                    raw_text=raw_text,
                    external_id=post_id or None,
                    hints=hints,
                    payload={
                        "content": _clean(content_html),
                        "instagram_permalinks": ig_links,
                    },
                )
            )
        return items

    def fetch(self) -> list[dict[str, Any]]:  # pragma: no cover
        base = self.options.get("base_url", self._DEFAULT_BASE).rstrip("/")
        cat_id = self.options.get("categoria_id", self._CULTURA_ID)
        per_page = self.options.get("per_page", 20)
        url = (
            f"{base}/wp-json/wp/v2/post_type_noticias"
            f"?noticia_categoria={cat_id}"
            f"&per_page={per_page}"
            f"&_fields=id,date,title,excerpt,content,link"
        )
        with self._client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
