"""FastAPI application — feeds the Mapa, Calendario and Agenda views.

Endpoints (Fase 2 of the docx):
  GET /health
  GET /events/nearby   — events within a geographic radius (Mapa)
  GET /events/range    — events within a date range (Calendario)
  GET /events/{id}     — event detail
"""
from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_engine, init_db, session_scope
from ..extraction.schema import CATEGORIES
from .. import repository
from .schemas import EventOut


def get_session() -> Session:  # FastAPI dependency
    with session_scope() as session:
        yield session


def create_app(*, create_tables: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        get_engine()
        if create_tables:
            init_db()
        yield

    app = FastAPI(
        title="EventScope API",
        version="0.1.0",
        description="Catálogo curado de eventos locales (mapa, calendario, agenda).",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/events/nearby", response_model=list[EventOut])
    def events_nearby(
        lat: float | None = Query(default=None),
        lng: float | None = Query(default=None),
        radius_km: float = Query(default=5.0, gt=0, le=200),
        category: str | None = Query(default=None),
        free_only: bool = Query(default=False),
        starts_after: dt.datetime | None = Query(default=None),
        starts_before: dt.datetime | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=500),
        session: Session = Depends(get_session),
    ) -> list[EventOut]:
        settings = get_settings()
        lat = lat if lat is not None else settings.pilot_lat
        lng = lng if lng is not None else settings.pilot_lng
        if category and category not in CATEGORIES:
            raise HTTPException(422, f"unknown category; valid: {sorted(CATEGORIES)}")
        hits = repository.events_within_radius(
            session, lat, lng, radius_km,
            starts_after=starts_after, starts_before=starts_before,
            category=category, free_only=free_only, limit=limit,
        )
        return [EventOut.from_event(h.event, h.distance_km) for h in hits]

    @app.get("/events/range", response_model=list[EventOut])
    def events_range(
        start: dt.datetime = Query(...),
        end: dt.datetime = Query(...),
        category: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=500),
        session: Session = Depends(get_session),
    ) -> list[EventOut]:
        if end < start:
            raise HTTPException(422, "end must be >= start")
        events = repository.events_in_range(session, start, end, category=category, limit=limit)
        return [EventOut.from_event(e) for e in events]

    @app.get("/events/{event_id}", response_model=EventOut)
    def event_detail(event_id: int, session: Session = Depends(get_session)) -> EventOut:
        event = repository.get_event(session, event_id)
        if event is None:
            raise HTTPException(404, "event not found")
        return EventOut.from_event(event)

    return app


app = create_app()
