"""Scraper para noticias culturales del Municipio de Esteban Echeverría.

API: WordPress REST (misma estructura que Almirante Brown)
URL: https://www.estebanecheverria.gob.ar/wp-json/wp/v2/posts
Categoría 81 = Cultura (521 posts)
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedItem, register
from .venue_html import harvest_instagram_permalinks

_BASE = "https://www.estebanecheverria.gob.ar"
_API = (
    f"{_BASE}/wp-json/wp/v2/posts"
    "?categories=81&per_page=20&orderby=date&order=desc"
    "&_fields=id,date,title,excerpt,content,link"
)


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text()).strip()


def _parse_posts(posts: list[dict]) -> list[ScrapedItem]:
    items: list[ScrapedItem] = []
    for post in posts:
        title = _strip_html(post.get("title", {}).get("rendered", ""))
        if not title:
            continue
        excerpt = _strip_html(post.get("excerpt", {}).get("rendered", ""))
        content_html = post.get("content", {}).get("rendered", "")
        content_text = _strip_html(content_html)
        date_str = (post.get("date") or "")[:10]  # "2026-06-15"
        link = post.get("link", _BASE)

        ig_links = harvest_instagram_permalinks(content_html)

        raw_text = "\n".join(p for p in [title, excerpt, content_text[:400]] if p)

        items.append(
            ScrapedItem(
                source="gov:echeverria",
                source_url=link,
                external_id=str(post["id"]),
                raw_text=raw_text,
                hints={"date_text": date_str},
                payload={"instagram_permalinks": ig_links},
            )
        )
    return items


@register
class EstebanEcheverriaScraper(BaseScraper):
    """Noticias culturales — Municipio de Esteban Echeverría (WordPress REST)."""

    name = "esteban_echeverria"
    discovery = True

    def parse(self, raw: str | bytes) -> list[ScrapedItem]:
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        return _parse_posts(data)

    def fetch(self) -> str:  # pragma: no cover
        with self._client() as client:
            resp = client.get(_API)
            resp.raise_for_status()
            return resp.text
