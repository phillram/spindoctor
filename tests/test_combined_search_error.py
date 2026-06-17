"""CombinedMetadataClient.search() error propagation and circuit-breaker helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spindoctor.scraper import (
    CombinedMetadataClient,
    GameMetadata,
    MetadataError,
    ScreenScraperClient,
    TheGamesDBClient,
)
from spindoctor.cli import _is_network_error


# ── _is_network_error ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "HTTPSConnectionPool(host='www.screenscraper.fr', port=443): Max retries exceeded with url: ... (Caused by NameResolutionError(...))",
    "ScreenScraper search failed: HTTPSConnectionPool: Max retries exceeded",
    "TheGamesDB fetch failed: getaddrinfo failed",
    "Read timed out. (read timeout=15)",
    "Connection refused",
    "Failed to establish a new connection",
    "RemoteDisconnected('Remote end closed connection without response')",
    "Connection reset by peer",
])
def test_is_network_error_matches_dns_and_connection_failures(msg):
    assert _is_network_error(msg)


@pytest.mark.parametrize("msg", [
    "ScreenScraper API error: Vous avez atteint votre quota journalier",
    "TheGamesDB API error (code 401): Invalid API key",
    "HTTP 403",
    "no match found",
    "",
])
def test_is_network_error_ignores_non_network_errors(msg):
    assert not _is_network_error(msg)


# ── CombinedMetadataClient.search() ───────────────────────────────────────────

class _AlwaysErrorSS:
    """Stand-in ScreenScraperClient whose search always raises MetadataError."""
    def search(self, game_name, system_name):
        raise MetadataError("ScreenScraper search failed: Max retries exceeded (NameResolutionError)")


class _AlwaysErrorTGDB:
    """Stand-in TheGamesDBClient whose search always raises MetadataError."""
    def search(self, game_name, system_name):
        raise MetadataError("TheGamesDB search failed: Max retries exceeded (NameResolutionError)")


class _EmptySS:
    """Stand-in that returns no results (no error)."""
    def search(self, game_name, system_name):
        return []


class _OneResultTGDB:
    """Stand-in that returns one result."""
    def search(self, game_name, system_name):
        return [GameMetadata(name="Test Game", source="thegamesdb", source_id="1")]


def _make_combined(ss, tgdb):
    client = CombinedMetadataClient.__new__(CombinedMetadataClient)
    client._ss = ss
    client._tgdb = tgdb
    client._cache = None
    return client


def test_combined_search_raises_when_both_fail():
    client = _make_combined(_AlwaysErrorSS(), _AlwaysErrorTGDB())
    with pytest.raises(MetadataError) as exc_info:
        client.search("Animal Crossing", "Nintendo Gamecube")
    msg = str(exc_info.value)
    assert "ScreenScraper" in msg
    assert "TheGamesDB" in msg
    assert "NameResolutionError" in msg


def test_combined_search_raises_when_only_ss_fails_and_tgdb_empty():
    # Both fail to return results — SS errors, TGDB returns [].
    # Should raise because there are no results AND there's an error.
    client = _make_combined(_AlwaysErrorSS(), _EmptySS())
    with pytest.raises(MetadataError) as exc_info:
        client.search("Animal Crossing", "Nintendo Gamecube")
    assert "ScreenScraper" in str(exc_info.value)


def test_combined_search_returns_tgdb_when_ss_fails_but_tgdb_has_results():
    # SS is down but TGDB has results — should succeed with TGDB results.
    client = _make_combined(_AlwaysErrorSS(), _OneResultTGDB())
    results = client.search("Animal Crossing", "Nintendo Gamecube")
    assert len(results) == 1
    assert results[0].name == "Test Game"


def test_combined_search_raises_only_ss_error_when_only_ss_configured():
    # Only SS errors out; TGDB returns empty but no error.
    client = _make_combined(_AlwaysErrorSS(), _EmptySS())
    with pytest.raises(MetadataError) as exc_info:
        client.search("Zelda", "Nintendo 64")
    # Error message mentions SS but not TGDB (TGDB had no error, just no results)
    assert "ScreenScraper" in str(exc_info.value)
    assert "TheGamesDB" not in str(exc_info.value)


# ── CombinedMetadataClient.fetch() scalar sync ────────────────────────────────

class _SSnoBG:
    """SS finds the game but has no wheel or background URL."""
    def fetch(self, game_name, system_name):
        return GameMetadata(
            name="Street Fighter II", source="screenscraper", source_id="101",
            match_score=1.0,
            snap_url="http://ss/snap.png",   # SS has a snap
            # wheel_url and background_url intentionally empty
        )


class _TGDBhasBG:
    """TGDB finds the game and has wheel + background that SS is missing."""
    def fetch(self, game_name, system_name):
        from spindoctor.scraper import MediaCandidate
        meta = GameMetadata(
            name="Street Fighter II", source="thegamesdb", source_id="202",
            match_score=1.0,
        )
        meta.media_candidates["wheel"] = [
            MediaCandidate(url="http://tgdb/wheel.png", region="us", source_type="wheel"),
        ]
        meta.media_candidates["background"] = [
            MediaCandidate(url="http://tgdb/bg.png", region="us", source_type="background"),
        ]
        return meta


def test_combined_fetch_syncs_tgdb_scalar_urls_into_ss_result():
    """When SS has a game but is missing some media slots, TGDB fill-in must
    update both media_candidates AND the scalar *_url fields so that
    jobs_for_metadata() (which reads *_url) picks them up."""
    client = _make_combined(_SSnoBG(), _TGDBhasBG())
    result = client.fetch("Street Fighter II", "Arcade")
    # SS snap should be preserved
    assert result.snap_url == "http://ss/snap.png"
    # TGDB wheel/background must appear in both candidates AND scalar fields
    assert result.media_candidates.get("wheel"), "wheel candidates missing"
    assert result.wheel_url == "http://tgdb/wheel.png", (
        "wheel_url not synced from TGDB fill — jobs_for_metadata would miss it"
    )
    assert result.media_candidates.get("background"), "background candidates missing"
    assert result.background_url == "http://tgdb/bg.png", (
        "background_url not synced from TGDB fill — jobs_for_metadata would miss it"
    )


# ── Override-ID miss warning (was NameError: _log not defined) ────────────────

def test_ss_override_miss_logs_warning_via_scraper_logger(monkeypatch):
    """When a forced screenscraper_id returns no result, scraper_logger.warning
    must be called.  Before the fix, _log.warning() raised NameError because
    the module logger is called scraper_logger, not _log."""
    import spindoctor.scraper as m

    client = ScreenScraperClient.__new__(ScreenScraperClient)
    client.username = "u"
    client.password = "p"
    client._limiter = MagicMock()

    monkeypatch.setattr(m, "get_game_override", lambda _sys, _game: {"screenscraper_id": "9999"})
    monkeypatch.setattr(client, "fetch_by_id", lambda _id: None)

    with patch.object(m.scraper_logger, "warning") as mock_warn:
        result = client.fetch("Pac-Man", "Arcade")

    assert result is None
    mock_warn.assert_called_once()
    call_str = str(mock_warn.call_args)
    assert "9999" in call_str
    assert "screenscraper.fr" in call_str


def test_tgdb_override_miss_logs_warning_via_scraper_logger(monkeypatch):
    """Same fix for TheGamesDBClient.fetch()."""
    import spindoctor.scraper as m

    client = TheGamesDBClient.__new__(TheGamesDBClient)
    client.api_key = "fake-api-key"
    client._limiter = MagicMock()

    monkeypatch.setattr(m, "get_game_override", lambda _sys, _game: {"thegamesdb_id": "8888"})
    monkeypatch.setattr(client, "fetch_by_id", lambda _id: None)

    with patch.object(m.scraper_logger, "warning") as mock_warn:
        result = client.fetch("Pac-Man", "Arcade")

    assert result is None
    mock_warn.assert_called_once()
    call_str = str(mock_warn.call_args)
    assert "8888" in call_str
    assert "thegamesdb.net" in call_str
