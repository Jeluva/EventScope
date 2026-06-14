from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from eventscope import db
from eventscope.api.main import create_app
from eventscope.pipeline import run_items
from eventscope.scrapers import get_scraper

from .conftest import load_fixture

NOW = dt.datetime(2026, 6, 14, tzinfo=dt.timezone.utc)


@pytest.fixture
def client(db_url):
    # Seed events into the same (temp) DB the app will read.
    items = get_scraper("eventbrite").parse(load_fixture("eventbrite_response.json"))
    with db.session_scope() as s:
        run_items(s, items, now=NOW)
    app = create_app(create_tables=False)
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_nearby_radius_filters_by_distance(client):
    # Pilot center is Adrogué; the CABA event (~25km) must be excluded at 5km.
    resp = client.get("/events/nearby", params={"lat": -34.7998, "lng": -58.3897, "radius_km": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Noche de Jazz en vivo"
    assert data[0]["distance_km"] is not None

    # Widen the radius and both events appear, sorted by distance.
    wide = client.get(
        "/events/nearby", params={"lat": -34.7998, "lng": -58.3897, "radius_km": 50}
    ).json()
    assert len(wide) == 2
    assert wide[0]["distance_km"] <= wide[1]["distance_km"]


def test_nearby_free_and_category_filters(client):
    free = client.get(
        "/events/nearby", params={"radius_km": 100, "free_only": True}
    ).json()
    assert all(e["is_free"] for e in free)
    music = client.get("/events/nearby", params={"radius_km": 100, "category": "musica"}).json()
    assert all(e["category"] == "musica" for e in music)


def test_nearby_rejects_unknown_category(client):
    resp = client.get("/events/nearby", params={"category": "noexiste"})
    assert resp.status_code == 422


def test_range_endpoint(client):
    resp = client.get(
        "/events/range", params={"start": "2026-07-01T00:00:00Z", "end": "2026-07-31T23:59:59Z"}
    )
    assert resp.status_code == 200
    titles = [e["title"] for e in resp.json()]
    assert "Noche de Jazz en vivo" in titles
    assert "Workshop de Data Engineering" not in titles  # August event excluded


def test_detail_and_404(client):
    listing = client.get("/events/nearby", params={"radius_km": 100}).json()
    eid = listing[0]["id"]
    assert client.get(f"/events/{eid}").json()["id"] == eid
    assert client.get("/events/999999").status_code == 404
