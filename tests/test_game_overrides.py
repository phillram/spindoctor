"""Per-(system, game) scraper-ID overrides: config storage, CLI, and the
fetch()-bypass behavior in ScreenScraperClient / TheGamesDBClient.

Lets a cabinet owner force a specific ScreenScraper/TheGamesDB game ID
for one title that doesn't match well by name (language barrier,
alternate punctuation, a remaster's subtitle, etc.) instead of relying
on fuzzy name matching.
"""
from __future__ import annotations

import types

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor.cli import cli
from spindoctor.config import (
    Config, get_game_override, get_game_overrides, save_config,
)
from spindoctor.scraper import ScreenScraperClient, TheGamesDBClient


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


# ─── config storage / cache ────────────────────────────────────────────────

def test_get_game_override_returns_empty_dict_when_unset(isolated_config):
    assert get_game_override("Nintendo DS", "Some Game") == {}


def test_get_game_override_returns_saved_entry(isolated_config):
    cfg = Config()
    cfg.game_overrides = {
        "Nintendo DS": {
            "Golden Sun - Dark Dawn (USA)": {
                "screenscraper_id": 5775, "thegamesdb_id": 11251,
            },
        },
    }
    save_config(cfg)
    assert get_game_override("Nintendo DS", "Golden Sun - Dark Dawn (USA)") == {
        "screenscraper_id": 5775, "thegamesdb_id": 11251,
    }


def test_save_config_invalidates_game_override_cache(isolated_config):
    cfg = Config()
    cfg.game_overrides = {"NES": {"Mario": {"screenscraper_id": 1}}}
    save_config(cfg)
    assert get_game_overrides() == {"NES": {"Mario": {"screenscraper_id": 1}}}

    cfg2 = Config()
    cfg2.game_overrides = {"NES": {"Mario": {"screenscraper_id": 2}}}
    save_config(cfg2)
    # Cache must reflect the new save, not the stale first read.
    assert get_game_overrides() == {"NES": {"Mario": {"screenscraper_id": 2}}}


# ─── `config game-override` CLI ────────────────────────────────────────────

def test_game_override_set_requires_at_least_one_id(isolated_config):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["config", "game-override", "set", "Nintendo DS", "Some Game"],
    )
    assert result.exit_code != 0
    assert "Nothing to set" in result.output


def test_game_override_set_then_list_round_trips(isolated_config):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "config", "game-override", "set", "Nintendo DS",
        "Golden Sun - Dark Dawn (USA)",
        "--screenscraper-id", "5775", "--thegamesdb-id", "11251",
    ])
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli, ["config", "game-override", "list"])
    assert result.exit_code == 0, result.output
    assert "Golden Sun - Dark Dawn (USA)" in result.output
    assert "5775" in result.output
    assert "11251" in result.output


def test_game_override_set_partial_only_screenscraper(isolated_config):
    """Setting only --screenscraper-id must not invent a thegamesdb_id."""
    runner = CliRunner()
    result = runner.invoke(cli, [
        "config", "game-override", "set", "Nintendo DS", "Some Game",
        "--screenscraper-id", "42",
    ])
    assert result.exit_code == 0, result.output
    assert get_game_override("Nintendo DS", "Some Game") == {"screenscraper_id": 42}


def test_game_override_clear_removes_entry(isolated_config):
    runner = CliRunner()
    runner.invoke(cli, [
        "config", "game-override", "set", "Nintendo DS", "Some Game",
        "--screenscraper-id", "42",
    ])
    result = runner.invoke(
        cli, ["config", "game-override", "clear", "Nintendo DS", "Some Game"],
    )
    assert result.exit_code == 0, result.output
    assert get_game_override("Nintendo DS", "Some Game") == {}


def test_game_override_clear_nonexistent_is_a_no_op_not_an_error(isolated_config):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["config", "game-override", "clear", "Nintendo DS", "Ghost Game"],
    )
    assert result.exit_code == 0
    assert "No override set" in result.output


def test_game_override_list_empty_says_so(isolated_config):
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "game-override", "list"])
    assert result.exit_code == 0
    assert "No game overrides configured" in result.output


# ─── ScreenScraperClient.fetch() override bypass ───────────────────────────

