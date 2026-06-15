"""Tests for geocoders — zero network (httpx monkeypatched)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from eventscope.geocoding import (
    NominatimGeocoder,
    NullGeocoder,
    StaticGeocoder,
    get_geocoder,
)


# ─── NullGeocoder ────────────────────────────────────────────────────────────

def test_null_geocoder_always_none():
    g = NullGeocoder()
    assert g.geocode("Plaza Brown, Adrogué") is None
    assert g.geocode("") is None


# ─── StaticGeocoder ──────────────────────────────────────────────────────────

def test_static_geocoder_hit_and_miss():
    g = StaticGeocoder({"Plaza Brown, Adrogué": (-34.7998, -58.3897)})
    assert g.geocode("Plaza Brown, Adrogué") == (-34.7998, -58.3897)
    assert g.geocode("  Plaza Brown, Adrogué  ") == (-34.7998, -58.3897)
    assert g.geocode("Desconocido") is None
    assert g.geocode("") is None


# ─── NominatimGeocoder ───────────────────────────────────────────────────────

_NOMINATIM_HIT = json.dumps(
    [{"lat": "-34.7998", "lon": "-58.3897", "display_name": "Plaza Brown, Adrogué"}]
)
_NOMINATIM_EMPTY = json.dumps([])


def _mock_response(body: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json.loads(body)
    resp.raise_for_status = MagicMock()
    return resp


def _patched_geocoder(**kwargs):
    return NominatimGeocoder(
        user_agent="EventScope-test/0.1",
        base_url="http://nominatim.test",
        **kwargs,
    )


@patch("eventscope.geocoding.time.sleep")  # suppress rate-limit sleep
@patch("eventscope.geocoding.time.monotonic", return_value=9999.0)
def test_nominatim_returns_coords(mock_mono, mock_sleep):
    g = _patched_geocoder()
    mock_get = MagicMock(return_value=_mock_response(_NOMINATIM_HIT))
    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(get=mock_get))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        result = g.geocode("Plaza Brown, Adrogué")

    assert result == (-34.7998, -58.3897)
    call_kwargs = mock_get.call_args
    assert "search" in call_kwargs[0][0]
    assert call_kwargs[1]["params"]["q"] == "Plaza Brown, Adrogué"
    assert call_kwargs[1]["params"]["countrycodes"] == "ar"


@patch("eventscope.geocoding.time.sleep")
@patch("eventscope.geocoding.time.monotonic", return_value=9999.0)
def test_nominatim_empty_result_returns_none(mock_mono, mock_sleep):
    g = _patched_geocoder()
    mock_get = MagicMock(return_value=_mock_response(_NOMINATIM_EMPTY))
    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(get=mock_get))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        assert g.geocode("Nowhere") is None


@patch("eventscope.geocoding.time.sleep")
@patch("eventscope.geocoding.time.monotonic", return_value=9999.0)
def test_nominatim_http_error_returns_none(mock_mono, mock_sleep):
    import httpx as _httpx

    g = _patched_geocoder()
    with patch("httpx.Client") as mock_client_cls:
        mock_ctx = MagicMock()
        mock_ctx.get.side_effect = _httpx.ConnectError("timeout")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        assert g.geocode("Plaza Brown") is None


def test_nominatim_empty_query_returns_none():
    g = _patched_geocoder()
    assert g.geocode("") is None
    assert g.geocode("   ") is None


# ─── get_geocoder() factory ──────────────────────────────────────────────────

def test_get_geocoder_default_is_null(monkeypatch):
    from eventscope.config import get_settings
    monkeypatch.setenv("EVENTSCOPE_GEOCODER_PROVIDER", "null")
    get_settings.cache_clear()
    try:
        assert isinstance(get_geocoder(), NullGeocoder)
    finally:
        get_settings.cache_clear()


def test_get_geocoder_nominatim(monkeypatch):
    from eventscope.config import get_settings
    monkeypatch.setenv("EVENTSCOPE_GEOCODER_PROVIDER", "nominatim")
    get_settings.cache_clear()
    try:
        assert isinstance(get_geocoder(), NominatimGeocoder)
    finally:
        get_settings.cache_clear()
