from __future__ import annotations

import datetime as dt

from eventscope.extraction.llm import StubExtractor, parse_spanish_date
from eventscope.scrapers.base import ScrapedItem


def test_parse_spanish_date():
    d = parse_spanish_date("25 de julio de 2026")
    assert (d.year, d.month, d.day) == (2026, 7, 25)
    d2 = parse_spanish_date("evento el 2 de agosto", default_year=2026)
    assert (d2.month, d2.day) == (8, 2)
    assert parse_spanish_date("sin fecha alguna xyz") is None


def test_stub_extractor_uses_hints():
    item = ScrapedItem(
        source="eventbrite",
        source_url="https://e.example/1",
        raw_text="Noche de Jazz en vivo\nConcierto gratuito",
        hints={
            "starts_at": "2026-07-15T23:00:00Z",
            "is_free": True,
            "lat": -34.8,
            "lng": -58.39,
            "venue_name": "Bar X",
        },
    )
    ev = StubExtractor().extract(item)
    assert ev.title == "Noche de Jazz en vivo"
    assert ev.category == "musica"
    assert ev.is_free is True
    assert ev.lat == -34.8
    assert ev.starts_at.year == 2026


def test_stub_extractor_parses_spanish_date_from_text():
    item = ScrapedItem(
        source="gov:x",
        source_url="https://gov.example/1",
        raw_text="Feria de Emprendedores\n25 de julio de 2026\nPlaza Brown",
        hints={"date_text": "25 de julio de 2026", "location_text": "Plaza Brown"},
    )
    ev = StubExtractor().extract(item)
    assert ev.category == "ferias"
    assert ev.starts_at.month == 7
    assert ev.address == "Plaza Brown"


def test_stub_extractor_returns_none_without_title():
    item = ScrapedItem(source="x", source_url="u", raw_text="   ")
    assert StubExtractor().extract(item) is None