def test_screenscraper_fetch_uses_override_id_instead_of_name_search(isolated_config):
    cfg = Config()
    cfg.game_overrides = {
        "Nintendo DS": {"Golden Sun - Dark Dawn (USA)": {"screenscraper_id": 5775}},
    }
    save_config(cfg)

    client = ScreenScraperClient("user", "pass")
    calls: list[str] = []

    def fake_fetch_by_id(game_id):
        calls.append(game_id)
        from spindoctor.scraper import GameMetadata
        return GameMetadata(name="Golden Sun: Dark Dawn", source_id=game_id)

    client.fetch_by_id = fake_fetch_by_id

    def fail_if_called(*_a, **_k):
        raise AssertionError("name-based lookup must not run when an override exists")

    client._session = types.SimpleNamespace(get=fail_if_called)

    meta = client.fetch("Golden Sun - Dark Dawn (USA)", "Nintendo DS")
    assert calls == ["5775"]
    assert meta.match_score == 1.0


def test_screenscraper_fetch_without_override_does_not_call_fetch_by_id(isolated_config):
    client = ScreenScraperClient("user", "pass")
    client.fetch_by_id = lambda *_a, **_k: pytest.fail("must not be called")

    def fake_get(url, params=None, timeout=None):  # noqa: ARG001
        class _Resp:
            status_code = 200
            text = ""
            def raise_for_status(self): return None
            def json(self): return {"response": {}}
        return _Resp()

    client._session = types.SimpleNamespace(get=fake_get)
    assert client.fetch("Some Game", "Nintendo DS") is None


# ─── TheGamesDBClient.fetch_by_id() / override bypass ──────────────────────

class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_thegamesdb_fetch_by_id_returns_metadata():
    client = TheGamesDBClient("fake-key")

    def fake_get(url, params=None, timeout=None):
        if "Images" in url:
            return _FakeResp({"data": {"images": {}}})
        assert params["id"] == "11251"
        return _FakeResp({
            "data": {"games": [{"id": 11251, "game_title": "Golden Sun: Dark Dawn"}]},
            "include": {},
        })

    client._session = types.SimpleNamespace(get=fake_get)
    meta = client.fetch_by_id("11251")
    assert meta is not None
    assert meta.name == "Golden Sun: Dark Dawn"
    assert meta.source_id == "11251"


def test_thegamesdb_fetch_by_id_returns_none_when_no_games():
    client = TheGamesDBClient("fake-key")
    client._session = types.SimpleNamespace(
        get=lambda url, params=None, timeout=None: _FakeResp({"data": {"games": []}}),
    )
    assert client.fetch_by_id("999") is None


def test_thegamesdb_fetch_by_id_returns_none_on_request_exception():
    client = TheGamesDBClient("fake-key")

    def raising_get(url, params=None, timeout=None):
        raise RuntimeError("boom")

    client._session = types.SimpleNamespace(get=raising_get)
    assert client.fetch_by_id("999") is None


def test_thegamesdb_fetch_by_id_returns_none_for_empty_id():
    client = TheGamesDBClient("fake-key")
    assert client.fetch_by_id("") is None
    assert client.fetch_by_id(None) is None


def test_thegamesdb_fetch_uses_override_id_instead_of_name_search(isolated_config):
    cfg = Config()
    cfg.game_overrides = {
        "Nintendo DS": {"Golden Sun - Dark Dawn (USA)": {"thegamesdb_id": 11251}},
    }
    save_config(cfg)

    client = TheGamesDBClient("fake-key")
    calls: list[str] = []

    def fake_fetch_by_id(game_id):
        calls.append(game_id)
        from spindoctor.scraper import GameMetadata
        return GameMetadata(name="Golden Sun: Dark Dawn", source_id=game_id)

    client.fetch_by_id = fake_fetch_by_id

    def fail_if_called(*_a, **_k):
        raise AssertionError("name-based lookup must not run when an override exists")

    client._session = types.SimpleNamespace(get=fail_if_called)

    meta = client.fetch("Golden Sun - Dark Dawn (USA)", "Nintendo DS")
    assert calls == ["11251"]
    assert meta.match_score == 1.0
