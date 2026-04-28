"""Recently-Played wheel: parse RL Statistics + rebuild synthetic system."""
from __future__ import annotations

from datetime import datetime

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.medialink import LinkMode
from spindoctor.recent import (
    PlayRecord, _parse_time, _read_stats_file, collect_play_records,
    rebuild, top_recent,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    home = tmp_path / "spindoctor_home"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / "config.json")
    config_mod.reset_override_cache()
    yield home
    config_mod.reset_override_cache()


def _write_stats_ini(path, sections):
    """*sections* is a list of (game_name, last_played_str, count)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, last, count in sections:
        lines.append(f"[{name}]")
        lines.append(f"Last_Played={last}")
        lines.append(f"Number_of_Times_Played={count}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_parse_time_handles_common_formats():
    assert _parse_time("2026-04-27 18:33:12") == datetime(2026, 4, 27, 18, 33, 12)
    assert _parse_time("2026-04-27T18:33:12") == datetime(2026, 4, 27, 18, 33, 12)
    assert _parse_time("not a timestamp") is None
    assert _parse_time("") is None


def test_read_stats_file_parses_records(tmp_path):
    ini = tmp_path / "snes.ini"
    _write_stats_ini(ini, [
        ("Tetris", "2026-04-27 18:33:12", 4),
        ("Mario", "2026-04-26 09:00:00", 1),
    ])
    records = _read_stats_file(ini, "Super Nintendo")
    assert {r.rom_name for r in records} == {"Tetris", "Mario"}
    tetris = next(r for r in records if r.rom_name == "Tetris")
    assert tetris.play_count == 4
    assert tetris.last_played == datetime(2026, 4, 27, 18, 33, 12)


def test_top_recent_dedupes_and_sorts():
    older = PlayRecord("snes", "Tetris", datetime(2026, 4, 1, 0, 0, 0), 1)
    newer = PlayRecord("snes", "Tetris", datetime(2026, 4, 27, 0, 0, 0), 2)
    other = PlayRecord("snes", "Mario",  datetime(2026, 4, 20, 0, 0, 0), 5)
    top = top_recent([older, newer, other], limit=2)
    assert [r.rom_name for r in top] == ["Tetris", "Mario"]
    assert top[0].play_count == 2  # the newer Tetris record won


def test_collect_play_records_walks_global_dir(isolated_config, tmp_path):
    rl = tmp_path / "rl"
    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [("Tetris", "2026-04-27 18:33:12", 1)],
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg)
    assert len(records) == 1
    assert records[0].system == "Super Nintendo"


def test_rebuild_writes_recently_played_database(isolated_config, tmp_path):
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"

    # Source system + DB + media
    (roms / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").write_text(
        "<menu><game name=\"Tetris\"><description>Tetris</description>"
        "</game></menu>",
        encoding="utf-8",
    )
    (hs / "Media" / "Super Nintendo" / "Images" / "Wheel").mkdir(parents=True)
    (hs / "Media" / "Super Nintendo" / "Images" / "Wheel" / "Tetris.png").write_bytes(b"w")

    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [("Tetris", "2026-04-27 18:33:12", 3)],
    )

    cfg = Config(
        roms_dir=str(roms),
        hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
    )
    save_config(cfg)

    summary = rebuild(cfg, limit=20, media_mode=LinkMode.COPY)
    assert summary.entries == 1
    assert summary.db_path.exists()
    db_text = summary.db_path.read_text(encoding="utf-8")
    assert "Tetris" in db_text
    assert (hs / "Media" / "Recently Played" / "Images" / "Wheel" / "Tetris.png").exists()
    inis = list((rl / "Modules" / "PCLauncher" / "Recently Played").iterdir())
    assert len(inis) == 1


def test_rebuild_prunes_when_records_drop_off(isolated_config, tmp_path):
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    (roms / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").write_text(
        "<menu>"
        "<game name=\"Tetris\"><description>Tetris</description></game>"
        "<game name=\"Mario\"><description>Mario</description></game>"
        "</menu>",
        encoding="utf-8",
    )
    (hs / "Media" / "Super Nintendo" / "Images" / "Wheel").mkdir(parents=True)
    (hs / "Media" / "Super Nintendo" / "Images" / "Wheel" / "Tetris.png").write_bytes(b"a")
    (hs / "Media" / "Super Nintendo" / "Images" / "Wheel" / "Mario.png").write_bytes(b"b")

    stats_path = rl / "Settings" / "Global Statistics" / "Super Nintendo.ini"
    _write_stats_ini(stats_path, [
        ("Tetris", "2026-04-26 09:00:00", 1),
        ("Mario",  "2026-04-27 18:00:00", 1),
    ])
    cfg = Config(
        roms_dir=str(roms), hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
    )
    save_config(cfg)
    rebuild(cfg, limit=2, media_mode=LinkMode.COPY)

    # Drop Tetris from the stats
    _write_stats_ini(stats_path, [
        ("Mario", "2026-04-27 18:00:00", 1),
    ])
    summary = rebuild(cfg, limit=2, media_mode=LinkMode.COPY)
    assert summary.entries == 1
    assert summary.pruned == 1
    wheels = list((hs / "Media" / "Recently Played" / "Images" / "Wheel").glob("*"))
    assert {w.stem for w in wheels} == {"Mario"}
