"""Example Airflow DAG: one discovery scraper → ingestion pipeline.

This illustrates the docx's "un DAG por fuente" orchestration with retries,
backoff and a 0-results alert. Airflow is NOT a runtime dependency of the core
slice — the pipeline runs standalone via pytest/CLI. This file imports Airflow
lazily so the rest of the project loads without it installed.

Pattern to replicate per source (Eventbrite, each venue, each municipality):
copy this DAG, change `SCRAPER_NAME` / `SCRAPER_OPTIONS` / `schedule`.

The Instagram oEmbed enricher is intentionally NOT a discovery DAG: it runs as
a downstream task keyed on permalinks harvested by the other scrapers plus a
manual seed list (see docstring in scrapers/instagram_oembed.py).
"""
from __future__ import annotations

import datetime as dt

try:
    from airflow.decorators import dag, task
except ImportError:  # pragma: no cover - Airflow is an optional extra
    dag = task = None


SCRAPER_NAME = "eventbrite"
SCRAPER_OPTIONS: dict = {}


def _ingest_once(scraper_name: str, options: dict) -> dict:
    """Body of the DAG, importable + testable without Airflow."""
    from eventscope.db import session_scope
    from eventscope.pipeline import run_items
    from eventscope.scrapers import get_scraper

    scraper = get_scraper(scraper_name, **options)
    items = scraper.scrape()  # live fetch + parse
    if not items:
        # docx mitigation: alert when a scraper returns 0 events.
        raise ValueError(f"scraper {scraper_name!r} returned 0 items — possible breakage")
    with session_scope() as session:
        result = run_items(session, items)
    return {
        "raw_stored": result.raw_stored,
        "events_upserted": result.events_upserted,
        "rejected": result.rejected,
    }


if dag is not None:  # pragma: no cover - only when Airflow is installed

    @dag(
        dag_id=f"eventscope_ingest_{SCRAPER_NAME}",
        schedule="0 */6 * * *",  # every 6 hours
        start_date=dt.datetime(2026, 1, 1),
        catchup=False,
        default_args={
            "retries": 3,
            "retry_delay": dt.timedelta(minutes=10),
            "retry_exponential_backoff": True,
        },
        tags=["eventscope", "ingestion", SCRAPER_NAME],
    )
    def eventscope_ingest():
        @task
        def ingest() -> dict:
            return _ingest_once(SCRAPER_NAME, SCRAPER_OPTIONS)

        ingest()

    eventscope_ingest()
