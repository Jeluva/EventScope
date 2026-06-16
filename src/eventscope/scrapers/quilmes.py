"""Scraper de noticias culturales del Municipio de Quilmes.

URL: https://quilmes.gov.ar/noticias/?categoria=cultura
Estructura: grilla de <article> elements, cada uno con:
  - <a> con href relativo a la noticia (noticia.php?id_noti=N)
  - <p> con nombre de la categoría
  - <a> con título completo
  - <p> con descripción corta
  - <p> con fecha en español mayúsculas ("MIÉRCOLES, 10 DE JUNIO DE 2026")

El filtro ?categoria=cultura no filtra completamente; el LLM downstream
descarta noticias que no son eventos culturales.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedItem, register
from .venue_html import harvest_instagram_permalinks

_BASE = "https://quilmes.gov.ar"
_NOTICIAS_URL = f"{_BASE}/noticias/?categoria=cultura"

# Date format: "MIÉRCOLES, 10 DE JUNIO DE 2026"
_DATE_RE = re.compile(
    r"(?:LUNES|MARTES|MIÉ?RCOLES|JUEVES|VIERNES|SÁBADO|DOMINGO),\s+\d{1,2}\s+DE\s+\w+\s+DE\s+\d{4}",
    re.I,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_articles(soup: BeautifulSoup) -> list[ScrapedItem]:
    items: list[ScrapedItem] = []

    for article in soup.find_all("article"):
        texts = [_clean(el.get_text()) for el in article.find_all(["p", "a", "h2", "h3"]) if _clean(el.get_text())]
        if not texts:
            continue

        # Find the canonical article link (href with id_noti or noticia)
        link_tag = article.find("a", href=re.compile(r"id_noti|noticia"))
        if not link_tag:
            link_tag = article.find("a", href=True)
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        full_url = urljoin(_BASE + "/noticias/", href) if href else _BASE

        # Title: prefer the second <a> or the <h2>/<h3>; first <a> is often the image link
        all_links = article.find_all("a", href=True)
        title = ""
        for a in all_links:
            t = _clean(a.get_text())
            if t and len(t) > 10:
                title = t
                break
        if not title:
            h = article.find(["h2", "h3"])
            title = _clean(h.get_text()) if h else texts[0]

        # Date: the distinctive "MIÉRCOLES, 10 DE JUNIO DE 2026" paragraph
        date_text = ""
        for p in article.find_all("p"):
            t = _clean(p.get_text())
            if _DATE_RE.search(t):
                date_text = t.title()  # "Miércoles, 10 De Junio De 2026"
                break

        # Description: longest paragraph that isn't a date or category
        description = ""
        for p in article.find_all("p"):
            t = _clean(p.get_text())
            if t and not _DATE_RE.search(t) and len(t) > len(description):
                description = t

        category_text = ""
        for p in article.find_all("p"):
            t = _clean(p.get_text())
            if t and not _DATE_RE.search(t) and len(t) < 40 and t != description:
                category_text = t
                break

        ig_links = harvest_instagram_permalinks(str(article))

        # Extract id_noti as external_id
        m = re.search(r"id_noti=(\d+)", href)
        external_id = m.group(1) if m else None

        raw_text = "\n".join(p for p in [title, category_text, description, date_text] if p)

        items.append(
            ScrapedItem(
                source="gov:quilmes",
                source_url=full_url,
                raw_text=raw_text,
                external_id=external_id,
                hints={
                    "date_text": date_text,
                },
                payload={
                    "category_raw": category_text,
                    "instagram_permalinks": ig_links,
                },
            )
        )

    return items


@register
class QuilmesScraper(BaseScraper):
    """Noticias culturales del Municipio de Quilmes."""

    name = "quilmes"
    discovery = True

    def parse(self, raw: str) -> list[ScrapedItem]:
        soup = BeautifulSoup(raw, "html.parser")
        return _parse_articles(soup)

    def fetch(self) -> str:  # pragma: no cover
        with self._client() as client:
            resp = client.get(_NOTICIAS_URL)
            resp.raise_for_status()
            return resp.text
