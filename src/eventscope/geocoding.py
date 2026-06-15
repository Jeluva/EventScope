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
import time

import httpx


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


class NominatimGeocoder(Geocoder):
    """Free geocoder backed by OpenStreetMap Nominatim.

    Nominatim's usage policy requires:
    - A descriptive User-Agent header (not a generic library name)
    - Max 1 request/second — enforced by ``_min_interval``

    Country-code filter defaults to "ar" (Argentina) to avoid ambiguous matches
    for local venue names that could match cities abroad.
    """

    _min_interval = 1.1  # seconds between requests (Nominatim ToS: max 1 req/s)

    def __init__(
        self,
        user_agent: str,
        base_url: str = "https://nominatim.openstreetmap.org",
        countrycodes: str = "ar",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._countrycodes = countrycodes
        self._headers = {"User-Agent": user_agent, "Accept-Language": "es"}
        self._last_call: float = 0.0

    def geocode(self, query: str) -> tuple[float, float] | None:
        if not query or not query.strip():
            return None

        # Rate-limit: wait until 1.1 s have passed since last call.
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        try:
            with httpx.Client(timeout=10.0, headers=self._headers) as client:
                resp = client.get(
                    f"{self._base_url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "limit": 1,
                        "countrycodes": self._countrycodes,
                    },
                )
                resp.raise_for_status()
        except httpx.HTTPError:
            return None
        finally:
            self._last_call = time.monotonic()

        results = resp.json()
        if not results:
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])


def get_geocoder() -> Geocoder:
    from .config import get_settings

    s = get_settings()
    if s.geocoder_provider == "nominatim":
        return NominatimGeocoder(
            user_agent=s.nominatim_user_agent,
            base_url=s.nominatim_url,
        )
    return NullGeocoder()
