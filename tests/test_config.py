"""Tests for spindoctor.config.

Exercises the dataclass-level helpers (is_valid, is_ignored, add_ignore,
remove_ignore, get_ignore_list, set_lightgun, lightgun_systems) and the
module-level functions (load_config, save_config, get_system_overrides,
reset_override_cache, get_rom_extensions, get_systems).

These used to be exercised only as side effects of other tests; pinning
them here guards against regressions that previously only surfaced as
mysterious failures deep inside scrape/match loops.
"""
from __future__ import annotations

import json

import pytest

from spindoctor import config as config_mod
from spindoctor.config import Config


# ─── is_valid ────────────────────────────────────────────────────────────────


def test_is_valid_reports_missing_roms_and_hyperspin_dirs():
    cfg = Config()
    ok, errors = cfg.is_valid()
    assert ok is False
    assert any("roms_dir" in e for e in errors)
    assert any("hyperspin_dir" in e for e in errors)


def test_is_valid_reports_missing_directories_on_disk(tmp_path):
    cfg = Config(roms_dir=str(tmp_path / "nope"), hyperspin_dir=str(tmp_path / "nada"))
    ok, errors = cfg.is_valid()
    assert ok is False
    assert any("does not exist" in e for e in errors)


def test_is_valid_passes_when_both_dirs_exist(tmp_path):
    (tmp_path / "roms").mkdir()
    (tmp_path / "hs").mkdir()
    cfg = Config(roms_dir=str(tmp_path / "roms"), hyperspin_dir=str(tmp_path / "hs"))
    ok, errors = cfg.is_valid()
    assert ok is True
    assert errors == []


# ─── ignore lists ────────────────────────────────────────────────────────────


def test_is_ignored_checks_global_and_system_lists():
    cfg = Config(ignore_lists={
        "_global": ["protected.dat"],
        "NES": ["beta.nes"],
    })
    assert cfg.is_ignored("protected.dat", "NES") is True
    assert cfg.is_ignored("beta.nes", "NES") is True
    assert cfg.is_ignored("beta.nes", "SNES") is False
    assert cfg.is_ignored("clean.nes", "NES") is False


def test_add_ignore_is_idempotent():
    cfg = Config()
    cfg.add_ignore("alpha", "NES")
    cfg.add_ignore("alpha", "NES")  # second call must not duplicate
    cfg.add_ignore("beta", "NES")
    assert cfg.ignore_lists["NES"] == ["alpha", "beta"]


def test_remove_ignore_returns_false_when_missing():
    cfg = Config()
    cfg.add_ignore("alpha", "NES")
    assert cfg.remove_ignore("alpha", "NES") is True
    assert cfg.remove_ignore("alpha", "NES") is False  # already gone


def test_get_ignore_list_per_system_and_global():
    cfg = Config(ignore_lists={"NES": ["a"], "SNES": ["b", "c"]})
    assert cfg.get_ignore_list("NES") == ["a"]
    assert cfg.get_ignore_list("SNES") == ["b", "c"]
    assert sorted(cfg.get_ignore_list()) == ["a", "b", "c"]


# ─── lightgun helpers ────────────────────────────────────────────────────────


def test_lightgun_helpers_toggle_overrides():
    cfg = Config()
    assert cfg.lightgun_systems() == []
    cfg.set_lightgun("Sinden", True)
    assert "Sinden" in cfg.lightgun_systems()
    cfg.set_lightgun("Sinden", False)
    # Toggling off removes the whole override entry if nothing else is set.
    assert cfg.lightgun_systems() == []
    assert "Sinden" not in cfg.system_overrides


def test_lightgun_off_preserves_other_override_keys():
    cfg = Config(system_overrides={"Sinden": {"emulator": "Sinden.exe", "lightgun": True}})
    cfg.set_lightgun("Sinden", False)
    assert cfg.system_overrides["Sinden"] == {"emulator": "Sinden.exe"}


# ─── serialisation ───────────────────────────────────────────────────────────


def test_from_dict_filters_unknown_keys():
    cfg = Config.from_dict({"roms_dir": "/tmp/x", "_unknown_key": True})
    assert cfg.roms_dir == "/tmp/x"
    assert not hasattr(cfg, "_unknown_key")


def test_to_dict_round_trip():
    cfg = Config(roms_dir="/r", hyperspin_dir="/h", match_threshold=0.42)
    rebuilt = Config.from_dict(cfg.to_dict())
    assert rebuilt.roms_dir == "/r"
    assert rebuilt.hyperspin_dir == "/h"
    assert rebuilt.match_threshold == pytest.approx(0.42)


# ─── load_config / save_config ───────────────────────────────────────────────


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect the module-level config paths to a per-test tmp dir."""
    cfg_dir = tmp_path / ".spindoctor"
    cfg_file = cfg_dir / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
    config_mod.reset_override_cache()
    yield cfg_file
    config_mod.reset_override_cache()


def test_load_config_returns_defaults_when_missing(isolated_config):
    cfg = config_mod.load_config()
    assert cfg.roms_dir == ""
    assert cfg.match_threshold == 0.80


def test_save_then_load_round_trip(isolated_config):
    config_mod.save_config(Config(roms_dir="/x", match_threshold=0.5))
    cfg = config_mod.load_config()
    assert cfg.roms_dir == "/x"
    assert cfg.match_threshold == pytest.approx(0.5)


def test_load_config_handles_corrupt_json(isolated_config, capsys):
    """A garbled file must produce defaults, a stderr warning, and a backup."""
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text("{not valid json", encoding="utf-8")
    cfg = config_mod.load_config()
    assert cfg.roms_dir == ""  # fell through to defaults
    captured = capsys.readouterr()
    assert "unreadable" in captured.err
    # Backup file was created next to the original.
    backups = list(isolated_config.parent.glob("config.corrupt-*.json"))
    assert len(backups) == 1


def test_load_config_handles_wrong_type(isolated_config):
    """A JSON file whose top level isn't an object must not crash."""
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text("[1, 2, 3]", encoding="utf-8")
    cfg = config_mod.load_config()
    assert cfg.roms_dir == ""  # defaults


