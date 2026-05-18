"""User-supplied system overrides extend the four hardcoded lookups."""
from __future__ import annotations


import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, get_rom_extensions, save_config
from spindoctor.organize import required_layout
from spindoctor.rocketlauncher import guess_emulator
from spindoctor.scraper import ScreenScraperClient


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point CONFIG_FILE / CONFIG_DIR at tmp_path and reset the cache."""
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _save_overrides(overrides):
    cfg = Config()
    cfg.system_overrides = overrides
    save_config(cfg)


def test_rom_extensions_uses_override(isolated_config):
    _save_overrides({"Sony Playstation 7": {"rom_extensions": ["ps7", ".iso"]}})
    exts = get_rom_extensions("Sony Playstation 7")
    # Both forms (with and without leading dot) get normalised.
    assert exts == [".ps7", ".iso"]


def test_rom_extensions_falls_back_to_default(isolated_config):
    assert get_rom_extensions("Unknown System") == [".zip", ".7z", ".rar"]


def test_required_layout_uses_override(isolated_config):
    _save_overrides({"Sony Playstation 7": {"layout": "per-game-folder"}})
    assert required_layout("Sony Playstation 7") == "per-game-folder"


def test_required_layout_flat_disables_builtin_rule(isolated_config):
    # Sega Saturn has built-in multi-disc-m3u layout — override to "flat".
    _save_overrides({"Sega Saturn": {"layout": "flat"}})
    assert required_layout("Sega Saturn") is None


def test_emulator_uses_override(isolated_config):
    _save_overrides({"Sony Playstation 7": {"emulator": "RPCS7"}})
    assert guess_emulator("Sony Playstation 7") == "RPCS7"


def test_emulator_falls_back(isolated_config):
    # Built-in default for unknown systems is RetroArch.
    assert guess_emulator("Unknown System") == "RetroArch"


def test_screenscraper_id_uses_override(isolated_config):
    _save_overrides({"Sony Playstation 7": {"screenscraper_id": 999}})
    client = ScreenScraperClient("u", "p")
    assert client._system_id("Sony Playstation 7") == 999


def test_save_config_invalidates_override_cache(isolated_config):
    # First lookup with no overrides
    assert guess_emulator("New Console") == "RetroArch"
    # Now save overrides — the cache must drop, so the next lookup sees them.
    _save_overrides({"New Console": {"emulator": "CustomEmu"}})
    assert guess_emulator("New Console") == "CustomEmu"
