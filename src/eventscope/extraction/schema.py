"""Structured output contract for LLM extraction.

This Pydantic model defines the fields the LLM must return. ``json_schema()``
feeds the provider's structured-output / JSON-Schema mode (Gemini Flash,
GPT-4o-mini, etc.) so responses are validated rather than free-parsed.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

CATEGORIES = (
    "musica",
    "arte",
    "gastronomia",
    "tech",
    "networking",
    "bienestar",
    "ferias",
    "otros",
)


class ExtractedEvent(BaseModel):
    """Normalized fields parsed from a raw event's free text."""

    title: str = Field(description="Nombre del evento, conciso.")
    description: str | None = Field(default=None, description="Resumen corto.")
    category: str = Field(default="otros", description=f"Una de: {', '.join(CATEGORIES)}")
    starts_at: dt.datetime | None = Field(default=None, description="Inicio (ISO 8601).")
    ends_at: dt.datetime | None = Field(default=None, description="Fin (ISO 8601), si se conoce.")
    is_recurring: bool = Field(default=False)
    price: str | None = Field(default=None, description="Texto de precio ('Gratis', '$5000').")
    is_free: bool = Field(default=False)
    venue_name: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    # Extractor's self-reported confidence — feeds the quality score / curation.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @classmethod
    def json_schema(cls) -> dict:
        return cls.model_json_schema()
