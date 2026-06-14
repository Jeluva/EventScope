"""Engine/session management and schema bootstrap."""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a file-based SQLite URL if needed."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        path = url[len(prefix) :]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)


def get_engine() -> Engine:
    global _engine, _SessionFactory
    if _engine is None:
        url = get_settings().database_url
        _ensure_sqlite_dir(url)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def init_db() -> None:
    """Create tables from the ORM metadata (used for SQLite/dev/tests)."""
    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Drop cached engine — primarily for tests that swap the DATABASE_URL."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _SessionFactory is not None
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
