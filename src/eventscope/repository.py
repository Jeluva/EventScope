"""Query layer over the normalized ``events`` table.

The radius search uses a bounding-box SQL pre-filter (index-friendly on plain
lat/lng columns) followed by an exact haversine refinement in Python. This is
portable across SQLite and Postgres; for high volume in production swap the
pre-filter for PostGIS ``ST_DWithin(geom, ...)``.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .geo import bounding_box, haversine_km
from .models import Event


@dataclass
class EventHit:
    event: Event
    distance_km: float | None = None


def events_within_radius(
    session: Session,
    lat: float,
    lng: float,
    radius_km: float,
    *,
    starts_after: dt.datetime | None = None,
    starts_before: dt.datetime | None = None,
    category: str | None = None,
    free_only: bool = False,
    limit: int = 200,
) -> list[EventHit]:
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)
    stmt = (
        select(Event)
        .where(Event.status == "active")
        .where(Event.lat.is_not(None), Event.lng.is_not(None))
        .where(Event.lat >= min_lat, Event.lat <= max_lat)
        .where(Event.lng >= min_lng, Event.lng <= max_lng)
    )
    if starts_after is not None:
        stmt = stmt.where(Event.starts_at >= starts_after)
    if starts_before is not None:
        stmt = stmt.where(Event.starts_at <= starts_before)
    if category:
        stmt = stmt.where(Event.category == category)
    if free_only:
        stmt = stmt.where(Event.is_free.is_(True))

    hits: list[EventHit] = []
    for event in session.scalars(stmt):
        dist = haversine_km(lat, lng, event.lat, event.lng)
        if dist <= radius_km:
            hits.append(EventHit(event=event, distance_km=round(dist, 3)))
    hits.sort(key=lambda h: h.distance_km if h.distance_km is not None else float("inf"))
    return hits[:limit]


def events_in_range(
    session: Session,
    starts_after: dt.datetime,
    starts_before: dt.datetime,
    *,
    category: str | None = None,
    limit: int = 500,
) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.status == "active")
        .where(Event.starts_at >= starts_after, Event.starts_at <= starts_before)
        .order_by(Event.starts_at)
    )
    if category:
        stmt = stmt.where(Event.category == category)
    return list(session.scalars(stmt.limit(limit)))


def get_event(session: Session, event_id: int) -> Event | None:
    return session.get(Event, event_id)
