"""Geocoding hook: address/venue text → (lat, lng).

The default is a no-op (``NullGeocoder``) — we deliberately do NOT fabricate a
location (e.g. defaulting to the pilot centre), because a wrong pin is worse than
no pin. Events without coordinates are reachable via the Calendar (`/events/range`)
but excluded from the Map radius query until geocoded.

In production, plug in a real provider (Nominatim / Google / Mapbox) behind this
interface; the pipeline accepts any ``Geocoder`` so it can be injected in tests.
"""
from __future__ import annotations

import abc


class Geocoder(abc.ABC):
    @abc.abstractmethod
    def geocode(self, query: str) -> tuple[float, float] | None:
        """Return (lat, lng) for an address/venue string, or None if unknown."""


class NullGeocoder(Geocoder):
    def geocode(self, query: str) -> tuple[float, float] | None:
        return None


class StaticGeocoder(Geocoder):
    """Lookup table — handy for tests and for hard-coding known pilot venues."""

    def __init__(self, table: dict[str, tuple[float, float]]) -> None:
        self._table = {k.strip().lower(): v for k, v in table.items()}

    def geocode(self, query: str) -> tuple[float, float] | None:
        if not query:
            return None
        return self._table.get(query.strip().lower())


def get_geocoder() -> Geocoder:
    # No external geocoding service wired by default (keeps the slice offline).
    return NullGeocoder()
