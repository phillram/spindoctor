"""Regression tests for scraper payloads that don't match the documented shape.

A `fetch-meta --source both` run over a 60-game PC wheel died on the fifth
game with `AttributeError: 'list' object has no attribute 'get'` inside
`_parse_thegamesdb`, throwing away every game resolved before it. TheGamesDB
runs on PHP, whose `json_encode` writes an empty associative array as `[]`,
so `include.boxart.data` arrives as a list for a game with no boxart.

The same run reported every ScreenScraper call as "ScreenScraper search
failed: Expecting value: line 1 column 1 (char 0)" — a JSON decode error
that named nothing the user could act on, because the plain-text body that
does name the cause was dropped.
"""
from __future__ import annotations

import json
import types

import pytest

from spindoctor.scraper import (
    MetadataError,
    ScreenScraperClient,
    TheGamesDBClient,
    _parse_thegamesdb,
)


class _FakeResp:
    def __init__(self, payload=None, status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        if self._payload is None:
            raise json.JSONDecodeError("Expecting value", self.text or "", 0)
        return self._payload


def _session(fake_get):
    return types.SimpleNamespace(get=fake_get)


# ─── TheGamesDB empty-map payloads ────────────────────────────────────────────

def test_parse_thegamesdb_survives_empty_include_maps():
    """`include.*.data` as `[]` must read as "nothing here", not crash."""
    game = {"id": 12345, "game_title": "Fix-It Felix Jr", "genres": [1], "developers": [7]}
    response = {"include": {
        "boxart": {"base_url": {"medium": "https://cdn.thegamesdb.net/"}, "data": []},
        "genres": {"data": []},
        "developers": {"data": []},
    }}

    meta = _parse_thegamesdb("Fix-It Felix Jr", game, response)

    assert meta.name == "Fix-It Felix Jr"
    assert meta.source_id == "12345"
    assert meta.artwork_url == ""
    assert meta.genre == ""
    assert meta.manufacturer == ""


def test_thegamesdb_fetch_resolves_a_game_with_no_boxart():
    """The failing path from the crash log, end to end."""
    client = TheGamesDBClient("fake-key")

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        if "Games/Images" in url:
            return _FakeResp({"data": {"images": []}})
        return _FakeResp({
            "code": 200,
            "data": {"games": [{"id": 12345, "game_title": "Fix-It Felix Jr"}]},
            "include": {"boxart": {"base_url": [], "data": []}},
        })

    client._session = _session(fake_get)

    meta = client.fetch("Fix-It Felix Jr", "PC Games")
    assert meta is not None
    assert meta.name == "Fix-It Felix Jr"
    assert meta.artwork_url == ""


def test_unexpected_payload_fails_only_the_current_game():
    """Any other shape surprise must raise MetadataError, which callers
    already handle per game, rather than unwinding the whole command."""
    client = TheGamesDBClient("fake-key")

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        return _FakeResp({"code": 200, "data": {"games": ["not-a-game-record"]}})

    client._session = _session(fake_get)

    with pytest.raises(MetadataError) as excinfo:
        client.fetch("Arzette The Jewel of Faramore", "PC Games")
    assert "unexpected payload" in str(excinfo.value)
    assert "Arzette The Jewel of Faramore" in str(excinfo.value)


# ─── Non-JSON responses ───────────────────────────────────────────────────────

@pytest.mark.parametrize("make_client,secret,label", [
    (lambda: ScreenScraperClient("user", "hunter2"), "hunter2", "ScreenScraper search failed"),
    (lambda: TheGamesDBClient("key-abcd1234"), "key-abcd1234", "TheGamesDB search failed"),
])
def test_search_reports_the_plain_text_body(make_client, secret, label):
    """Both APIs answer HTTP 200 with plain text for auth and quota problems.
    The body names the cause, so it must reach the message — with the
    credentials scrubbed, because users paste console output into reports."""
    body = f"Erreur : API closed for non-registered members (sent {secret})"

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        return _FakeResp(None, text=body)

    client = make_client()
    client._session = _session(fake_get)

    with pytest.raises(MetadataError) as excinfo:
        client.search("Crazy Taxi 2-in-1", "PC Games")

    msg = str(excinfo.value)
    assert label in msg
    assert "API closed for non-registered members" in msg
    assert "HTTP 200" in msg
    assert secret not in msg
    assert "***" in msg


def test_search_reports_an_empty_body_as_empty():
    """An empty 200 is its own diagnosis — say so instead of showing
    only the decoder's "Expecting value: line 1 column 1"."""
    client = ScreenScraperClient("user", "hunter2")
    client._session = _session(lambda url, params=None, timeout=None: _FakeResp(None))

    with pytest.raises(MetadataError) as excinfo:
        client.search("Deathwish Enforcers Special Edition", "PC Games")
    assert "empty response body" in str(excinfo.value)
