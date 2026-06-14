"""Geospatial helpers. Pure-Python so radius search works on SQLite and Postgres
alike; production can swap in PostGIS ST_DWithin for performance at scale."""
from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lng, max_lng) enclosing the radius.

    Used as a cheap SQL pre-filter before the exact haversine refinement.
    """
    lat_delta = radius_km / 111.0  # ~111 km per degree of latitude
    # Degrees of longitude shrink toward the poles; guard the cos near ±90°.
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    lng_delta = radius_km / (111.0 * cos_lat)
    return (lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta)
