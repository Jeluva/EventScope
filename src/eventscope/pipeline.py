"""End-to-end ingestion pipeline.

    ScrapedItem(s)
      → persist raw_events (immutable, dedup on source+external_id)
      → LLM extraction (structured fields)
      → validation (must have title + a future-enough date)
      → dedup clustering (embeddings + date/geo)
      → upsert into normalized `events`

Runs fully offline with the stub extractor/embedder; the same code path uses
real providers when configured.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .dedup.deduplicator import DedupCandidate, Deduplicator
from .extraction.llm import Extractor, get_extractor
from .extraction.schema import ExtractedEvent
from .geocoding import Geocoder, get_geocoder
from .models import Event, RawEvent
from .scrapers.base import ScrapedItem


@dataclass
class PipelineResult:
    raw_stored: int = 0
    extracted: int = 0
    rejected: int = 0
    events_upserted: int = 0
    clusters_merged: int = 0
    rejections: list[str] = field(default_factory=list)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(d: dt.datetime) -> dt.datetime:
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def quality_score(ev: ExtractedEvent) -> float:
    """0..1 score from completeness + extractor confidence (drives curation)."""
    score = 0.4 * ev.confidence
    if ev.starts_at:
        score += 0.25
    if ev.lat is not None and ev.lng is not None:
        score += 0.2
    if ev.venue_name or ev.address:
        score += 0.15
    return round(min(score, 1.0), 3)


def persist_raw(session: Session, item: ScrapedItem) -> RawEvent:
    """Insert a raw_events row, or return the existing one (idempotent)."""
    if item.external_id is not None:
        existing = session.scalar(
            select(RawEvent).where(
                RawEvent.source == item.source, RawEvent.external_id == item.external_id
            )
        )
        if existing is not None:
            return existing
    raw = RawEvent(
        source=item.source,
        source_url=item.source_url,
        external_id=item.external_id,
        raw_payload={"raw_text": item.raw_text, "hints": item.hints, **item.payload},
    )
    session.add(raw)
    session.flush()
    return raw


def validate(ev: ExtractedEvent, now: dt.datetime, *, max_past_hours: float = 6.0) -> str | None:
    """Return a rejection reason, or None if the event is publishable."""
    if not ev.title:
        return "missing title"
    if ev.starts_at is None:
        return "missing start date"
    if _aware(ev.starts_at) < now - dt.timedelta(hours=max_past_hours):
        return "event is in the past"
    return None


def _existing_candidates(session: Session, dedup: Deduplicator) -> list[DedupCandidate]:
    cands: list[DedupCandidate] = []
    for ev in session.scalars(select(Event).where(Event.status == "active")):
        extracted = ExtractedEvent(
            title=ev.title,
            description=ev.description,
            starts_at=ev.starts_at,
            venue_name=ev.venue_name,
            lat=ev.lat,
            lng=ev.lng,
        )
        cand = dedup.to_candidate(extracted)
        cand.cluster_id = ev.dedup_cluster_id
        cands.append(cand)
    return cands


def _maybe_geocode(ev: ExtractedEvent, geocoder: Geocoder) -> None:
    """Fill lat/lng from address/venue when the source gave none."""
    if ev.lat is not None and ev.lng is not None:
        return
    for query in (ev.address, ev.venue_name):
        if not query:
            continue
        coords = geocoder.geocode(query)
        if coords:
            ev.lat, ev.lng = coords
            return


def run_items(
    session: Session,
    items: list[ScrapedItem],
    *,
    extractor: Extractor | None = None,
    deduplicator: Deduplicator | None = None,
    geocoder: Geocoder | None = None,
    now: dt.datetime | None = None,
) -> PipelineResult:
    extractor = extractor or get_extractor()
    dedup = deduplicator or Deduplicator()
    geocoder = geocoder or get_geocoder()
    now = now or _utcnow()
    result = PipelineResult()

    existing = _existing_candidates(session, dedup)
    existing_clusters = {c.cluster_id for c in existing if c.cluster_id}

    # Stage 1-3: raw → extract → validate, collecting valid (item, event) pairs.
    valid: list[tuple[ScrapedItem, RawEvent, ExtractedEvent]] = []
    for item in items:
        raw = persist_raw(session, item)
        result.raw_stored += 1
        extracted = extractor.extract(item)
        if extracted is None:
            result.rejected += 1
            result.rejections.append(f"{item.source}: no extraction")
            continue
        result.extracted += 1
        _maybe_geocode(extracted, geocoder)
        reason = validate(extracted, now)
        if reason:
            result.rejected += 1
            result.rejections.append(f"{item.source}: {reason}")
            continue
        valid.append((item, raw, extracted))
        raw.processed = True

    # Stage 4: dedup clustering against existing + within the batch.
    candidates = [dedup.to_candidate(ev) for _, _, ev in valid]
    dedup.assign_clusters(candidates, existing=existing)

    # Stage 5: upsert into events (one row per cluster; reuse if cluster exists).
    for (item, raw, extracted), cand in zip(valid, candidates):
        starts_at = _aware(extracted.starts_at) if extracted.starts_at else now
        existing_event = session.scalar(
            select(Event).where(Event.dedup_cluster_id == cand.cluster_id)
        )
        if existing_event is not None:
            existing_event.last_verified_at = now
            if cand.cluster_id in existing_clusters:
                result.clusters_merged += 1
            continue

        session.add(
            Event(
                title=extracted.title,
                description=extracted.description,
                category=extracted.category,
                starts_at=starts_at,
                ends_at=_aware(extracted.ends_at) if extracted.ends_at else None,
                is_recurring=extracted.is_recurring,
                price=extracted.price,
                is_free=extracted.is_free,
                venue_name=extracted.venue_name,
                address=extracted.address,
                lat=extracted.lat,
                lng=extracted.lng,
                source=item.source,
                source_url=item.source_url,
                image_url=item.image_url,
                quality_score=quality_score(extracted),
                dedup_cluster_id=cand.cluster_id,
                raw_event_id=raw.id,
                last_verified_at=now,
            )
        )
        existing_clusters.add(cand.cluster_id)
        result.events_upserted += 1

    session.flush()
    return result


# ─── Instagram enrichment loop ───────────────────────────────────────────────
# oEmbed cannot discover posts, so IG runs as a SECOND pass keyed on permalinks
# harvested by the venue/government scrapers (stored in raw_events.payload) plus
# an optional manual seed list. This is the join between "harvest" and "resolve".

def collect_harvested_permalinks(session: Session) -> list[str]:
    """De-duplicated Instagram permalinks found in stored raw_events payloads."""
    seen: dict[str, None] = {}
    for raw in session.scalars(select(RawEvent)):
        for permalink in (raw.raw_payload or {}).get("instagram_permalinks", []):
            seen.setdefault(permalink, None)
    return list(seen)


def _already_resolved_shortcodes(session: Session) -> set[str]:
    return {
        ext_id
        for ext_id in session.scalars(
            select(RawEvent.external_id).where(RawEvent.source == "instagram")
        )
        if ext_id
    }


def enrich_from_instagram(
    session: Session,
    *,
    resolver=None,
    seed_permalinks: list[str] | None = None,
    now: dt.datetime | None = None,
    **run_kwargs,
) -> PipelineResult:
    """Resolve harvested + seed permalinks via Instagram oEmbed, then ingest them.

    ``resolver(permalinks) -> list[ScrapedItem]`` is injectable so tests pass a
    fake (offline). The default uses the live oEmbed enricher (token or iframe
    fallback). Permalinks already resolved into raw_events are skipped.
    """
    from .scrapers.instagram_oembed import InstagramOembedScraper, shortcode_from_permalink

    permalinks = list(dict.fromkeys((seed_permalinks or []) + collect_harvested_permalinks(session)))
    done = _already_resolved_shortcodes(session)
    pending = [p for p in permalinks if (shortcode_from_permalink(p) or p) not in done]
    if not pending:
        return PipelineResult()

    if resolver is None:  # pragma: no cover - live path
        resolver = lambda pls: InstagramOembedScraper().enrich(pls)  # noqa: E731
    items = resolver(pending)
    return run_items(session, items, now=now, **run_kwargs)


# ─── Stale event purge ────────────────────────────────────────────────────────

def purge_stale_events(
    session: Session,
    *,
    days: int = 7,
    dry_run: bool = False,
    now: dt.datetime | None = None,
) -> int:
    """Mark active events whose start time is > ``days`` days in the past as cancelled.

    Returns the number of events affected. When ``dry_run=True`` the session is
    not modified — the count is still returned so the CLI can report it.
    """
    cutoff = _aware(now or _utcnow()) - dt.timedelta(days=days)
    stale = list(
        session.scalars(
            select(Event).where(
                Event.status == "active",
                Event.starts_at < cutoff,
            )
        )
    )
    if not dry_run:
        for ev in stale:
            ev.status = "cancelled"
        session.flush()
    return len(stale)
