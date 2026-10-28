"""default_metadata_source: "auto" uses both scrapers when both are configured.

The old default "screenscraper" was written into every saved config, so a
configured TheGamesDB key was never used unless --source both was passed,
though the docs promised both sources whenever both are configured.
"""
from __future__ import annotations

import pytest

from spindoctor import config as config_mod
from spindoctor.config import Config
from spindoctor.scraper import (
    CombinedMetadataClient,
    ScreenScraperClient,
    TheGamesDBClient,
    build_client,
)

SS = {"screenscraper_user": "u", "screenscraper_pass": "p"}
TGDB = {"thegamesdb_key": "k"}


@pytest.mark.parametrize("creds,expected", [
    ({**SS, **TGDB}, CombinedMetadataClient),
    (SS, ScreenScraperClient),
    (TGDB, TheGamesDBClient),
])
def test_auto_default_uses_what_is_configured(creds, expected):
    client = build_client(Config(**creds), use_cache=False)
    assert type(client) is expected


def test_explicit_screenscraper_stays_screenscraper_only():
    cfg = Config(default_metadata_source="screenscraper", **SS, **TGDB)
    assert type(build_client(cfg, use_cache=False)) is ScreenScraperClient


def test_old_saved_default_is_migrated_to_auto_once():
    old = {"default_metadata_source": "screenscraper", **SS, **TGDB}
    cfg = Config.from_dict(old)
    assert cfg.default_metadata_source == "auto"
    assert cfg.metadata_source_migrated is True
    assert type(build_client(cfg, use_cache=False)) is CombinedMetadataClient


def test_choice_made_after_migration_is_kept():
    saved = {"default_metadata_source": "screenscraper", "metadata_source_migrated": True}
    assert Config.from_dict(saved).default_metadata_source == "screenscraper"


def test_old_explicit_thegamesdb_is_not_migrated():
    cfg = Config.from_dict({"default_metadata_source": "thegamesdb"})
    assert cfg.default_metadata_source == "thegamesdb"


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    config_mod.reset_override_cache()
    yield tmp_path
    config_mod.reset_override_cache()


def test_config_set_rejects_unknown_source(isolated_config):
    from click.testing import CliRunner

    from spindoctor.cli import cli

    result = CliRunner().invoke(cli, ["config", "set", "default_metadata_source", "screenscaper"])
    assert result.exit_code != 0
    assert "expected one of" in result.output
    result = CliRunner().invoke(cli, ["config", "set", "default_metadata_source", "Both"])
    assert result.exit_code == 0, result.output
    assert config_mod.load_config().default_metadata_source == "both"
