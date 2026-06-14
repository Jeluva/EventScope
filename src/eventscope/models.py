"""SQLAlchemy 2.0 ORM models — the source of truth for the schema.

Geometry is stored as plain ``lat``/``lng`` float columns here so the models
work identically on SQLite (offline dev/tests) and Postgres. In production the
``geom`` PostGIS column (see db/schema.sql) is maintained for ``ST_DWithin``
radius queries; the repository layer falls back to a bounding-box + haversine
query when PostGIS is unavailable.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class RawEvent(Base):
    """Immutable landing zone: exactly what a scraper saw, pre-LLM."""

    __tablename__ = "raw_events"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_raw_source_extid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(256))
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    scraped_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    events: Mapped[list[Event]] = relationship(back_populates="raw_event")


class Event(Base):
    """Normalized, deduplicated, geocoded event that feeds the API."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64))
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    price: Mapped[str | None] = mapped_column(String(64))
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    venue_name: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    # Provenance is first-class: the app surfaces a source icon per event.
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)

    # Lifecycle / quality
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    dedup_cluster_id: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_event_id: Mapped[int | None] = mapped_column(ForeignKey("raw_events.id"))
    last_verified_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    raw_event: Mapped[RawEvent | None] = relationship(back_populates="events")


class UserInteraction(Base):
    """Feedback signal for the recommendation engine (Agenda > Recomendados)."""

    __tablename__ = "user_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # saved|going|attended|dismissed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
