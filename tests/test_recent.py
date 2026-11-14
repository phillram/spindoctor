"""Recently-Played wheel: parse RL Statistics + rebuild synthetic system."""
from __future__ import annotations
from tests.helpers import write_bytes as _write_bytes

from spindoctor import config
from spindoctor import favorites
from spindoctor import recent

from datetime import datetime

import pytest

from spindoctor.config import Config, save_config
from spindoctor.medialink import LinkMode
from spindoctor.recent import (
    PlayRecord, _parse_time, _read_stats_file, _read_global_statistics_ini,
    collect_play_records, rebuild, top_recent,
)


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
    assert _parse_time("Friday June 12, 2026 08:18:02 PM") == datetime(2026, 6, 12, 20, 18, 2)
    assert _parse_time("not a timestamp") is None
    assert _parse_time("") is None


def test_ranked_builder_reuses_source_cache_and_preserves_metadata(config_home, tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET
    from spindoctor import favorites, recent

    hs = tmp_path / "hs"
    source = hs / "Databases" / "MAME" / "MAME.xml"
    source.parent.mkdir(parents=True)
    source.write_text(
        '<menu><game name="A"><description>Alpha</description></game>'
        '<game name="B" custom="keep"><description>Beta</description>'
        '<manufacturer>Maker</manufacturer><custom-child>value</custom-child></game></menu>',
        encoding="utf-8",
    )
    cfg = Config(hyperspin_dir=str(hs))
    entries = [favorites.FavoriteEntry("MAME", name, "", "") for name in ("B", "A", "stale")]
    calls = []
    original = favorites.load_database

    def load(system, config):
        calls.append(system)
        return original(system, config)

    monkeypatch.setattr(favorites, "load_database", load)
    summary = recent._build_synthetic_wheel(
        cfg, "Recently Played", entries, skip_media=True, skip_launchers=True,
    )
    assert isinstance(summary, recent.RecentSummary)
    assert calls == ["MAME"]  # validation and writing share one parsed source
    assert summary.entries == 2
    games = ET.parse(summary.db_path).getroot().findall("game")
    assert [game.get("name") for game in games] == ["B", "A"]
    assert games[0].findtext("description") == "Beta (MAME)"
    assert games[0].get("custom") == "keep"
    assert games[0].findtext("custom-child") == "value"


@pytest.mark.parametrize("ranked", [False, True])
def test_shared_writer_does_not_prune_after_media_write_failure(config_home, tmp_path, monkeypatch, ranked):
    from spindoctor import favorites, recent
    from spindoctor._wheels import mark_synthetic

    hs = tmp_path / "hs"
    source = hs / "Databases" / "MAME" / "MAME.xml"
    source.parent.mkdir(parents=True)
    source.write_text('<menu><game name="A"><description>Alpha</description></game></menu>', encoding="utf-8")
    cfg = Config(hyperspin_dir=str(hs))
    target = "Recently Played" if ranked else "Favorites"
    (cfg.databases_dir / target).mkdir()
    mark_synthetic(cfg, target)
    orphan = hs / "Media" / target / "Images" / "Wheel" / "old.png"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"keep until replacement succeeds")
    entries = [favorites.FavoriteEntry("MAME", "A", "", "")]
    pruned = []

    def fail(*args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(favorites, "apply_plan", fail)
    monkeypatch.setattr(favorites, "prune_mirrored_media", lambda *args: pruned.append(args) or [])
    with pytest.raises(OSError, match="simulated disk full"):
        if ranked:
            recent._build_synthetic_wheel(cfg, target, entries, skip_launchers=True)
        else:
            favorites.rebuild(favorites.FavoriteStore(entries, target), cfg, skip_launchers=True)
    assert pruned == []
    assert orphan.read_bytes() == b"keep until replacement succeeds"


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


def test_read_stats_file_parses_last_time_played_key(tmp_path):
    """RL writes Last_Time_Played (not Last_Played) in newer versions.

    This was causing 0 parseable records and an empty Recently Played wheel.
    """
    ini = tmp_path / "mame.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text(
        "[acedrvrw]\n"
        "Last_Time_Played=Friday June 12, 2026 08:18:02 PM\n"
        "Number_of_Times_Played=3\n"
        "Total_Time_Played=540\n"
        "\n"
        "[25pacman]\n"
        "Last_Time_Played=Thursday June 11, 2026 07:00:00 PM\n"
        "Number_of_Times_Played=1\n"
        "\n",
        encoding="utf-8",
    )
    records = _read_stats_file(ini, "MAME")
    assert {r.rom_name for r in records} == {"acedrvrw", "25pacman"}
    ace = next(r for r in records if r.rom_name == "acedrvrw")
    assert ace.last_played == datetime(2026, 6, 12, 20, 18, 2)
    assert ace.play_count == 3


