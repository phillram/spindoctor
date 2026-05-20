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


def test_screenscraper_403_surfaces_response_body():
    """A 403 with a useful upstream message must reach the UI dialog."""
    body = '{"erreur":"Erreur de developpeur : devid/devpassword incorrects"}'
    with patch.object(
        scraper, "request_get",
        return_value=_FakeResponse(403, payload=None, text=body),
    ):
        ok, msg = scraper.verify_screenscraper("u", "p")
    assert ok is False
    assert "403" in msg
    # Body snippet must be appended so the cabinet owner can see the real
    # ScreenScraper error without trawling the log file.
    assert "devid" in msg.lower() or "developpeur" in msg.lower()


def test_screenscraper_verify_uses_custom_devid():
    """A user-overridden devid must be sent in the request params."""
    captured: dict = {}

    def fake_get(url, *, params=None, **_kw):
        captured["params"] = dict(params or {})
        return _FakeResponse(403, payload=None, text="")

    with patch.object(scraper, "request_get", side_effect=fake_get):
        scraper.verify_screenscraper(
            "u", "p", devid="my-real-devid", devpassword="my-real-devpw",
        )
    assert captured["params"]["devid"] == "my-real-devid"
    assert captured["params"]["devpassword"] == "my-real-devpw"


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


# ``verify_thegamesdb`` short-circuits keys shorter than 8 chars as
# obviously-malformed (saves a round-trip and gives the user a clearer
# message than TheGamesDB's generic error). Tests that need to drive the
# HTTP / payload-error branches use 8+ char keys.
_GOOD_KEY = "realapikey"


def test_thegamesdb_happy_path():
    payload = {
        "code": 200,
        "status": "Success",
        "data": {"games": []},
        "remaining_monthly_allowance": 957,
    }
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is True
    assert "957" in msg


def test_thegamesdb_rejects_invalid_key_via_http():
    with patch.object(scraper, "request_get", return_value=_FakeResponse(403, {})):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is False
    assert "invalid" in msg.lower()


def test_thegamesdb_rejects_invalid_key_via_payload_code():
    payload = {"code": 403, "status": "Invalid API Key"}
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is False
    assert "invalid" in msg.lower()


def test_thegamesdb_rate_limited():
    with patch.object(scraper, "request_get", return_value=_FakeResponse(429, {})):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is False
    assert "429" in msg or "rate" in msg.lower()


def test_thegamesdb_403_surfaces_response_body():
    body = '{"code":403,"status":"Invalid API key — please reissue"}'
    with patch.object(
        scraper, "request_get",
        return_value=_FakeResponse(403, payload=None, text=body),
    ):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is False
    assert "invalid" in msg.lower()
    assert "reissue" in msg.lower()


def test_thegamesdb_handles_network_error():
    def boom(*_a, **_k):
        raise requests.Timeout("slow")

    with patch.object(scraper, "request_get", side_effect=boom):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is False
    assert "network" in msg.lower()


def test_thegamesdb_rejects_short_key_without_http():
    """A key that's obviously too short never reaches the API."""
    def boom(*_a, **_k):  # pragma: no cover - should not be hit
        raise AssertionError("request_get should not be called for short keys")

    with patch.object(scraper, "request_get", side_effect=boom):
        ok, msg = scraper.verify_thegamesdb("bad-key")  # 7 chars
    assert ok is False
    assert "malformed" in msg.lower()


def test_thegamesdb_rejects_whitespace_key_without_http():
    def boom(*_a, **_k):  # pragma: no cover - should not be hit
        raise AssertionError("request_get should not be called for whitespace keys")

    with patch.object(scraper, "request_get", side_effect=boom):
        ok, msg = scraper.verify_thegamesdb("has spaces here")
    assert ok is False
    assert "malformed" in msg.lower()


def test_thegamesdb_rejects_suspicious_200_without_allowance():
    """200 + no ``*allowance*`` field = anonymous / unauthenticated.

    TheGamesDB returns OK + public data for some invalid keys; the
    verifier conservatively treats those as failures so the Setup
    tab's Test credentials button can't lie about a missing key.
    """
    payload = {"code": 200, "data": {"games": []}}
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is False
    assert "suspicious" in msg.lower() or "allowance" in msg.lower()


def test_thegamesdb_accepts_alternate_allowance_field():
    """Any field containing ``allowance`` proves the key was authenticated."""
    payload = {
        "code": 200,
        "data": {"games": []},
        "allowance_refresh_timer": 123,
    }
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_thegamesdb(_GOOD_KEY)
    assert ok is True
    assert msg == "OK"


def test_screenscraper_failure_message_includes_devid():
    """A 403 must surface the devid so the user can rule out a stale default."""
    with patch.object(
        scraper, "request_get",
        return_value=_FakeResponse(403, payload=None, text="Erreur de login"),
    ):
        ok, msg = scraper.verify_screenscraper(
            "u", "p", devid="custom-devid", devpassword="custom-pw",
        )
    assert ok is False
    assert "devid=custom-devid" in msg
    # devpassword must never appear in any output surface.
    assert "custom-pw" not in msg


def test_screenscraper_success_message_includes_devid():
    payload = {"response": {"ssuser": {"id": "phillipr", "niveau": "1"}}}
    with patch.object(scraper, "request_get", return_value=_FakeResponse(200, payload)):
        ok, msg = scraper.verify_screenscraper(
            "phillipr", "pw", devid="SpinDoctor", devpassword="SpinDoctor",
        )
    assert ok is True
    assert "devid=SpinDoctor" in msg


# ─── logger setup ─────────────────────────────────────────────────────────────

def test_scraper_log_handler_is_idempotent():
    """Repeated verify clicks must not stack RotatingFileHandlers.

    The first call attaches one; every subsequent call should be a no-op,
    otherwise the same log line ends up duplicated 10x after a few clicks
    and the file rotates faster than its budget intends.
    """
    # Reset state so this test is order-independent.
    scraper._LOG_HANDLER_INSTALLED = False
    for h in list(scraper.scraper_logger.handlers):
        scraper.scraper_logger.removeHandler(h)

    scraper._install_scraper_log_handler()
    after_first = len(scraper.scraper_logger.handlers)
    scraper._install_scraper_log_handler()
    scraper._install_scraper_log_handler()
    after_third = len(scraper.scraper_logger.handlers)

    # One handler max, regardless of how many times we re-enter.
    assert after_first <= 1
    assert after_third == after_first


def test_redact_params_masks_secrets():
    redacted = scraper._redact_params({
        "devid": "SpinDoctor",
        "devpassword": "secret-app-pw",
        "ssid": "phillipr",
        "sspassword": "secret-user-pw",
        "apikey": "abc123",
        "softname": "SpinDoctor",
    })
    # Non-secret fields pass through unchanged.
    assert redacted["devid"] == "SpinDoctor"
    assert redacted["ssid"] == "phillipr"
    assert redacted["softname"] == "SpinDoctor"
    # Every secret-bearing field is masked.
    assert redacted["devpassword"] == "***"
    assert redacted["sspassword"] == "***"
    assert redacted["apikey"] == "***"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
