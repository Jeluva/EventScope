from __future__ import annotations

import json
import pathlib

import pytest

from eventscope import db
from eventscope.config import get_settings

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    path = FIXTURES / name
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("EVENTSCOPE_DATABASE_URL", url)
    monkeypatch.setenv("EVENTSCOPE_LLM_PROVIDER", "stub")
    monkeypatch.setenv("EVENTSCOPE_EMBEDDING_PROVIDER", "stub")
    get_settings.cache_clear()
    db.reset_engine()
    db.init_db()
    yield url
    db.reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def session(db_url):
    with db.session_scope() as s:
        yield s
