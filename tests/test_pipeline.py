from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from eventscope.geocoding import StaticGeocoder
from eventscope.models import Event, RawEvent
from eventscope.pipeline import enrich_from_instagram, purge_stale_events, run_items
from eventscope.repository import events_within_radius
from eventscope.scrapers import get_scraper

from .conftest import load_fixture

NOW = dt.datetime(2026, 6, 14, tzinfo=dt.timezone.utc)


def _all_items():
    eb = get_scraper("eventbrite").parse(load_fixture("eventbrite_response.json"))
    venue = get_scraper("venue_html", source="venue:cc", base_url="https://cc.example").parse(
        load_fixture("venue_page.html")
    )
    gov = get_scraper(
        "government",
        source="gov:lomas",
        base_url="https://municipio.example",
        item_selector=".evento",
        title_selector=".titulo",
        date_selector=".fecha",
        location_selector=".lugar",
    ).parse(load_fixture("government_page.html"))
    ig = get_scraper(
        "instagram_oembed", permalink="https://www.instagram.com/p/AbCdEf123/"
    ).parse(load_fixture("instagram_oembed.json"))
    return eb + venue + gov + ig


def test_full_pipeline_ingests_all_sources(session):
    result = run_items(session, _all_items(), now=NOW)
    # 2 eventbrite + 1 venue + 2 gov + 1 instagram = 6 raw, all valid & future.
    assert result.raw_stored == 6
    assert result.events_upserted == 6
    assert result.rejected == 0

    count = session.scalar(select(func.count()).select_from(Event))
    assert count == 6
    sources = set(session.scalars(select(Event.source)))
    assert sources == {"eventbrite", "venue:cc", "gov:lomas", "instagram"}


def test_pipeline_rejects_past_events(session):
    items = get_scraper("eventbrite").parse(load_fixture("eventbrite_response.json"))
    far_future = dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc)
    result = run_items(session, items, now=far_future)
    assert result.events_upserted == 0
    assert result.rejected == 2
    assert all("past" in r for r in result.rejections)


def test_pipeline_dedups_across_runs(session):
    items = get_scraper("eventbrite").parse(load_fixture("eventbrite_response.json"))
    run_items(session, items, now=NOW)
    # Re-ingest the same source: raw rows are idempotent, no new events.
    result = run_items(session, items, now=NOW)
    assert result.events_upserted == 0
    assert session.scalar(select(func.count()).select_from(Event)) == 2
    # raw_events stays at 2 (unique on source+external_id).
    assert session.scalar(select(func.count()).select_from(RawEvent)) == 2


def test_provenance_recorded(session):
    run_items(session, _all_items(), now=NOW)
    ig = session.scalar(select(Event).where(Event.source == "instagram"))
    assert ig.source_url == "https://www.instagram.com/p/AbCdEf123/"
    assert ig.image_url is not None


def test_instagram_enrichment_loop_from_harvested_permalinks(session):
    # 1) Ingest the venue page — it harvests an IG permalink into raw_events.
    venue = get_scraper("venue_html", source="venue:cc", base_url="https://cc.example").parse(
        load_fixture("venue_page.html")
    )
    run_items(session, venue, now=NOW)
    assert session.scalar(select(func.count()).select_from(Event).where(Event.source == "instagram")) == 0

    # 2) Run the enrichment pass with a FAKE resolver (offline, no token/network)
    #    that returns the oEmbed fixture for the harvested permalink.
    ig_fixture = load_fixture("instagram_oembed.json")

    def fake_resolver(permalinks):
        scraper = get_scraper("instagram_oembed", permalink=permalinks[0])
        return scraper.parse(ig_fixture)

    result = enrich_from_instagram(session, resolver=fake_resolver, now=NOW)
    assert result.events_upserted == 1

    ig = session.scalar(select(Event).where(Event.source == "instagram"))
    assert ig.source_url == "https://www.instagram.com/p/AbCdEf123/"
    assert ig.category == "musica"  # parsed from the caption

    # 3) Idempotent: a second pass resolves nothing new.
    again = enrich_from_instagram(session, resolver=fake_resolver, now=NOW)
    assert again.events_upserted == 0


def test_geocoder_hook_makes_gov_events_map_visible(session):
    # Without geocoding the gov event has no coords → absent from the radius query.
    gov_items = get_scraper(
        "government", source="gov:lomas", base_url="https://municipio.example",
        item_selector=".evento", title_selector=".titulo",
        date_selector=".fecha", location_selector=".lugar",
    ).parse(load_fixture("government_page.html"))

    geocoder = StaticGeocoder({"Plaza Brown, Adrogué": (-34.7995, -58.3892)})
    run_items(session, gov_items, now=NOW, geocoder=geocoder)

    feria = session.scalar(select(Event).where(Event.title == "Feria de Emprendedores"))
    assert feria.lat == -34.7995
    hits = events_within_radius(session, -34.7998, -58.3897, 5.0)
    assert any(h.event.title == "Feria de Emprendedores" for h in hits)


def test_purge_marks_stale_events_cancelled(session):
    run_items(session, _all_items(), now=NOW)
    active_before = session.scalar(
        select(func.count()).select_from(Event).where(Event.status == "active")
    )
    assert active_before == 6

    # Purge with a "now" far in the future so all events are stale.
    far_future = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    count = purge_stale_events(session, days=7, now=far_future)
    assert count == 6
    cancelled = session.scalar(
        select(func.count()).select_from(Event).where(Event.status == "cancelled")
    )
    assert cancelled == 6


def test_purge_dry_run_does_not_write(session):
    run_items(session, _all_items(), now=NOW)
    far_future = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    count = purge_stale_events(session, days=7, dry_run=True, now=far_future)
    assert count == 6
    # Status unchanged
    still_active = session.scalar(
        select(func.count()).select_from(Event).where(Event.status == "active")
    )
    assert still_active == 6
