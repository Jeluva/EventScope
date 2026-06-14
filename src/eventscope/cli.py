"""Minimal CLI: bootstrap the DB, list scrapers, and run the dev API.

    eventscope init-db
    eventscope scrapers
    eventscope serve [--host 0.0.0.0 --port 8000]
"""
from __future__ import annotations

import argparse

from .db import init_db
from .scrapers import list_scrapers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eventscope")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create tables from the ORM metadata")
    sub.add_parser("scrapers", help="list registered scrapers")
    serve = sub.add_parser("serve", help="run the FastAPI dev server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "init-db":
        init_db()
        print("Database initialized.")
    elif args.command == "scrapers":
        for name in list_scrapers():
            print(name)
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("eventscope.api.main:app", host=args.host, port=args.port, reload=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
