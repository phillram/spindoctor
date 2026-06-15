"""CombinedMetadataClient.search() error propagation and circuit-breaker helpers."""
from __future__ import annotations

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
