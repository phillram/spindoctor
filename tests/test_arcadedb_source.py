"""ArcadeDB (adb.arcadeitalia.net) as a source for arcade wheels.

ArcadeDB answers by MAME set name with no key: a short gameplay video (SD
and HD), in-game, title, flyer and cabinet pictures, and title, maker,
year, genre and players. It is the only free source of game videos found
for arcade wheels. A fake session stands in for the site here.
"""
from __future__ import annotations

import types

import pytest

from spindoctor.config import Config
from spindoctor.scraper import (
    ArcadeDBClient, ChainedMetadataClient, MetadataError, build_client,
)

_PACMAN = {
    "game_name": "pacman", "title": "Pac-Man (Midway)", "cloneof": "puckman",
    "manufacturer": "Namco (Midway license)", "year": "1980", "genre": "Maze / Collect",
    "players": "2", "url": "https://adb.arcadeitalia.net/?mame=pacman",
    "url_image_ingame": "https://adb.example/pacman/ingame",
    "url_image_title": "https://adb.example/pacman/title",
    "url_image_marquee": "https://adb.example/pacman/marquee",
    "url_image_flyer": "https://adb.example/pacman/flyer",
    "url_image_cabinet": "https://adb.example/pacman/cabinet",
    "url_video_shortplay": "https://adb.example/pacman/video",
    "url_video_shortplay_hd": "https://adb.example/pacman/video-hd",
}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.text = payload, status, ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client(rows_by_name, calls):
    client = ArcadeDBClient()
    client._limiter = types.SimpleNamespace(wait=lambda: None)

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        calls.append(params["game_name"])
        return _Resp({"release": "x", "result": rows_by_name.get(params["game_name"], [])})

    client._session = types.SimpleNamespace(get=fake_get)
    return client


def test_a_set_name_gives_video_pictures_and_tags():
    calls = []
    [meta] = _client({"pacman": [_PACMAN]}, calls).fetch_with_search("pacman", "MAME")
    assert (meta.name, meta.source, meta.source_id, meta.match_score) == (
        "Pac-Man (Midway)", "arcadedb", "pacman", 1.0)
    assert (meta.manufacturer, meta.year, meta.genre, meta.players) == (
        "Namco (Midway license)", "1980", "Maze / Collect", "2")
    assert meta.video_url.endswith("/video")                       # SD first
    assert [c.url.rsplit("/", 1)[1] for c in meta.media_candidates["video"]] == ["video", "video-hd"]
    assert meta.snap_url.endswith("/ingame") and meta.title_url.endswith("/title")
    assert meta.artwork_url.endswith("/flyer")
    assert not meta.wheel_url                                       # a marquee isn't a wheel logo
    assert calls == ["pacman"]


def test_console_names_are_never_sent():
    calls = []
    client = _client({}, calls)
    assert client.fetch_with_search("007 - Blood Stone (USA)", "Nintendo DS") == []
    assert client.fetch_with_search("Pac-Man", "MAME") == []
    assert calls == []


def test_a_miss_is_asked_once():
    calls = []
    assert _client({}, calls).fetch_with_search("notaset", "MAME") == []
    assert calls == ["notaset"]


def test_an_unknown_set_is_a_miss_not_an_error():
    """ArcadeDB answers 400 Bad Request (HTML) for a set it doesn't know."""
    client = ArcadeDBClient()
    client._limiter = types.SimpleNamespace(wait=lambda: None)
    calls = []

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        calls.append(params["game_name"])
        return _Resp(None, status=400)

    client._session = types.SimpleNamespace(get=fake_get)
    assert client.fetch_with_search("fballxbox", "4-Player Games") == []
    assert calls == ["fballxbox"]


def test_only_the_asked_set_is_taken():
    calls = []
    other = dict(_PACMAN, game_name="puckman")
    assert _client({"pacman": [other]}, calls).fetch("pacman", "MAME") is None


def test_bad_answers_are_metadata_errors():
    client = ArcadeDBClient()
    client._limiter = types.SimpleNamespace(wait=lambda: None)

    class _Bad(_Resp):
        def json(self):
            raise ValueError("not json")

    client._session = types.SimpleNamespace(get=lambda url, params=None, timeout=None: _Bad(None))
    with pytest.raises(MetadataError, match="ArcadeDB fetch failed"):
        client.fetch("pacman", "MAME")


def test_build_client_names_arcadedb():
    assert isinstance(build_client(Config(), "arcadedb", use_cache=False), ArcadeDBClient)
    chain = build_client(Config(thegamesdb_key="k"), "arcadedb,thegamesdb", use_cache=False)
    assert isinstance(chain, ChainedMetadataClient) and chain.names == ["arcadedb", "thegamesdb"]


def test_cli_accepts_arcadedb():
    from spindoctor.cli import _SourceParam
    assert _SourceParam().convert("arcadedb,launchbox", None, None) == "arcadedb,launchbox"