def test_read_stats_file_handles_utf8_bom(tmp_path):
    """RL sometimes writes Statistics.ini with a UTF-8 BOM.

    Plain utf-8 leaves the BOM on the first section header and configparser
    raises MissingSectionHeaderError, silently dropping the whole file — so
    the system vanished from Recently Played while still appearing in Most
    Played (playtime already read these files with utf-8-sig).
    """
    ini = tmp_path / "mame.ini"
    ini.write_bytes(
        b"\xef\xbb\xbf"  # UTF-8 BOM
        b"[pacman]\n"
        b"Last_Time_Played=2026-07-01 10:00:00\n"
        b"Number_of_Times_Played=3\n"
    )
    warnings: list[str] = []
    records = _read_stats_file(ini, "MAME", warnings=warnings)
    assert [r.rom_name for r in records] == ["pacman"]
    assert warnings == []


def test_top_recent_dedupes_and_sorts():
    older = PlayRecord("snes", "Tetris", datetime(2026, 4, 1, 0, 0, 0), 1)
    newer = PlayRecord("snes", "Tetris", datetime(2026, 4, 27, 0, 0, 0), 2)
    other = PlayRecord("snes", "Mario",  datetime(2026, 4, 20, 0, 0, 0), 5)
    top = top_recent([older, newer, other], limit=2)
    assert [r.rom_name for r in top] == ["Tetris", "Mario"]
    assert top[0].play_count == 2  # the newer Tetris record won


def test_collect_play_records_walks_global_dir(config_home, tmp_path):
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


def test_rebuild_writes_recently_played_database(config_home, tmp_path):
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

    # HyperSpin must find Settings/Recently Played.ini or it shows
    # "Cannot find Recently Played.ini" when the wheel is selected.
    hs_ini = hs / "Settings" / "Recently Played.ini"
    assert hs_ini.exists(), (
        "Settings/Recently Played.ini was not written — HyperSpin will show "
        "'Cannot find Recently Played.ini' when the wheel is selected."
    )
    body = hs_ini.read_text(encoding="utf-8")
    assert "[exe info]" in body
    assert "hyperlaunch=true" in body


def test_rebuild_prunes_when_records_drop_off(config_home, tmp_path):
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


def test_rebuild_orders_by_recency_not_alphabetical(config_home, tmp_path):
    """Recently Played lists games most-recent first, even when that differs
    from alphabetical order — covering both the fresh write and a rebuild over
    an existing database file."""
    import re

    def _game_order(db_path):
        return re.findall(
            r'<game name="([^"]+)"',
            db_path.read_text(encoding="utf-8"),
        )

    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"

    (roms / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").write_text(
        "<menu>"
        "<game name=\"Apple\"><description>Apple</description></game>"
        "<game name=\"Banana\"><description>Banana</description></game>"
        "<game name=\"Cherry\"><description>Cherry</description></game>"
        "</menu>",
        encoding="utf-8",
    )
    # Newest-first ranking: Banana > Cherry > Apple. Alphabetical would be
    # Apple, Banana, Cherry — deliberately different.
    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [
            ("Apple", "2026-04-25 10:00:00", 1),
            ("Banana", "2026-04-27 18:00:00", 1),
            ("Cherry", "2026-04-26 12:00:00", 1),
        ],
    )
    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs),
                 rocketlauncher_dir=str(rl))
    save_config(cfg)

    # First build — fresh Recently Played.xml (_write_fresh path).
    summary = rebuild(cfg, limit=20, media_mode=LinkMode.COPY)
    assert _game_order(summary.db_path) == ["Banana", "Cherry", "Apple"]

    # Second build — merges over the existing file (_merge_into_tree path).
    summary = rebuild(cfg, limit=20, media_mode=LinkMode.COPY)
    assert _game_order(summary.db_path) == ["Banana", "Cherry", "Apple"]


