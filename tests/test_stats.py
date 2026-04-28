"""Coverage stats roll-up across systems."""
from __future__ import annotations

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.stats import collect_stats, top_missing_media


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / "spindoctor_home")
    monkeypatch.setattr(
        config_mod, "CONFIG_FILE", tmp_path / "spindoctor_home" / "config.json"
    )
    config_mod.reset_override_cache()
    yield
    config_mod.reset_override_cache()


def _build_layout(tmp_path):
    """Two systems: nes (has 1 ROM + 1 matching DB entry) and snes (empty)."""
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    (roms / "nes").mkdir(parents=True)
    (roms / "snes").mkdir()
    (roms / "nes" / "Mario.nes").touch()

    (hs / "Databases" / "nes").mkdir(parents=True)
    (hs / "Databases" / "nes" / "nes.xml").write_text(
        "<menu>"
        "<game name=\"Mario\">"
        "<description>Mario</description>"
        "<manufacturer>Nintendo</manufacturer>"
        "<year>1985</year>"
        "<genre>Platformer</genre>"
        "</game>"
        "</menu>",
        encoding="utf-8",
    )
    (hs / "Databases" / "snes").mkdir(parents=True)
    (hs / "Databases" / "snes" / "snes.xml").write_text(
        "<menu></menu>", encoding="utf-8")

    (hs / "Media" / "nes").mkdir(parents=True)
    (hs / "Media" / "snes").mkdir()
    return roms, hs


def _cfg(roms, hs):
    cfg = Config()
    cfg.roms_dir = str(roms)
    cfg.hyperspin_dir = str(hs)
    save_config(cfg)
    return cfg


def test_collect_stats_summarises_per_system(isolated_config, tmp_path):
    roms, hs = _build_layout(tmp_path)
    cfg = _cfg(roms, hs)

    report = collect_stats(["nes", "snes"], cfg)
    by_name = {s.system: s for s in report.per_system}
    assert by_name["nes"].total_roms == 1
    assert by_name["nes"].total_db_entries == 1
    assert by_name["nes"].matched == 1
    assert by_name["nes"].rom_coverage == 1.0
    assert by_name["nes"].metadata_coverage == 1.0
    # No media on disk → media coverage is zero
    assert by_name["nes"].media_coverage == 0.0
    assert by_name["snes"].total_roms == 0
    assert by_name["snes"].rom_coverage == 0.0


def test_top_missing_media_returns_counts(isolated_config, tmp_path):
    roms, hs = _build_layout(tmp_path)
    cfg = _cfg(roms, hs)
    report = collect_stats(["nes", "snes"], cfg)

    top = top_missing_media(report, limit=3)
    assert all(isinstance(count, int) and count > 0 for _, count in top)
    # Wheel comes first in MEDIA_TYPES so should be among the most missing
    types = [t for t, _ in top]
    assert "wheel" in types
