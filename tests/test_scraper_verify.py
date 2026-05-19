"""Credential verifiers for the GUI "Test credentials" button.

Network is mocked end-to-end. The tests pin the happy-path return shape
plus the common failure modes so a regression in either endpoint's
contract gets flagged at PR time, not the next time a user clicks Test.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from spindoctor import scraper


class _FakeResponse:
    """Minimal stand-in for ``requests.Response`` covering the bits we touch."""

    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


# ─── ScreenScraper ────────────────────────────────────────────────────────────

def test_screenscraper_blank_credentials():
    ok, msg = scraper.verify_screenscraper("", "")
    assert ok is False
    assert "required" in msg.lower()


def test_screenscraper_happy_path():
    payload = {
        "response": {
            "ssuser": {"id": "phillipr", "niveau": "1", "maxthreads": "4"},
        },
    }
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_screenscraper("phillipr", "hunter2")
    assert ok is True
    assert "phillipr" in msg
    assert "level 1" in msg
    assert "threads 4" in msg


def test_screenscraper_rejects_401():
    with patch.object(scraper, "request_get", return_value=_FakeResponse(401, {})):
        ok, msg = scraper.verify_screenscraper("u", "p")
    assert ok is False
    assert "401" in msg or "rejected" in msg.lower()


def test_screenscraper_handles_erreur_payload():
    payload = {"erreur": "Erreur de login : mauvais mot de passe"}
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_screenscraper("u", "p")
    assert ok is False
    assert "mauvais" in msg.lower() or "erreur" in msg.lower()


def test_screenscraper_handles_network_error():
    def boom(*_a, **_k):
        raise requests.ConnectionError("dns failed")

    with patch.object(scraper, "request_get", side_effect=boom):
        ok, msg = scraper.verify_screenscraper("u", "p")
    assert ok is False
    assert "network" in msg.lower()


def test_screenscraper_handles_non_json_body():
    with patch.object(
        scraper, "request_get",
        return_value=_FakeResponse(200, payload=None, text="Erreur"),
    ):
        ok, msg = scraper.verify_screenscraper("u", "p")
    assert ok is False
    assert "Erreur" in msg


# ─── TheGamesDB ───────────────────────────────────────────────────────────────

def test_thegamesdb_blank_key():
    ok, msg = scraper.verify_thegamesdb("")
    assert ok is False
    assert "required" in msg.lower()


def test_thegamesdb_happy_path():
    payload = {
        "code": 200,
        "status": "Success",
        "data": {"games": []},
        "remaining_monthly_allowance": 957,
    }
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_thegamesdb("good-key")
    assert ok is True
    assert "957" in msg


def test_thegamesdb_rejects_invalid_key_via_http():
    with patch.object(scraper, "request_get", return_value=_FakeResponse(403, {})):
        ok, msg = scraper.verify_thegamesdb("bad-key")
    assert ok is False
    assert "invalid" in msg.lower()


def test_thegamesdb_rejects_invalid_key_via_payload_code():
    payload = {"code": 403, "status": "Invalid API Key"}
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_thegamesdb("bad-key")
    assert ok is False
    assert "invalid" in msg.lower()


def test_thegamesdb_rate_limited():
    with patch.object(scraper, "request_get", return_value=_FakeResponse(429, {})):
        ok, msg = scraper.verify_thegamesdb("k")
    assert ok is False
    assert "429" in msg or "rate" in msg.lower()


def test_thegamesdb_handles_network_error():
    def boom(*_a, **_k):
        raise requests.Timeout("slow")

    with patch.object(scraper, "request_get", side_effect=boom):
        ok, msg = scraper.verify_thegamesdb("k")
    assert ok is False
    assert "network" in msg.lower()


def test_thegamesdb_handles_missing_remaining_field():
    # Some early TheGamesDB responses omit the `remaining_*` counter —
    # success path should still report OK rather than fail on KeyError.
    payload = {"code": 200, "data": {"games": []}}
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_thegamesdb("k")
    assert ok is True
    assert msg == "OK"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
