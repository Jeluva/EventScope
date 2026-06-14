from __future__ import annotations

import datetime as dt

import pytest

from eventscope.dedup.deduplicator import Deduplicator, cluster_id_for
from eventscope.dedup.embeddings import StubEmbedder, cosine_similarity
from eventscope.extraction.schema import ExtractedEvent


def _ev(title, day=15, hour=23, lat=-34.80, lng=-58.39, desc=""):
    return ExtractedEvent(
        title=title,
        description=desc,
        starts_at=dt.datetime(2026, 7, day, hour, tzinfo=dt.timezone.utc),
        lat=lat,
        lng=lng,
    )


def test_cosine_identical_vs_disjoint():
    e = StubEmbedder()
    assert cosine_similarity(e.embed("noche de jazz"), e.embed("noche de jazz")) == pytest.approx(1.0)
    assert cosine_similarity(e.embed("jazz"), e.embed("yoga")) == 0.0


def test_near_duplicate_same_cluster():
    d = Deduplicator()
    a = d.to_candidate(_ev("Noche de Jazz en vivo", desc="concierto banda local"))
    b = d.to_candidate(_ev("Noche de Jazz en vivo", desc="concierto banda local", lng=-58.3905))
    d.assign_clusters([a, b])
    assert a.cluster_id == b.cluster_id


def test_different_events_different_clusters():
    d = Deduplicator()
    a = d.to_candidate(_ev("Noche de Jazz en vivo"))
    b = d.to_candidate(_ev("Clase de Yoga matutina", day=20, hour=9, lat=-34.70, lng=-58.30))
    d.assign_clusters([a, b])
    assert a.cluster_id != b.cluster_id


def test_same_title_far_apart_not_merged():
    # Same title + time but different place (>geo tolerance) → distinct events.
    d = Deduplicator()
    a = d.to_candidate(_ev("Recital", lat=-34.80, lng=-58.39))
    b = d.to_candidate(_ev("Recital", lat=-34.60, lng=-58.38))
    d.assign_clusters([a, b])
    assert a.cluster_id != b.cluster_id


def test_cluster_id_deterministic():
    assert cluster_id_for(_ev("Noche de Jazz")) == cluster_id_for(_ev("noche de  jazz"))
