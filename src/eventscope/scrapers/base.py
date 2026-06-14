"""Scraper base class, item contract, and registry.

Design rule: **fetching (network) is separate from parsing (pure)**. Every
scraper implements ``parse(raw)`` as a pure function over already-fetched
content, so it can be exercised against saved fixtures with zero network. The
``scrape()`` method wires real fetching to parsing for production runs.
"""
from __future__ import annotations

import abc
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx


@dataclass
class ScrapedItem:
    """One raw event candidate as seen by a scraper, before LLM normalization.

    ``raw_text`` is the free text handed to the LLM extractor. ``payload`` keeps
    the full structured/original content for the immutable ``raw_events`` row.
    """

    source: str
    source_url: str
    raw_text: str
    external_id: str | None = None
    image_url: str | None = None
    # Optional structured hints a source already provides (lat/lng, start time…)
    hints: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


class BaseScraper(abc.ABC):
    """Subclasses set ``name`` and implement ``parse`` (and usually ``fetch``)."""

    name: ClassVar[str] = ""
    # When True, the scraper discovers many events; when False it enriches a
    # single known URL/permalink (e.g. Instagram oEmbed). Discovery scrapers
    # become scheduled Airflow DAGs; enrichers run keyed on harvested links.
    discovery: ClassVar[bool] = True

    def __init__(self, **options: Any) -> None:
        self.options = options

    @abc.abstractmethod
    def parse(self, raw: Any) -> list[ScrapedItem]:
        """Pure transform: fetched content -> scraped items. Network-free."""

    def fetch(self) -> Any:  # pragma: no cover - exercised only in live runs
        """Fetch raw content from the live source. Override per scraper."""
        raise NotImplementedError(f"{self.name}: live fetch not configured")

    def scrape(self) -> list[ScrapedItem]:  # pragma: no cover - live path
        return self.parse(self.fetch())

    @staticmethod
    def _client(**kwargs: Any) -> httpx.Client:
        defaults = {
            "timeout": 20.0,
            "headers": {"User-Agent": "EventScope/0.1 (+https://eventscope.app)"},
            "follow_redirects": True,
        }
        defaults.update(kwargs)
        return httpx.Client(**defaults)


# ─── Registry ────────────────────────────────────────────────────────────────
_REGISTRY: dict[str, type[BaseScraper]] = {}


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Class decorator: add a scraper to the registry under its ``name``."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a non-empty `name`")
    if cls.name in _REGISTRY:
        raise ValueError(f"duplicate scraper name: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def get_scraper(name: str, **options: Any) -> BaseScraper:
    if name not in _REGISTRY:
        raise KeyError(f"unknown scraper: {name!r} (known: {sorted(_REGISTRY)})")
    return _REGISTRY[name](**options)


def list_scrapers() -> Iterable[str]:
    return sorted(_REGISTRY)
