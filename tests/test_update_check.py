"""Tests for spindoctor.update_check.

Headless on every platform: the GitHub HTTP call is replaced via
monkeypatching, so the suite never actually hits api.github.com.
"""
from __future__ import annotations

import urllib.error

import pytest

from spindoctor import update_check


# ─── _parse_version ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1.4.0", (1, 4, 0)),
    ("v1.4.0", (1, 4, 0)),
    ("v1.4.0-rc1", (1, 4, 0)),     # pre-release qualifier dropped
    ("v1.4", (1, 4)),
    ("v1.4.0+build.5", (1, 4, 0)), # build metadata dropped
    ("0.1.0", (0, 1, 0)),
])
def test_parse_version_accepts_semver_ish(raw, expected):
    assert update_check._parse_version(raw) == expected


@pytest.mark.parametrize("raw", ["", "rolling", "garbage", "v"])
def test_parse_version_rejects_unparseable(raw):
    assert update_check._parse_version(raw) is None


# ─── is_newer ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("latest,current,expected", [
    # Strictly newer.
    ("v1.4.0", "1.3.0", True),
    ("v2.0.0", "v1.99.99", True),
    ("v1.4.1", "v1.4", True),       # patch bump beats no-patch baseline
    # Same version — no notification.
    ("v1.4.0", "1.4.0", False),
    ("v1.4", "v1.4.0", False),       # implicit zero matches explicit zero
    # Older — no notification (e.g. user installed a dev build).
    ("v1.3.0", "1.4.0", False),
    # Unparseable on either side: degrade gracefully to "no notify".
    ("rolling", "1.4.0", False),
    ("v1.4.0", "garbage", False),
])
def test_is_newer(latest, current, expected):
    assert update_check.is_newer(latest, current) is expected


# ─── check_for_update ─────────────────────────────────────────────────────────

def test_check_for_update_returns_result_when_newer(monkeypatch):
    monkeypatch.delenv(update_check._DISABLE_ENV, raising=False)
    monkeypatch.setattr(
        update_check, "fetch_latest_release",
        lambda **_kw: ("v1.4.0", "https://example/v1.4.0"),
    )
    result = update_check.check_for_update("1.3.0")
    assert result is not None
    assert result.newer_available is True
    assert result.latest == "v1.4.0"
    assert result.current == "1.3.0"
    assert result.release_url == "https://example/v1.4.0"


def test_check_for_update_returns_result_when_up_to_date(monkeypatch):
    monkeypatch.delenv(update_check._DISABLE_ENV, raising=False)
    monkeypatch.setattr(
        update_check, "fetch_latest_release",
        lambda **_kw: ("v1.3.0", "https://example/v1.3.0"),
    )
    result = update_check.check_for_update("1.3.0")
    assert result is not None
    assert result.newer_available is False


def test_check_for_update_returns_none_on_network_failure(monkeypatch):
    monkeypatch.delenv(update_check._DISABLE_ENV, raising=False)

    def boom(**_kw):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(update_check, "fetch_latest_release", boom)
    # Network failures must never raise out — a cabinet on a bad
    # connection should still launch cleanly.
    assert update_check.check_for_update("1.3.0") is None


def test_check_for_update_returns_none_on_unparseable_tag(monkeypatch):
    monkeypatch.delenv(update_check._DISABLE_ENV, raising=False)
    monkeypatch.setattr(
        update_check, "fetch_latest_release",
        lambda **_kw: ("rolling-release", "https://example/rolling"),
    )
    # GitHub allows arbitrary tag strings — if the project ever ships
    # a "rolling" or build-hash tag, fail closed instead of crying
    # wolf about an "update".
    assert update_check.check_for_update("1.3.0") is None


def test_check_for_update_respects_env_opt_out(monkeypatch):
    monkeypatch.setenv(update_check._DISABLE_ENV, "1")
    # When the user explicitly opts out, callers need to distinguish
    # "skipped" from "couldn't reach GitHub" so they can show the
    # right status message.
    with pytest.raises(update_check.UpdateCheckDisabled):
        update_check.check_for_update("1.3.0")