# ─── New path: Data/Statistics/ ──────────────────────────────────────────────

def test_parse_time_handles_global_statistics_format():
    """RocketLauncher Global Statistics.ini uses 'Friday May 22, 2026 07:19:22 AM'."""
    result = _parse_time("Friday May 22, 2026 07:19:22 AM")
    assert result == datetime(2026, 5, 22, 7, 19, 22)


def test_collect_play_records_walks_data_statistics_dir(config_home, tmp_path):
    """Stats in Data/Statistics/<system>.ini (newer RL layout) are found."""
    rl = tmp_path / "rl"
    _write_stats_ini(
        rl / "Data" / "Statistics" / "MAME.ini",
        [("zingzip", "2026-05-22 07:19:22", 1)],
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg)
    assert len(records) == 1
    assert records[0].system == "MAME"
    assert records[0].rom_name == "zingzip"


def test_collect_play_records_skips_global_statistics_ini(config_home, tmp_path):
    """Global Statistics.ini in Data/Statistics/ is NOT parsed as a per-system file."""
    rl = tmp_path / "rl"
    # Write a real per-system file alongside the aggregate
    _write_stats_ini(
        rl / "Data" / "Statistics" / "MAME.ini",
        [("005", "2026-05-20 20:31:57", 3)],
    )
    # Write the aggregate (it would produce zero records if parsed as per-game)
    agg = rl / "Data" / "Statistics" / "Global Statistics.ini"
    agg.parent.mkdir(parents=True, exist_ok=True)
    agg.write_text(
        "[Last_Played_Games]\n"
        "1_System=MAME\n1_Name=zingzip\n1_Date=Friday May 22, 2026 07:19:22 AM\n",
        encoding="utf-8",
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg)
    # Only the real per-game file should contribute; aggregate file is skipped
    assert len(records) == 1
    assert records[0].rom_name == "005"


def test_collect_play_records_falls_back_to_global_statistics(
    config_home, tmp_path,
):
    """When no per-system files exist, the Global Statistics.ini fallback is used."""
    rl = tmp_path / "rl"
    agg = rl / "Data" / "Statistics" / "Global Statistics.ini"
    agg.parent.mkdir(parents=True, exist_ok=True)
    agg.write_text(
        "[Last_Played_Games]\n"
        "1_System=MAME\n1_Name=zingzip\n"
        "1_Date=Friday May 22, 2026 07:19:22 AM\n"
        "2_System=Toolkit\n2_Name=Refresh Recently Played\n"
        "2_Date=Friday May 22, 2026 07:19:05 AM\n",
        encoding="utf-8",
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg)
    # Toolkit entries are skipped; only the real game should appear
    assert len(records) == 1
    assert records[0].system == "MAME"
    assert records[0].rom_name == "zingzip"
    assert records[0].last_played == datetime(2026, 5, 22, 7, 19, 22)


def test_read_global_statistics_ini_parses_last_played(tmp_path):
    ini = tmp_path / "Global Statistics.ini"
    ini.write_text(
        "[Last_Played_Games]\n"
        "1_System=MAME\n1_Name=zingzip\n"
        "1_Description=zingzip\n"
        "1_Date=Friday May 22, 2026 07:19:22 AM\n"
        "2_System=MAME\n2_Name=005\n"
        "2_Description=005\n"
        "2_Date=Wednesday May 20, 2026 08:31:57 PM\n"
        "3_System=Toolkit\n3_Name=Refresh Recently Played\n"
        "3_Date=Friday May 22, 2026 07:19:05 AM\n",
        encoding="utf-8",
    )
    records = _read_global_statistics_ini(ini)
    # Toolkit entry skipped, two real games returned, newest first when sorted
    assert len(records) == 2
    names = {r.rom_name for r in records}
    assert names == {"zingzip", "005"}
    zingzip = next(r for r in records if r.rom_name == "zingzip")
    assert zingzip.last_played == datetime(2026, 5, 22, 7, 19, 22)


