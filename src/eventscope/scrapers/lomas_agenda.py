"""Scraper para la Agenda de la Comunidad de Lomas de Zamora.

API: https://apiform.lomasdezamora.gov.ar/api/ActividadesAnual
Devuelve lista JSON con campos: id, titulo, fecha, horario, descripcion,
coordenadas, lugar, direccion, localidad, tipo, categoria, inscripcionOnline.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .base import BaseScraper, ScrapedItem, register

_API_URL = "https://apiform.lomasdezamora.gov.ar/api/ActividadesAnual?noCache=true"
_SOURCE_URL = "https://lomasdezamora.gov.ar/agenda-de-la-comunidad"


def _parse_coords(raw: str | None) -> tuple[float, float] | None:
    """Parse '\t,-34.73...' or '-58.39...\t,-34.73...' into (lat, lng)."""
    if not raw:
        return None
    # Remove tabs and spaces, split on comma
    clean = raw.replace("\t", "").strip()
    parts = [p.strip() for p in clean.split(",") if p.strip()]
    if len(parts) == 2:
        try:
            a, b = float(parts[0]), float(parts[1])
            # Coords for GBA: lat ~ -34.x, lng ~ -58.x
            if -90 <= a <= 0 and -90 <= b <= 0:
                lat, lng = (a, b) if a > b else (b, a)
                return lat, lng
        except ValueError:
            pass
    return None


def _parse_horario(fecha_str: str, horario: str) -> dt.datetime | None:
    """Convert '2026-06-15' + '20hs' / '18:30hs' into a UTC datetime."""
    if not fecha_str:
        return None
    horario = re.sub(r"hs.*", "", horario, flags=re.I).strip()  # "20" or "18:30"
    time_str = horario if ":" in horario else f"{horario}:00"
    try:
        return dt.datetime.fromisoformat(f"{fecha_str}T{time_str}:00").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        try:
            return dt.datetime.fromisoformat(fecha_str).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def _parse_item(item: dict[str, Any]) -> ScrapedItem:
    titulo = (item.get("titulo") or "").strip()
    fecha = (item.get("fecha") or "").split("T")[0]   # "2026-06-15"
    horario = (item.get("horario") or "").strip()      # "20hs"
    descripcion = (item.get("descripcion") or "").strip()
    lugar = (item.get("lugar") or "").strip().replace("\t", "")
    direccion = (item.get("direccion") or "").strip()
    localidad = (item.get("localidad") or "").strip()
    tipo = (item.get("tipo") or "").strip()
    categoria = (item.get("categoria") or "").strip()
    ig_url = (item.get("inscripcionOnline") or "").strip()

    coords = _parse_coords(item.get("coordenadas"))
    lat = coords[0] if coords else None
    lng = coords[1] if coords else None

    address = ", ".join(filter(None, [direccion, localidad]))

    raw_text_parts = [titulo]
    if tipo or categoria:
        raw_text_parts.append(f"Tipo: {tipo} / {categoria}")
    if fecha:
        raw_text_parts.append(f"Fecha: {fecha} {horario}".strip())
    if descripcion:
        raw_text_parts.append(descripcion)
    if address:
        raw_text_parts.append(f"Lugar: {lugar} - {address}" if lugar else address)

    ig_links = [ig_url] if ig_url and "instagram.com" in ig_url else []

    return ScrapedItem(
        source="gov:lomas",
        source_url=_SOURCE_URL,
        external_id=str(item["id"]),
        raw_text="\n".join(raw_text_parts),
        hints={
            "starts_at": _parse_horario(fecha, horario),
            "date_text": f"{fecha} {horario}".strip(),
            "location_text": f"{lugar} - {address}".strip(" -") if lugar or address else None,
            "lat": lat,
            "lng": lng,
        },
        payload={
            "instagram_permalinks": ig_links,
        },
    )


@register
class LomasAgendaScraper(BaseScraper):
    """Agenda de la Comunidad — Municipio de Lomas de Zamora (REST API)."""

    name = "lomas_agenda"
    discovery = True

    def parse(self, raw: str | bytes) -> list[ScrapedItem]:
        import json
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        return [_parse_item(item) for item in data if item.get("titulo")]

    def fetch(self) -> str:  # pragma: no cover
        import json
        with self._client(verify=False) as client:
            resp = client.get(_API_URL)
            resp.raise_for_status()
            return resp.text
