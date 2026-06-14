"""Pydantic response models for the public API."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from ..models import Event


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None = None
    category: str | None = None
    starts_at: dt.datetime
    ends_at: dt.datetime | None = None
    is_recurring: bool = False
    price: str | None = None
    is_free: bool = False
    venue_name: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    source: str
    source_url: str
    image_url: str | None = None
    status: str
    quality_score: float
    last_verified_at: dt.datetime
    distance_km: float | None = None

    @classmethod
    def from_event(cls, event: Event, distance_km: float | None = None) -> "EventOut":
        out = cls.model_validate(event)
        out.distance_km = distance_km
        return out
