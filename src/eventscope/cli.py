"""EventScope CLI.

    eventscope init-db
    eventscope scrapers
    eventscope serve [--host HOST --port PORT]
    eventscope ingest [--source NAME] [--dry-run]
    eventscope enrich [--seed URL [URL ...]]
    eventscope purge  [--days N] [--dry-run]
    eventscope status
"""
from __future__ import annotations

import argparse
import logging
import sys

# Fix Windows console encoding (cp1252 chokes on arrows, emoji, etc.)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eventscope")
    sub = parser.add_subparsers(dest="command", required=True)

    # init-db
    sub.add_parser("init-db", help="create tables from ORM metadata")

    # scrapers
    sub.add_parser("scrapers", help="list registered scrapers")

    # serve
    serve = sub.add_parser("serve", help="run the FastAPI dev server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    # ingest
    ingest = sub.add_parser("ingest", help="run scrapers and push events through the pipeline")
    ingest.add_argument(
        "--source", metavar="NAME",
        help="scraper name to run (default: all discovery scrapers)",
    )
    ingest.add_argument(
        "--dry-run", action="store_true",
        help="fetch + extract but do NOT write to the database",
    )

    # enrich
    enrich = sub.add_parser("enrich", help="resolve harvested Instagram permalinks via oEmbed")
    enrich.add_argument(
        "--seed", metavar="URL", nargs="+", default=[],
        help="additional Instagram permalink(s) to resolve",
    )

    # purge
    purge_p = sub.add_parser("purge", help="mark stale events as cancelled")
    purge_p.add_argument(
        "--days", type=int, default=7,
        help="events whose start time is more than N days in the past get cancelled (default: 7)",
    )
    purge_p.add_argument("--dry-run", action="store_true", help="report count without writing")

    # status
    sub.add_parser("status", help="print a summary of the database contents")

    args = parser.parse_args(argv)

    if args.command == "init-db":
        return _cmd_init_db()
    if args.command == "scrapers":
        return _cmd_scrapers()
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "enrich":
        return _cmd_enrich(args)
    if args.command == "purge":
        return _cmd_purge(args)
    if args.command == "status":
        return _cmd_status()
    return 0


# ─── implementations ──────────────────────────────────────────────────────────

def _cmd_init_db() -> int:
    from .db import init_db
    init_db()
    print("Database initialized.")
    return 0


def _cmd_scrapers() -> int:
    from .scrapers import list_scrapers, get_scraper
    from .scrapers.base import _REGISTRY
    for name in list_scrapers():
        cls = _REGISTRY[name]
        kind = "discovery" if cls.discovery else "enrichment"
        print(f"  {name:<25} [{kind}]")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    uvicorn.run(
        "eventscope.api.main:app",
        host=args.host, port=args.port, reload=True,
    )
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from .db import session_scope
    from .pipeline import run_items
    from .scrapers import list_scrapers, get_scraper
    from .scrapers.base import _REGISTRY

    # Determine which scrapers to run
    if args.source:
        names = [args.source]
    else:
        names = [n for n in list_scrapers() if _REGISTRY[n].discovery]

    if not names:
        print("No discovery scrapers found.")
        return 1

    total_raw = total_events = total_rejected = 0

    for name in names:
        print(f"\n> {name}")
        try:
            scraper = get_scraper(name)
            items = scraper.scrape()
        except Exception as exc:
            log.error("  fetch failed: %s", exc)
            continue

        print(f"  fetched {len(items)} item(s)")

        if args.dry_run:
            print("  [dry-run] skipping DB write")
            continue

        with session_scope() as session:
            result = run_items(session, items)
            session.commit()

        print(f"  raw_stored={result.raw_stored}  events_upserted={result.events_upserted}  rejected={result.rejected}")
        for reason in result.rejections:
            log.debug("    rejected: %s", reason)

        total_raw += result.raw_stored
        total_events += result.events_upserted
        total_rejected += result.rejected

    if not args.dry_run:
        print(f"\nTotal: raw_stored={total_raw}  events_upserted={total_events}  rejected={total_rejected}")
    return 0


def _cmd_enrich(args: argparse.Namespace) -> int:
    from .db import session_scope
    from .pipeline import enrich_from_instagram

    with session_scope() as session:
        result = enrich_from_instagram(session, seed_permalinks=args.seed or None)
        session.commit()

    print(f"Instagram enrichment: events_upserted={result.events_upserted}  rejected={result.rejected}")
    return 0


def _cmd_purge(args: argparse.Namespace) -> int:
    from .db import session_scope
    from .pipeline import purge_stale_events

    with session_scope() as session:
        count = purge_stale_events(session, days=args.days, dry_run=args.dry_run)
        if not args.dry_run:
            session.commit()

    label = "[dry-run] would cancel" if args.dry_run else "cancelled"
    print(f"Purge: {label} {count} event(s) older than {args.days} day(s).")
    return 0


def _cmd_status() -> int:
    from sqlalchemy import func, select, text
    from .db import session_scope
    from .models import Event, RawEvent

    with session_scope() as session:
        total_raw = session.scalar(select(func.count()).select_from(RawEvent)) or 0
        total_events = session.scalar(select(func.count()).select_from(Event)) or 0
        active = session.scalar(
            select(func.count()).select_from(Event).where(Event.status == "active")
        ) or 0
        no_coords = session.scalar(
            select(func.count()).select_from(Event).where(
                Event.lat.is_(None), Event.status == "active"
            )
        ) or 0

        print(f"\nEventScope status")
        print(f"  raw_events  : {total_raw}")
        print(f"  events      : {total_events}  (active: {active})")
        print(f"  sin coords  : {no_coords} activos sin lat/lng (no aparecen en el mapa)")

        # Per-source breakdown
        rows = session.execute(
            select(Event.source, func.count().label("n"))
            .where(Event.status == "active")
            .group_by(Event.source)
            .order_by(text("n DESC"))
        ).all()
        if rows:
            print("\n  Por fuente:")
            for source, n in rows:
                print(f"    {source:<30} {n}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
