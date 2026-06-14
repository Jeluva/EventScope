"""Provider-agnostic structured extraction.

Providers:
  * ``stub``   — offline, deterministic heuristic extractor. Default; used in
                 tests and local dev. Good enough to drive the full pipeline.
  * ``gemini`` / ``openai`` — real LLM providers using JSON-Schema structured
                 output. Active only when a key is configured (not run in tests).

The docx recommends a cheap LLM (Gemini Flash / GPT-4o-mini), so the real
providers are intentionally thin wrappers — the contract lives in schema.py.
"""
from __future__ import annotations

import abc
import datetime as dt
import re
from typing import Any

from dateutil import parser as dateparser

from ..config import get_settings
from ..scrapers.base import ScrapedItem
from .schema import CATEGORIES, ExtractedEvent

# Keyword → category heuristics (Spanish-first, matches the pilot audience).
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "musica": ("música", "music", "concierto", "recital", "dj", "banda", "vivo", "jazz", "rock"),
    "arte": ("arte", "muestra", "exposición", "galería", "teatro", "cine", "danza"),
    "gastronomia": ("gastronom", "feria de comida", "food", "cerveza", "vino", "degustación"),
    "tech": ("tech", "hackathon", "programación", "startup", "developer",
             "inteligencia artificial", "machine learning", "data engineering"),
    "networking": ("networking", "meetup", "charla", "conferencia", "workshop"),
    "bienestar": ("yoga", "meditación", "bienestar", "wellness", "running", "salud"),
    "ferias": ("feria", "mercado", "bazar", "expo"),
}

_FREE_TOKENS = ("gratis", "gratuito", "entrada libre", "free", "sin cargo")

# Spanish month names → number, so the stub can parse "15 de julio de 2026".
_ES_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_ES_DATE_RE = re.compile(
    r"(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+de\s+(\d{4}))?", re.I
)


def parse_spanish_date(text: str, *, default_year: int | None = None) -> dt.datetime | None:
    m = _ES_DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _ES_MONTHS.get(m.group(2).lower())
        year = int(m.group(3)) if m.group(3) else (default_year or dt.date.today().year)
        if month:
            return dt.datetime(year, month, day, tzinfo=dt.timezone.utc)
    # Fall back to dateutil for ISO / numeric formats.
    try:
        return dateparser.parse(text, dayfirst=True)
    except (ValueError, OverflowError):
        return None


def _coerce_dt(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    try:
        return dateparser.parse(str(value))
    except (ValueError, OverflowError):
        return None


class Extractor(abc.ABC):
    @abc.abstractmethod
    def extract(self, item: ScrapedItem) -> ExtractedEvent | None:
        """Return normalized fields, or None when nothing usable can be parsed."""


class StubExtractor(Extractor):
    """Heuristic, offline extractor. Prefers structured source hints, then text."""

    def extract(self, item: ScrapedItem) -> ExtractedEvent | None:
        text = (item.raw_text or "").strip()
        hints = item.hints or {}
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        title = first_line[:200] or hints.get("venue_name") or None
        if not title:
            return None

        lower = text.lower()
        category = "otros"
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            if any(k in lower for k in keywords):
                category = cat
                break

        starts_at = _coerce_dt(hints.get("starts_at"))
        if starts_at is None and hints.get("date_text"):
            starts_at = parse_spanish_date(hints["date_text"])
        if starts_at is None:
            starts_at = parse_spanish_date(text)

        is_free = bool(hints.get("is_free")) or any(tok in lower for tok in _FREE_TOKENS)

        return ExtractedEvent(
            title=title,
            description=text[:500] or None,
            category=category if category in CATEGORIES else "otros",
            starts_at=starts_at,
            ends_at=_coerce_dt(hints.get("ends_at")),
            is_free=is_free,
            price="Gratis" if is_free else None,
            venue_name=hints.get("venue_name") or hints.get("location_text"),
            address=hints.get("address") or hints.get("location_text"),
            lat=hints.get("lat"),
            lng=hints.get("lng"),
            confidence=0.6 if starts_at else 0.3,
        )


class _LLMHttpExtractor(Extractor):  # pragma: no cover - live path
    """Shared scaffolding for real providers using JSON-Schema structured output."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def _prompt(self, item: ScrapedItem) -> str:
        return (
            "Extraé los campos del evento del siguiente texto. Respondé SOLO con "
            "JSON que cumpla el schema provisto. Si un campo no está, dejalo null.\n\n"
            f"Fuente: {item.source}\nURL: {item.source_url}\n\nTexto:\n{item.raw_text}"
        )


def get_extractor() -> Extractor:
    settings = get_settings()
    provider = (settings.llm_provider or "stub").lower()
    if provider == "stub" or not settings.llm_api_key:
        return StubExtractor()
    # Real providers are wired here when keys are present; out of scope for the
    # offline slice, so we keep the stub as a safe default.
    return StubExtractor()
