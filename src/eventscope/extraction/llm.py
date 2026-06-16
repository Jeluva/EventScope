"""Provider-agnostic structured extraction.

Providers:
  * ``stub``   — offline, deterministic heuristic extractor. Default; used in
                 tests and local dev. Good enough to drive the full pipeline.
  * ``gemini`` — Google Gemini Flash via REST API (no SDK needed, uses httpx).
  * ``openai`` — OpenAI gpt-4o-mini via REST API (no SDK needed, uses httpx).

Both real providers send the JSON schema as part of the system prompt and
request JSON-only output. Structured-output API modes (Gemini response_schema,
OpenAI strict) are intentionally avoided — they require schema sanitisation and
add provider-specific friction. Plain "respond with JSON" is more portable and
still forces valid JSON via response_mime_type / response_format.
"""
from __future__ import annotations

import abc
import datetime as dt
import json
import logging
import re
from typing import Any

import httpx
from dateutil import parser as dateparser

from ..config import get_settings
from ..scrapers.base import ScrapedItem
from .schema import CATEGORIES, ExtractedEvent

log = logging.getLogger(__name__)

# ─── Heuristic helpers (used by StubExtractor) ───────────────────────────────

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


# ─── ABC ─────────────────────────────────────────────────────────────────────

class Extractor(abc.ABC):
    @abc.abstractmethod
    def extract(self, item: ScrapedItem) -> ExtractedEvent | None:
        """Return normalized fields, or None when nothing usable can be parsed."""


# ─── StubExtractor (offline default) ─────────────────────────────────────────

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


# ─── LLM base (shared prompt logic) ──────────────────────────────────────────

class _LLMExtractor(Extractor):  # pragma: no cover - live path only
    """Shared scaffolding: build prompt, call HTTP, parse JSON response."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._schema_str = json.dumps(
            ExtractedEvent.json_schema(), ensure_ascii=False, indent=None
        )

    def _system(self) -> str:
        return (
            "Sos un extractor de eventos culturales argentinos. "
            "Analizá el texto y devolvé ÚNICAMENTE un objeto JSON válido que cumpla "
            "el siguiente schema. Para campos sin datos, usá null. "
            "Las fechas van en formato ISO 8601 (YYYY-MM-DDTHH:MM:SS). "
            "El campo 'category' debe ser uno de: "
            f"{', '.join(CATEGORIES)}.\n\n"
            f"Schema JSON:\n{self._schema_str}"
        )

    def _user(self, item: ScrapedItem) -> str:
        return (
            f"Fuente: {item.source}\n"
            f"URL: {item.source_url}\n\n"
            f"Texto del evento:\n{item.raw_text}"
        )

    def _parse_response(self, raw_json: str) -> ExtractedEvent | None:
        """Strip markdown fences if present, then validate."""
        text = raw_json.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return ExtractedEvent.model_validate_json(text)
        except Exception as exc:
            log.warning("LLM response parse error: %s — raw: %.200s", exc, raw_json)
            return None

    def _call(self, item: ScrapedItem) -> str | None:
        raise NotImplementedError

    def extract(self, item: ScrapedItem) -> ExtractedEvent | None:
        raw = self._call(item)
        if raw is None:
            return None
        return self._parse_response(raw)


# ─── Gemini Flash ─────────────────────────────────────────────────────────────

class GeminiExtractor(_LLMExtractor):  # pragma: no cover - live path only
    """Google Gemini via REST — no SDK, just httpx.

    Default model: gemini-2.0-flash (cheapest, fast enough for extraction).
    Set EVENTSCOPE_LLM_MODEL to override (e.g. gemini-1.5-flash).
    """

    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        super().__init__(api_key, model)

    def _call(self, item: ScrapedItem) -> str | None:
        import time
        url = f"{self._BASE}/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": self._system()}]},
            "contents": [{"parts": [{"text": self._user(item)}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        for attempt in range(3):
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 429:
                        wait = 2 ** attempt * 5  # 5s, 10s, 20s
                        log.warning("Gemini rate limited, retrying in %ss", wait)
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    break
            except httpx.HTTPError as exc:
                log.error("Gemini HTTP error: %s", exc)
                return None
        else:
            log.error("Gemini rate limit persisted after retries")
            return None
        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError) as exc:
            log.error("Gemini response shape unexpected: %s", exc)
            return None


# ─── OpenAI gpt-4o-mini ───────────────────────────────────────────────────────

class OpenAIExtractor(_LLMExtractor):  # pragma: no cover - live path only
    """OpenAI via REST — no SDK, just httpx.

    Default model: gpt-4o-mini.
    Set EVENTSCOPE_LLM_MODEL to override.
    """

    _BASE = "https://api.openai.com/v1"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        super().__init__(api_key, model)

    def _call(self, item: ScrapedItem) -> str | None:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system()},
                {"role": "user", "content": self._user(item)},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(
                timeout=30.0,
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as client:
                resp = client.post(f"{self._BASE}/chat/completions", json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("OpenAI HTTP error: %s", exc)
            return None
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            log.error("OpenAI response shape unexpected: %s", exc)
            return None


# ─── Factory ──────────────────────────────────────────────────────────────────

def get_extractor() -> Extractor:
    settings = get_settings()
    provider = (settings.llm_provider or "stub").lower()

    if provider == "gemini" and settings.llm_api_key:
        model = settings.llm_model or "gemini-2.0-flash"
        return GeminiExtractor(api_key=settings.llm_api_key, model=model)

    if provider == "openai" and settings.llm_api_key:
        model = settings.llm_model or "gpt-4o-mini"
        return OpenAIExtractor(api_key=settings.llm_api_key, model=model)

    if provider not in ("stub", "gemini", "openai"):
        log.warning("Unknown LLM provider %r, falling back to stub", provider)

    return StubExtractor()