# ─── config set bounds validation ────────────────────────────────────────────


@pytest.mark.parametrize("key,bad_value", [
    ("match_threshold", "99.0"),       # 0.0–1.0
    ("match_threshold", "-0.5"),
    ("max_concurrent_downloads", "0"), # 1–64
    ("max_concurrent_downloads", "-5"),
    ("max_concurrent_downloads", "100"),
    ("metadata_cache_ttl_days", "-1"), # 0–3650
])
def test_config_set_rejects_out_of_range_value(isolated_config, key, bad_value):
    """Regression: out-of-range numeric values used to be accepted at write
    time and only surfaced as a confusing failure deep inside a download
    or match loop later. The CLI must fail at set time with a clear error.
    """
    from click.testing import CliRunner

    from spindoctor.cli import cli

    runner = CliRunner()
    # `--` so Click doesn't try to parse a leading-dash value as a flag.
    result = runner.invoke(cli, ["config", "set", "--", key, bad_value])
    assert result.exit_code != 0
    assert "Out of range" in result.output or "out of range" in result.output.lower()


def test_config_set_accepts_in_range_value(isolated_config):
    """Sanity check: legal values still pass the new bounds check."""
    from click.testing import CliRunner

    from spindoctor.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["config", "set", "match_threshold", "0.75"])
    assert result.exit_code == 0
    assert config_mod.load_config().match_threshold == pytest.approx(0.75)


# ─── system override cache ───────────────────────────────────────────────────


def test_get_system_overrides_caches_until_reset(isolated_config):
    config_mod.save_config(Config(system_overrides={"NES": {"emulator": "fceux"}}))
    # First call populates the cache from disk.
    first = config_mod.get_system_overrides()
    assert first == {"NES": {"emulator": "fceux"}}
    # Hand-edit the file behind our back — the cache should still return
    # the old value until reset_override_cache() runs.
    isolated_config.write_text(json.dumps({"system_overrides": {}}), encoding="utf-8")
    assert config_mod.get_system_overrides() == {"NES": {"emulator": "fceux"}}
    config_mod.reset_override_cache()
    assert config_mod.get_system_overrides() == {}


def test_save_config_clears_override_cache(isolated_config):
    config_mod.save_config(Config(system_overrides={"NES": {"emulator": "old"}}))
    assert config_mod.get_system_overrides()["NES"]["emulator"] == "old"
    # Saving a new config should invalidate the cache automatically.
    config_mod.save_config(Config(system_overrides={"NES": {"emulator": "new"}}))
    assert config_mod.get_system_overrides()["NES"]["emulator"] == "new"


# ─── get_rom_extensions ──────────────────────────────────────────────────────


def test_get_rom_extensions_exact_lookup(isolated_config):
    assert config_mod.get_rom_extensions("NES")[:1] == [".nes"]
    assert config_mod.get_rom_extensions("SNES")[:1] == [".sfc"]


def test_get_rom_extensions_partial_match_prefers_longest_key(isolated_config):
    """`Sega Genesis` must match `genesis`, not `nes`."""
    # `nes` is a substring of `genesis` — partial matching must pick
    # the longer key first or this regresses.
    exts = config_mod.get_rom_extensions("Sega Genesis")
    assert ".md" in exts and ".smd" in exts
    assert exts != config_mod.get_rom_extensions("NES")


def test_get_rom_extensions_falls_back_to_default(isolated_config):
    assert config_mod.get_rom_extensions("Imaginary System") == [".zip", ".7z", ".rar"]


def test_get_rom_extensions_uses_override_with_or_without_dot(isolated_config):
    config_mod.save_config(Config(system_overrides={
        "PS7": {"rom_extensions": [".ps7", "iso"]}
    }))
    assert config_mod.get_rom_extensions("PS7") == [".ps7", ".iso"]


# ─── get_systems ─────────────────────────────────────────────────────────────


def test_get_systems_unions_roms_and_databases(tmp_path):
    roms = tmp_path / "roms"
    hs = tmp_path / "hs"
    (roms / "NES").mkdir(parents=True)
    (roms / "SNES").mkdir()
    (hs / "Databases" / "NES").mkdir(parents=True)
    (hs / "Databases" / "Genesis").mkdir()
    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs))
    assert config_mod.get_systems(cfg) == ["Genesis", "NES", "SNES"]


def test_get_systems_ignores_missing_paths(tmp_path):
    cfg = Config(roms_dir=str(tmp_path / "no"), hyperspin_dir=str(tmp_path / "nope"))
    assert config_mod.get_systems(cfg) == []


# ─── first-run wizard flag ───────────────────────────────────────────────────


def test_first_run_complete_default_false():
    """Fresh configs default to False so the wizard opens on first launch."""
    assert Config().first_run_complete is False


def test_first_run_complete_round_trips(isolated_config):
    config_mod.save_config(Config(first_run_complete=True))
    assert config_mod.load_config().first_run_complete is True


def test_first_run_complete_omitted_keys_are_false(isolated_config):
    """Older configs written before the field existed must load cleanly
    with the default value rather than crashing."""
    # Simulate a v1.9.x config that has no `first_run_complete` key.
    raw = {"roms_dir": "/r", "hyperspin_dir": "/h"}
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(__import__("json").dumps(raw), encoding="utf-8")
    cfg = config_mod.load_config()
    assert cfg.first_run_complete is False
    assert cfg.roms_dir == "/r"
