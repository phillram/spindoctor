"""`spindoctor config verify-credentials` — credential test CLI surface.

The GUI Setup tab's Test credentials button shells out to this command
(rather than calling ``spindoctor.scraper.verify_*`` directly from
``gui.py``), so this is the test that pins the contract.

Network is fully mocked — the CLI calls ``scraper.verify_*`` which calls
``request_get`` which we patch. We never hit the real ScreenScraper /
TheGamesDB API.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from spindoctor import scraper
from spindoctor.cli import cli


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _ss_ok_payload():
    return {"response": {"ssuser": {"id": "alice", "niveau": "1"}}}


def _tgdb_ok_payload():
    return {
        "code": 200, "status": "Success",
        "data": {"games": []},
        "remaining_monthly_allowance": 957,
    }


def test_verify_credentials_skipped_when_nothing_provided(tmp_path, monkeypatch):
    """No saved config, no CLI overrides → both providers report skipped."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "spindoctor.cli.load_config",
        lambda: __import__("spindoctor.config", fromlist=["Config"]).Config(),
    )
    runner = CliRunner()
    result = runner.invoke(
        cli, ["config", "verify-credentials", "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["screenscraper"]["status"] == "skipped"
    assert data["thegamesdb"]["status"] == "skipped"


def test_verify_credentials_overrides_beat_saved_config(tmp_path, monkeypatch):
    """``--ss-user`` / ``--tgdb-key`` override the saved config values."""
    from spindoctor.config import Config

    saved = Config()
    saved.screenscraper_user = "olduser"
    saved.screenscraper_pass = "oldpw"
    saved.thegamesdb_key = "oldkey1234"
    monkeypatch.setattr("spindoctor.cli.load_config", lambda: saved)

    captured = {"ss_user": None, "ss_pass": None, "tgdb_key": None}

    def fake_request_get(url, *, params=None, **_kw):
        if "ssuserInfos" in url:
            captured["ss_user"] = params.get("ssid")
            captured["ss_pass"] = params.get("sspassword")
            return _FakeResponse(200, _ss_ok_payload())
        if "ByGameName" in url:
            captured["tgdb_key"] = params.get("apikey")
            return _FakeResponse(200, _tgdb_ok_payload())
        raise AssertionError(f"unexpected URL {url}")

    with patch.object(scraper, "request_get", side_effect=fake_request_get):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "config", "verify-credentials",
            "--ss-user", "newuser", "--ss-pass", "newpw",
            "--tgdb-key", "newapikey",
            "--json",
        ])
    assert result.exit_code == 0, result.output
    # The CLI must have sent the override values, not the saved config.
    assert captured["ss_user"] == "newuser"
    assert captured["ss_pass"] == "newpw"
    assert captured["tgdb_key"] == "newapikey"
    data = json.loads(result.output)
    assert data["screenscraper"]["status"] == "ok"
    assert data["thegamesdb"]["status"] == "ok"


def test_verify_credentials_falls_back_to_saved_config(monkeypatch):
    """No overrides → both probes use the saved config values."""
    from spindoctor.config import Config

    saved = Config()
    saved.screenscraper_user = "savedu"
    saved.screenscraper_pass = "savedpw"
    saved.thegamesdb_key = "savedkey1234"
    monkeypatch.setattr("spindoctor.cli.load_config", lambda: saved)

    captured = {"ss_user": None, "tgdb_key": None}

    def fake_request_get(url, *, params=None, **_kw):
        if "ssuserInfos" in url:
            captured["ss_user"] = params.get("ssid")
            return _FakeResponse(200, _ss_ok_payload())
        if "ByGameName" in url:
            captured["tgdb_key"] = params.get("apikey")
            return _FakeResponse(200, _tgdb_ok_payload())
        raise AssertionError(f"unexpected URL {url}")

    with patch.object(scraper, "request_get", side_effect=fake_request_get):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["config", "verify-credentials", "--json"],
        )
    assert result.exit_code == 0, result.output
    assert captured["ss_user"] == "savedu"
    assert captured["tgdb_key"] == "savedkey1234"


def test_verify_credentials_exits_nonzero_on_failure(monkeypatch):
    """If any provider returns failure, the CLI exits non-zero."""
    from spindoctor.config import Config

    saved = Config()
    saved.screenscraper_user = "u"
    saved.screenscraper_pass = "wrongpw"
    saved.thegamesdb_key = "realapikey"
    monkeypatch.setattr("spindoctor.cli.load_config", lambda: saved)

    def fake_request_get(url, *, params=None, **_kw):
        if "ssuserInfos" in url:
            return _FakeResponse(403, payload=None, text="Erreur de login")
        if "ByGameName" in url:
            return _FakeResponse(200, _tgdb_ok_payload())
        raise AssertionError(f"unexpected URL {url}")

    with patch.object(scraper, "request_get", side_effect=fake_request_get):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "verify-credentials", "--json"])
    # Failing provider exit code propagates as non-zero so the GUI
    # button can flip into "Credential test failed" state.
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["screenscraper"]["status"] == "fail"
    assert data["thegamesdb"]["status"] == "ok"


def test_verify_credentials_human_output_uses_check_and_cross(monkeypatch):
    """Without --json the output is human-readable with ok/fail symbols."""
    from spindoctor.config import Config

    saved = Config()
    saved.screenscraper_user = "u"
    saved.screenscraper_pass = "p"
    saved.thegamesdb_key = "realapikey"
    monkeypatch.setattr("spindoctor.cli.load_config", lambda: saved)

    def fake_request_get(url, *, params=None, **_kw):
        if "ssuserInfos" in url:
            return _FakeResponse(200, _ss_ok_payload())
        if "ByGameName" in url:
            return _FakeResponse(200, _tgdb_ok_payload())
        raise AssertionError(f"unexpected URL {url}")

    with patch.object(scraper, "request_get", side_effect=fake_request_get):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "verify-credentials"])
    assert result.exit_code == 0, result.output
    assert "ScreenScraper" in result.output
    assert "TheGamesDB" in result.output
    # Success markers for both providers in this scenario.
    assert result.output.count("✓") >= 2
