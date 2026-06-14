"""Eventbrite — official API (the docx's primary, lowest-risk source).

``parse`` operates on the JSON the Eventbrite API returns, so it is fully
fixture-testable. ``fetch`` calls the live API only when a token is configured.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from .base import BaseScraper, ScrapedItem, register

API_BASE = "https://www.eventbriteapi.com/v3"


@register
class EventbriteScraper(BaseScraper):
    name = "eventbrite"
    discovery = True

    def parse(self, raw: dict[str, Any]) -> list[ScrapedItem]:
        items: list[ScrapedItem] = []
        for ev in raw.get("events", []):
            ext_id = str(ev.get("id")) if ev.get("id") is not None else None
            name = (ev.get("name") or {}).get("text") or ""
            summary = (ev.get("description") or {}).get("text") or ev.get("summary") or ""
            url = ev.get("url") or f"{API_BASE}/events/{ext_id}"

            hints: dict[str, Any] = {}
            if ev.get("start", {}).get("utc"):
                hints["starts_at"] = ev["start"]["utc"]
            if ev.get("end", {}).get("utc"):
                hints["ends_at"] = ev["end"]["utc"]
            if "is_free" in ev:
                hints["is_free"] = bool(ev["is_free"])
            venue = ev.get("venue") or {}
            if venue:
                hints["venue_name"] = venue.get("name")
                addr = venue.get("address") or {}
                hints["address"] = addr.get("localized_address_display")
                if addr.get("latitude") and addr.get("longitude"):
                    hints["lat"] = float(addr["latitude"])
                    hints["lng"] = float(addr["longitude"])

            text = "\n".join(part for part in (name, summary) if part)
            items.append(
                ScrapedItem(
                    source="eventbrite",
                    source_url=url,
                    raw_text=text,
                    external_id=ext_id,
                    image_url=(ev.get("logo") or {}).get("url"),
                    hints=hints,
                    payload=ev,
                )
            )
        return items

    def fetch(self) -> dict[str, Any]:  # pragma: no cover - live path
        token = self.options.get("token") or get_settings().eventbrite_token
        if not token:
            raise RuntimeError("eventbrite: no API token configured")
        params = {
            "location.latitude": self.options.get("lat", get_settings().pilot_lat),
            "location.longitude": self.options.get("lng", get_settings().pilot_lng),
            "location.within": f"{int(self.options.get('radius_km', get_settings().pilot_radius_km))}km",
            "expand": "venue,logo",
        }
        with self._client(headers={"Authorization": f"Bearer {token}"}) as client:
            resp = client.get(f"{API_BASE}/events/search/", params=params)
            resp.raise_for_status()
            return resp.json()