# ─── synthetic system exclusion ──────────────────────────────────────────────

def test_collect_play_records_excludes_toolkit_by_default(config_home, tmp_path):
    """Toolkit stats are excluded by default so tool runs never appear in synthetic wheels."""
    rl = tmp_path / "rl"
    gs = rl / "Settings" / "Global Statistics"
    gs.mkdir(parents=True)
    _write_stats_ini(gs / "MAME.ini", [("zingzip", "2026-04-27 18:33:12", 3)])
    _write_stats_ini(gs / "Toolkit.ini", [
        ("Refresh Favorites", "2026-04-28 10:00:00", 5),
        ("Refresh Most Played", "2026-04-28 10:01:00", 2),
    ])

    from spindoctor.config import save_config
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg)

    systems = {r.system for r in records}
    assert "MAME" in systems
    assert "Toolkit" not in systems


def test_collect_play_records_excludes_synthetic_systems_by_default(config_home, tmp_path):
    """Favorites / Recently Played / Most Played stats are excluded by default."""
    rl = tmp_path / "rl"
    gs = rl / "Settings" / "Global Statistics"
    gs.mkdir(parents=True)
    _write_stats_ini(gs / "MAME.ini", [("zingzip", "2026-04-27 18:33:12", 3)])
    _write_stats_ini(gs / "Favorites.ini", [("strider", "2026-04-28 10:00:00", 1)])
    _write_stats_ini(gs / "Recently Played.ini", [("strider", "2026-04-29 11:00:00", 1)])
    _write_stats_ini(gs / "Most Played.ini", [("strider", "2026-04-30 12:00:00", 2)])

    from spindoctor.config import save_config
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg)

    systems = {r.system for r in records}
    assert "MAME" in systems
    assert "Favorites" not in systems
    assert "Recently Played" not in systems
    assert "Most Played" not in systems


def test_collect_play_records_includes_synthetic_when_exclusion_cleared(config_home, tmp_path):
    """Passing exclude_systems=None returns all systems including synthetic."""
    rl = tmp_path / "rl"
    gs = rl / "Settings" / "Global Statistics"
    gs.mkdir(parents=True)
    _write_stats_ini(gs / "MAME.ini", [("zingzip", "2026-04-27 18:33:12", 1)])
    _write_stats_ini(gs / "Favorites.ini", [("strider", "2026-04-28 10:00:00", 1)])

    from spindoctor.config import save_config
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg, exclude_systems=None)

    systems = {r.system for r in records}
    assert "MAME" in systems
    assert "Favorites" in systems


def test_collect_play_records_excludes_custom_target_system(config_home, tmp_path):
    """A custom target_system name is also excluded when passed explicitly."""
    rl = tmp_path / "rl"
    gs = rl / "Settings" / "Global Statistics"
    gs.mkdir(parents=True)
    _write_stats_ini(gs / "MAME.ini", [("zingzip", "2026-04-27 18:33:12", 1)])
    _write_stats_ini(gs / "My Custom Wheel.ini", [("strider", "2026-04-28 10:00:00", 1)])

    from spindoctor.recent import SYNTHETIC_SYSTEM_NAMES
    from spindoctor.config import save_config
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    records = collect_play_records(cfg, exclude_systems=SYNTHETIC_SYSTEM_NAMES | {"My Custom Wheel"})

    systems = {r.system for r in records}
    assert "MAME" in systems
    assert "My Custom Wheel" not in systems


