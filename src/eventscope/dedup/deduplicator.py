"""Deduplication: cluster events that are "the same" across sources.

Per the docx: embeddings of title+description, cosine similarity, gated by
date proximity and geolocation. Two events join the same ``dedup_cluster_id``
when their text is similar AND they happen at (roughly) the same time AND place.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field

from ..extraction.schema import ExtractedEvent
from ..geo import haversine_km
from .embeddings import Embedder, cosine_similarity, get_embedder

_NORM_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    return _NORM_RE.sub(" ", (title or "").strip().lower())


def cluster_id_for(event: ExtractedEvent) -> str:
    """Stable id for a brand-new cluster, derived from title + date + place.

    Place is included (coarse geo bucket ~100m, or venue name) so two distinct
    same-title/same-day events at *different* venues don't collide into one id.
    Genuine duplicates still merge earlier via the fuzzy ``is_duplicate`` check.
    """
    day = event.starts_at.date().isoformat() if event.starts_at else "nodate"
    if event.lat is not None and event.lng is not None:
        place = f"{round(event.lat, 3)},{round(event.lng, 3)}"
    else:
        place = _normalize_title(event.venue_name or "")
    basis = f"{_normalize_title(event.title)}|{day}|{place}"
    return hashlib.md5(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class DedupCandidate:
    event: ExtractedEvent
    embedding: list[float] = field(default_factory=list)
    cluster_id: str | None = None


class Deduplicator:
    def __init__(
        self,
        embedder: Embedder | None = None,
        *,
        sim_threshold: float = 0.82,
        date_tolerance_hours: float = 12.0,
        geo_tolerance_km: float = 0.75,
    ) -> None:
        self.embedder = embedder or get_embedder()
        self.sim_threshold = sim_threshold
        self.date_tolerance = dt.timedelta(hours=date_tolerance_hours)
        self.geo_tolerance_km = geo_tolerance_km

    def to_candidate(self, event: ExtractedEvent) -> DedupCandidate:
        basis = f"{event.title} {event.description or ''}"
        return DedupCandidate(event=event, embedding=self.embedder.embed(basis))

    # ─── pairwise tests ──────────────────────────────────────────────────────
    def _dates_match(self, a: ExtractedEvent, b: ExtractedEvent) -> bool:
        if a.starts_at and b.starts_at:
            # Coerce to aware so DB-loaded (naive) and fresh (aware) compare.
            da = a.starts_at if a.starts_at.tzinfo else a.starts_at.replace(tzinfo=dt.timezone.utc)
            db = b.starts_at if b.starts_at.tzinfo else b.starts_at.replace(tzinfo=dt.timezone.utc)
            return abs(da - db) <= self.date_tolerance
        return True  # missing date → don't block; lean on text+geo

    def _geo_match(self, a: ExtractedEvent, b: ExtractedEvent) -> bool:
        if a.lat is not None and a.lng is not None and b.lat is not None and b.lng is not None:
            return haversine_km(a.lat, a.lng, b.lat, b.lng) <= self.geo_tolerance_km
        if a.venue_name and b.venue_name:
            return _normalize_title(a.venue_name) == _normalize_title(b.venue_name)
        return True  # no geo signal on either side → don't block

    def is_duplicate(self, a: DedupCandidate, b: DedupCandidate) -> bool:
        sim = cosine_similarity(a.embedding, b.embedding)
        if sim < self.sim_threshold:
            return False
        return self._dates_match(a.event, b.event) and self._geo_match(a.event, b.event)

    # ─── batch + incremental clustering ──────────────────────────────────────
    def assign_clusters(
        self, candidates: list[DedupCandidate], existing: list[DedupCandidate] | None = None
    ) -> list[DedupCandidate]:
        """Assign a ``cluster_id`` to each candidate, reusing an existing
        cluster when a candidate duplicates an already-stored event."""
        clustered: list[DedupCandidate] = list(existing or [])
        for cand in candidates:
            match = next((c for c in clustered if self.is_duplicate(cand, c)), None)
            cand.cluster_id = match.cluster_id if match else cluster_id_for(cand.event)
            clustered.append(cand)
        return candidates
