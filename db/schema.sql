-- EventScope — PostGIS schema (production).
-- The SQLAlchemy models in src/eventscope/models.py are the source of truth and
-- can create equivalent tables on SQLite for offline dev/tests. This file is
-- the canonical Postgres/PostGIS DDL, applied on container init.

CREATE EXTENSION IF NOT EXISTS postgis;

-- ─── raw_events ──────────────────────────────────────────────────────────────
-- Immutable landing zone: exactly what a scraper saw, before any LLM parsing.
CREATE TABLE IF NOT EXISTS raw_events (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        TEXT        NOT NULL,           -- e.g. 'eventbrite', 'venue:konex', 'gov:lomas', 'instagram'
    source_url    TEXT        NOT NULL,           -- provenance: shown as the source link/icon in the app
    external_id   TEXT,                           -- stable id within the source, when available
    raw_payload   JSONB       NOT NULL,           -- original structured/text content
    scraped_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed     BOOLEAN     NOT NULL DEFAULT FALSE,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_events_unprocessed ON raw_events (processed) WHERE processed = FALSE;

-- ─── events ──────────────────────────────────────────────────────────────────
-- Normalized, deduplicated, geocoded events that feed the API.
CREATE TABLE IF NOT EXISTS events (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title             TEXT        NOT NULL,
    description       TEXT,
    category          TEXT,                        -- musica | arte | gastronomia | tech | networking | ...
    starts_at         TIMESTAMPTZ NOT NULL,
    ends_at           TIMESTAMPTZ,
    is_recurring      BOOLEAN     NOT NULL DEFAULT FALSE,
    price             TEXT,                        -- free text ('Gratis', '$5000') normalized downstream
    is_free           BOOLEAN     NOT NULL DEFAULT FALSE,
    venue_name        TEXT,
    address           TEXT,
    lat               DOUBLE PRECISION,
    lng               DOUBLE PRECISION,
    geom              geography(Point, 4326),      -- PostGIS point for ST_DWithin radius queries
    -- provenance (first-class: the app shows where each event came from)
    source            TEXT        NOT NULL,
    source_url        TEXT        NOT NULL,
    image_url         TEXT,
    -- lifecycle / quality
    status            TEXT        NOT NULL DEFAULT 'active',   -- active | cancelled | rescheduled
    quality_score     DOUBLE PRECISION NOT NULL DEFAULT 0,
    dedup_cluster_id  TEXT,                        -- events judged "the same" share this id
    raw_event_id      BIGINT REFERENCES raw_events(id),
    last_verified_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_geom    ON events USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_events_starts  ON events (starts_at);
CREATE INDEX IF NOT EXISTS idx_events_cluster ON events (dedup_cluster_id);
CREATE INDEX IF NOT EXISTS idx_events_status  ON events (status);

-- ─── user_interactions ───────────────────────────────────────────────────────
-- Feedback signal for the recommendation engine (Agenda > Recomendados).
CREATE TABLE IF NOT EXISTS user_interactions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     TEXT        NOT NULL,
    event_id    BIGINT      NOT NULL REFERENCES events(id),
    kind        TEXT        NOT NULL,              -- saved | going | attended | dismissed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interactions_user ON user_interactions (user_id);