def test_rebuild_excludes_favorites_system_via_fallback(config_home, tmp_path):
    """Entries with system='Favorites' from Global Statistics.ini fallback must be excluded.

    When a game is played from the Favorites wheel, RocketLauncher records a
    'Favorites' system entry in Global Statistics.ini.  If the cabinet has no
    per-system stats files, the fallback reads that file — and 'Favorites' entries
    must be dropped so they don't land in the Recently Played wheel.
    """
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"

    (roms / "Nintendo Entertainment System").mkdir(parents=True)
    (hs / "Databases" / "Nintendo Entertainment System").mkdir(parents=True)
    (hs / "Databases" / "Nintendo Entertainment System" /
     "Nintendo Entertainment System.xml").write_text(
        "<menu><game name=\"Kirby's Adventure\">"
        "<description>Kirby's Adventure</description></game></menu>",
        encoding="utf-8",
    )
    # Simulate Favorites DB dir existing on disk (created by a prior fav rebuild)
    (hs / "Databases" / "Favorites").mkdir(parents=True)
    (hs / "Media" / "Nintendo Entertainment System" / "Images" / "Wheel").mkdir(parents=True)
    (hs / "Media" / "Nintendo Entertainment System" / "Images" / "Wheel" /
     "Kirby's Adventure.png").write_bytes(b"w")

    # No per-system stats files — only the aggregate Global Statistics.ini,
    # which contains a 'Favorites' entry from a Favorites-wheel launch.
    agg = rl / "Data" / "Statistics" / "Global Statistics.ini"
    agg.parent.mkdir(parents=True, exist_ok=True)
    agg.write_text(
        "[Last_Played_Games]\n"
        "1_System=Favorites\n"
        "1_Name=Kirby's Adventure\n"
        "1_Date=Friday May 23, 2026 07:19:22 AM\n"
        "2_System=Nintendo Entertainment System\n"
        "2_Name=Kirby's Adventure\n"
        "2_Date=Friday May 23, 2026 07:18:00 AM\n",
        encoding="utf-8",
    )

    cfg = Config(
        roms_dir=str(roms), hyperspin_dir=str(hs), rocketlauncher_dir=str(rl),
    )
    save_config(cfg)

    summary = rebuild(cfg, limit=20, media_mode=LinkMode.COPY)

    # The NES entry should appear; the Favorites entry must not
    assert summary.entries == 1
    db_text = summary.db_path.read_text(encoding="utf-8")
    assert "Nintendo Entertainment System" in db_text
    assert "Favorites" not in db_text


def test_rebuild_uses_description_not_rom_name(config_home, tmp_path):
    """Regression: wheel description must come from the DB description field, not the ROM filename."""
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"
    (roms / "MAME").mkdir(parents=True)
    (hs / "Databases" / "MAME").mkdir(parents=True)
    (hs / "Databases" / "MAME" / "MAME.xml").write_text(
        "<menu><game name=\"mslug\">"
        "<description>Metal Slug - Super Vehicle-001</description>"
        "</game></menu>",
        encoding="utf-8",
    )
    (hs / "Media" / "MAME" / "Images" / "Wheel").mkdir(parents=True)
    (hs / "Media" / "MAME" / "Images" / "Wheel" / "mslug.png").write_bytes(b"w")

    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "MAME.ini",
        [("mslug", "2026-05-01 12:00:00", 3)],
    )
    cfg = Config(
        roms_dir=str(roms), hyperspin_dir=str(hs), rocketlauncher_dir=str(rl),
    )
    save_config(cfg)

    summary = rebuild(cfg, limit=20, media_mode=LinkMode.COPY)
    assert summary.entries == 1
    db_text = summary.db_path.read_text(encoding="utf-8")
    assert "Metal Slug - Super Vehicle-001" in db_text, (
        "description should use the DB description, not the raw ROM name"
    )
    assert ">mslug<" not in db_text, (
        "raw ROM name must not appear as the description in the wheel DB"
    )


def test_standalone_rebuild_media_mode_defaults_to_auto():
    from spindoctor.recent import _build_parser
    args = _build_parser().parse_args(["rebuild"])
    assert args.media_mode == "auto"


def test_standalone_version_flag_reports_version(capsys):
    # The GUI and scheduled .bat run this sibling exe directly, so it must
    # report its own version (independently of `spindoctor --version`) to
    # diagnose a stale copy left behind by a partial upgrade. --version must
    # win over the otherwise-required subcommand.
    import spindoctor.recent as recent_mod
    from spindoctor import __version__
    with pytest.raises(SystemExit) as exc:
        recent_mod.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("builder", ["favorites", "recent"])
def test_wheel_rebuild_preserves_theme_contents_and_system_media(config_home, tmp_path, builder):
    hs = tmp_path / "hs"
    source = "SNES"
    target = "Favorites" if builder == "favorites" else "Recently Played"
    _write_bytes(hs / "Databases" / source / f"{source}.xml", b'<menu><game name="Tetris"/></menu>')
    media = hs / "Media"
    _write_bytes(media / source / "Themes" / "Tetris" / "Theme.xml")
    _write_bytes(media / source / "Themes" / "Tetris" / "bg.png")
    protected = [
        _write_bytes(media / target / "Themes" / "default.zip", b"custom theme"),
        _write_bytes(media / target / "Sound" / "Wheel Click.mp3", b"custom click"),
        _write_bytes(media / target / "Images" / "Letters" / "A.png", b"letter"),
    ]
    stale = _write_bytes(media / target / "Images" / "Wheel" / "Removed.png")
    cfg = config.Config(hyperspin_dir=str(hs))
    entry = favorites.FavoriteEntry(source, "Tetris", "Tetris", "")
    for _ in range(2):
        if builder == "favorites":
            favorites.rebuild(favorites.FavoriteStore([entry], target), cfg, skip_launchers=True)
        else:
            recent._build_synthetic_wheel(cfg, target, [entry], skip_launchers=True)
    assert (media / target / "Themes" / "Tetris" / "Theme.xml").exists()
    assert (media / target / "Themes" / "Tetris" / "bg.png").exists()
    assert [p.read_bytes() for p in protected] == [b"custom theme", b"custom click", b"letter"]
    assert not stale.exists()


@pytest.mark.parametrize("name", ["", " ", "..", "../MAME", "MAME/child", "C:\\MAME"])
def test_clear_wheel_rejects_invalid_target(config_home, tmp_path, name):
    cfg = config.Config(hyperspin_dir=str(tmp_path))
    with pytest.raises(ValueError):
        recent.clear_wheel_artifacts(cfg, name, dry_run=True)


@pytest.mark.parametrize("operation", ["clear", "favorites", "recent"])
def test_real_pc_wheel_is_not_owned_because_it_has_launchers(tmp_path, operation):
    cfg = config.Config(hyperspin_dir=str(tmp_path / "hs"), rocketlauncher_dir=str(tmp_path / "rl"))
    name = "PC Games"
    db = _write_bytes(cfg.databases_dir / name / f"{name}.xml", b"<menu/>")
    ini = _write_bytes(tmp_path / "rl" / "Modules" / "PCLauncher" / name / "Game.ini")
    art = _write_bytes(cfg.media_dir / name / "Images" / "Wheel" / "Game.png")
    with pytest.raises(ValueError, match="non-synthetic"):
        if operation == "clear":
            recent.clear_wheel_artifacts(cfg, name, dry_run=False)
        elif operation == "favorites":
            favorites.rebuild(favorites.FavoriteStore([], name), cfg, skip_launchers=True)
        else:
            recent._build_synthetic_wheel(cfg, name, [], skip_launchers=True)
    assert db.read_bytes() == b"<menu/>"
    assert ini.read_bytes() == art.read_bytes() == b"original"
    assert not (db.parent / ".spindoctor-synthetic").exists()


def test_marked_custom_wheel_remains_rebuildable(tmp_path):
    cfg = config.Config(hyperspin_dir=str(tmp_path / "hs"))
    name = "My Favorites"
    db = _write_bytes(cfg.databases_dir / name / f"{name}.xml", b"<menu/>")
    _write_bytes(db.parent / ".spindoctor-synthetic", b"")
    favorites.rebuild(favorites.FavoriteStore([], name), cfg, skip_launchers=True)
    assert db.exists()
