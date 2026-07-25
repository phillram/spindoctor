"""Playtime stats: parse RL Statistics + aggregate + build Most Played wheel."""
from __future__ import annotations

import csv
import json
from datetime import datetime

import pytest

import spindoctor.config as config_mod
from spindoctor.config import Config, save_config
from spindoctor.medialink import LinkMode
from spindoctor.playtime import (
    DEFAULT_PLAYED_SYSTEM, PlayStat, _read_playstats_file,
    _read_global_statistics_ini,
    aggregate_by_system, build_most_played_wheel, export_csv, export_json,
    format_duration, load_all_playtime, most_recent, top_games,
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
    """*sections* is a list of dicts with keys
    name, last, count, total, avg (any may be missing)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for s in sections:
        lines.append(f"[{s['name']}]")
        if "last" in s:
            lines.append(f"Last_Played={s['last']}")
        if "count" in s:
            lines.append(f"Number_of_Times_Played={s['count']}")
        if "total" in s:
            lines.append(f"Total_Time_Played={s['total']}")
        if "avg" in s:
            lines.append(f"Average_Time_Played={s['avg']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ─── format_duration ──────────────────────────────────────────────────────────

def test_format_duration_basic():
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(60) == "1m"
    assert format_duration(60 * 45 + 12) == "45m 12s"
    assert format_duration(3600) == "1h"
    assert format_duration(3661) == "1h 1m"
    assert format_duration(86400 + 3600 * 2 + 60 * 3) == "1d 2h"
    assert format_duration(-99) == "0s"
    assert format_duration("not a number") == "0s"


# ─── _read_playstats_file ─────────────────────────────────────────────────────

def test_read_playstats_file_extracts_all_keys(tmp_path):
    ini = tmp_path / "snes.ini"
    _write_stats_ini(ini, [
        {"name": "Tetris", "last": "2026-04-27 18:33:12",
         "count": 4, "total": 1234, "avg": 308},
        {"name": "Mario", "last": "2026-04-26 09:00:00",
         "count": 1, "total": 600, "avg": 600},
    ])
    rows = _read_playstats_file(ini, "Super Nintendo")
    by_name = {r.game: r for r in rows}
    assert by_name["Tetris"].times_played == 4
    assert by_name["Tetris"].total_seconds == 1234
    assert by_name["Tetris"].average_seconds == 308
    assert by_name["Tetris"].last_played == datetime(2026, 4, 27, 18, 33, 12)
    assert by_name["Mario"].total_seconds == 600


def test_read_playstats_file_skips_settings_and_empty_records(tmp_path):
    ini = tmp_path / "x.ini"
    ini.write_text(
        "[Settings]\nFoo=1\n\n"
        "[Empty]\n\n"
        "[Real]\nNumber_of_Times_Played=3\nTotal_Time_Played=180\n",
        encoding="utf-8",
    )
    rows = _read_playstats_file(ini, "X")
    assert [r.game for r in rows] == ["Real"]


# ─── load_all_playtime ────────────────────────────────────────────────────────

def test_load_all_playtime_reads_global_dir(isolated_config, tmp_path):
    rl = tmp_path / "rl"
    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [{"name": "Tetris", "last": "2026-04-27 18:33:12",
          "count": 4, "total": 600}],
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    rows = load_all_playtime(cfg)
    assert len(rows) == 1
    assert rows[0].system == "Super Nintendo"
    assert rows[0].total_seconds == 600


def test_load_all_playtime_merges_per_system_layout(isolated_config, tmp_path):
    rl = tmp_path / "rl"
    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "MAME.ini",
        [{"name": "Pac-Man", "count": 5, "total": 300,
          "last": "2026-04-01 00:00:00"}],
    )
    _write_stats_ini(
        rl / "Settings" / "MAME" / "Statistics.ini",
        [{"name": "Pac-Man", "count": 2, "total": 200,
          "last": "2026-04-10 00:00:00"}],
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    rows = load_all_playtime(cfg)
    assert len(rows) == 1
    assert rows[0].times_played == 7
    assert rows[0].total_seconds == 500
    assert rows[0].last_played == datetime(2026, 4, 10, 0, 0, 0)


# ─── aggregate / top / recent ─────────────────────────────────────────────────

def _make_stat(system, game, *, total=0, count=0, last=None, avg=0):
    return PlayStat(
        system=system, game=game, display_name=game,
        times_played=count, total_seconds=total,
        last_played=last, average_seconds=avg,
    )


def test_aggregate_by_system_sums_correctly():
    stats = [
        _make_stat("MAME", "Pac-Man", total=600, count=3),
        _make_stat("MAME", "Galaga", total=300, count=2),
        _make_stat("Super Nintendo", "Mario", total=900, count=4),
    ]
    rows = aggregate_by_system(stats)
    by_sys = {r.system: r for r in rows}
    assert by_sys["MAME"].total_seconds == 900
    assert by_sys["MAME"].times_played == 5
    assert by_sys["MAME"].unique_games_played == 2
    assert by_sys["Super Nintendo"].total_seconds == 900
    # Sort order: most-time first; MAME and SNES tied so ordering is stable.
    assert rows[0].total_seconds >= rows[-1].total_seconds


def test_top_games_orders_and_filters_by_scope():
    stats = [
        _make_stat("MAME", "Pac-Man", total=600),
        _make_stat("MAME", "Galaga", total=300),
        _make_stat("Super Nintendo", "Mario", total=900),
    ]
    top_all = top_games(stats, n=2)
    assert [s.game for s in top_all] == ["Mario", "Pac-Man"]

    top_mame = top_games(stats, n=10, scope="MAME")
    assert [s.game for s in top_mame] == ["Pac-Man", "Galaga"]


def test_most_recent_skips_records_without_timestamps():
    stats = [
        _make_stat("MAME", "Pac-Man", last=datetime(2026, 4, 1)),
        _make_stat("MAME", "Galaga", last=None),
        _make_stat("MAME", "DK", last=datetime(2026, 4, 27)),
    ]
    rows = most_recent(stats, n=10)
    assert [r.game for r in rows] == ["DK", "Pac-Man"]


# ─── export ───────────────────────────────────────────────────────────────────

def test_export_csv_writes_all_rows(tmp_path):
    stats = [
        _make_stat("MAME", "Pac-Man", total=600, count=3,
                   last=datetime(2026, 4, 1, 12, 0, 0)),
        _make_stat("Super Nintendo", "Mario", total=900, count=4),
    ]
    out = tmp_path / "stats.csv"
    export_csv(stats, out)
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    pac = next(r for r in rows if r["game"] == "Pac-Man")
    assert pac["total_seconds"] == "600"
    assert pac["times_played"] == "3"
    assert pac["total_played"] == "10m"
    assert pac["last_played"] == "2026-04-01T12:00:00"


def test_export_json_includes_totals_and_per_system(tmp_path):
    stats = [
        _make_stat("MAME", "Pac-Man", total=600, count=3,
                   last=datetime(2026, 4, 1, 12, 0, 0)),
        _make_stat("Super Nintendo", "Mario", total=900, count=4),
    ]
    out = tmp_path / "stats.json"
    export_json(stats, out)
    payload = json.loads(out.read_text())
    assert payload["totals"]["total_seconds"] == 1500
    assert payload["totals"]["total_sessions"] == 7
    assert payload["totals"]["unique_games"] == 2
    assert {r["system"] for r in payload["per_system"]} == {"MAME", "Super Nintendo"}
    assert len(payload["stats"]) == 2


# ─── build_most_played_wheel ──────────────────────────────────────────────────

def test_build_most_played_wheel_writes_db_media_and_launchers(
    isolated_config, tmp_path,
):
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"

    (roms / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").write_text(
        "<menu><game name=\"Tetris\"><description>Tetris</description>"
        "</game></menu>",
        encoding="utf-8",
    )
    (hs / "Media" / "Super Nintendo" / "Images" / "Wheel").mkdir(parents=True)
    (hs / "Media" / "Super Nintendo" / "Images" / "Wheel"
        / "Tetris.png").write_bytes(b"w")

    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [{"name": "Tetris", "last": "2026-04-27 18:33:12",
          "count": 10, "total": 7200, "avg": 720}],
    )

    cfg = Config(
        roms_dir=str(roms),
        hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
    )
    save_config(cfg)

    summary = build_most_played_wheel(
        cfg, limit=20, media_mode=LinkMode.COPY,
    )
    assert summary.entries == 1
    assert summary.target_system == DEFAULT_PLAYED_SYSTEM
    assert summary.db_path.exists()
    assert "Tetris" in summary.db_path.read_text(encoding="utf-8")
    assert (hs / "Media" / DEFAULT_PLAYED_SYSTEM
            / "Images" / "Wheel" / "Tetris.png").exists()
    inis = list((rl / "Modules" / "PCLauncher" / DEFAULT_PLAYED_SYSTEM).iterdir())
    assert len(inis) == 1


def test_build_most_played_wheel_adds_to_main_menu(isolated_config, tmp_path):
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"

    (roms / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").write_text(
        "<menu><game name=\"Tetris\"><description>Tetris</description>"
        "</game></menu>",
        encoding="utf-8",
    )
    (hs / "Databases" / "Main Menu").mkdir(parents=True)
    (hs / "Databases" / "Main Menu" / "Main Menu.xml").write_text(
        "<menu><game name=\"Super Nintendo\">"
        "<description>Super Nintendo</description></game></menu>",
        encoding="utf-8",
    )

    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [{"name": "Tetris", "last": "2026-04-27 18:33:12",
          "count": 10, "total": 7200}],
    )
    cfg = Config(
        roms_dir=str(roms), hyperspin_dir=str(hs),
        rocketlauncher_dir=str(rl),
    )
    save_config(cfg)

    build_most_played_wheel(cfg, limit=5, media_mode=LinkMode.COPY)

    menu_xml = (hs / "Databases" / "Main Menu"
                / "Main Menu.xml").read_text(encoding="utf-8")
    assert "Most Played" in menu_xml


def test_build_most_played_wheel_respects_limit(isolated_config, tmp_path):
    hs = tmp_path / "hs"
    roms = tmp_path / "roms"
    rl = tmp_path / "rl"

    (roms / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo").mkdir(parents=True)
    (hs / "Databases" / "Super Nintendo" / "Super Nintendo.xml").write_text(
        "<menu>"
        "<game name=\"A\"><description>A</description></game>"
        "<game name=\"B\"><description>B</description></game>"
        "<game name=\"C\"><description>C</description></game>"
        "</menu>",
        encoding="utf-8",
    )
    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [
            {"name": "A", "count": 1, "total": 100,
             "last": "2026-04-27 18:00:00"},
            {"name": "B", "count": 1, "total": 500,
             "last": "2026-04-27 18:00:00"},
            {"name": "C", "count": 1, "total": 300,
             "last": "2026-04-27 18:00:00"},
        ],
    )
    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs),
                 rocketlauncher_dir=str(rl))
    save_config(cfg)
    summary = build_most_played_wheel(cfg, limit=2, media_mode=LinkMode.COPY)
    assert summary.entries == 2
    db_text = summary.db_path.read_text(encoding="utf-8")
    # B and C have the most playtime; A should be excluded.
    assert "B" in db_text and "C" in db_text
    assert " name=\"A\"" not in db_text


def _game_order(db_path):
    """Return the ``<game name=...>`` values in the order they appear."""
    import re
    return re.findall(
        r'<game name="([^"]+)"',
        db_path.read_text(encoding="utf-8"),
    )


def test_build_most_played_wheel_orders_by_playtime_not_alphabetical(
    isolated_config, tmp_path,
):
    """Wheel XML lists games most-played first, even when that differs from
    alphabetical order — covering both the fresh write and a rebuild over an
    existing (alphabetically-ordered) database file."""
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
    # Ranked by total playtime: Cherry (900) > Apple (500) > Banana (100).
    # Alphabetical order would be Apple, Banana, Cherry — deliberately different.
    _write_stats_ini(
        rl / "Settings" / "Global Statistics" / "Super Nintendo.ini",
        [
            {"name": "Apple", "count": 1, "total": 500,
             "last": "2026-04-27 18:00:00"},
            {"name": "Banana", "count": 1, "total": 100,
             "last": "2026-04-27 18:00:00"},
            {"name": "Cherry", "count": 1, "total": 900,
             "last": "2026-04-27 18:00:00"},
        ],
    )
    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs),
                 rocketlauncher_dir=str(rl))
    save_config(cfg)

    # First build — fresh Most Played.xml (no prior file → _write_fresh path).
    summary = build_most_played_wheel(cfg, limit=20, media_mode=LinkMode.COPY)
    assert _game_order(summary.db_path) == ["Cherry", "Apple", "Banana"]

    # Second build — merges over the existing file (in-place _merge_into_tree
    # path). Must re-derive ranked order rather than keeping prior positions.
    summary = build_most_played_wheel(cfg, limit=20, media_mode=LinkMode.COPY)
    assert _game_order(summary.db_path) == ["Cherry", "Apple", "Banana"]


# ─── Data/Statistics/ path + Global Statistics.ini fallback ──────────────────

def _write_global_statistics_ini(path, top_time=None, top_count=None):
    """Write a minimal Global Statistics.ini with the given top-10 data.

    *top_time* and *top_count* are lists of (system, name, value) tuples.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[General]", "Total_Global_Played_Time=", ""]
    if top_time:
        lines.append("[TopTen_Time_Played]")
        for i, (sys, name, val) in enumerate(top_time, 1):
            lines += [f"{i}_System={sys}", f"{i}_Name={name}", f"{i}_Time_Played={val}"]
        lines.append("")
    if top_count:
        lines.append("[TopTen_Times_Played]")
        for i, (sys, name, val) in enumerate(top_count, 1):
            lines += [f"{i}_System={sys}", f"{i}_Name={name}", f"{i}_Times_Played={val}"]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_load_all_playtime_reads_data_statistics_dir(isolated_config, tmp_path):
    """Stats in Data/Statistics/<system>.ini (newer RL layout) are found."""
    rl = tmp_path / "rl"
    _write_stats_ini(
        rl / "Data" / "Statistics" / "MAME.ini",
        [{"name": "sf2", "count": 130, "total": 7516,
          "last": "2026-04-01 12:00:00"}],
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    rows = load_all_playtime(cfg)
    assert len(rows) == 1
    assert rows[0].system == "MAME"
    assert rows[0].game == "sf2"
    assert rows[0].total_seconds == 7516


def test_load_all_playtime_fallback_uses_global_statistics(isolated_config, tmp_path):
    """When no per-system files exist the aggregate Global Statistics.ini is used."""
    rl = tmp_path / "rl"
    _write_global_statistics_ini(
        rl / "Data" / "Statistics" / "Global Statistics.ini",
        top_time=[
            ("Nintendo DS", "Kirby Super Star Ultra", 30016),
            ("PC Games", "Plants vs. Zombies GOTY Edition", 23875),
        ],
        top_count=[
            ("MAME", "1942", 340),
        ],
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    rows = load_all_playtime(cfg)
    by_key = {(r.system, r.game): r for r in rows}
    assert ("Nintendo DS", "Kirby Super Star Ultra") in by_key
    assert by_key[("Nintendo DS", "Kirby Super Star Ultra")].total_seconds == 30016
    assert ("MAME", "1942") in by_key
    assert by_key[("MAME", "1942")].times_played == 340


def test_load_all_playtime_skips_global_statistics_when_per_system_exists(
    isolated_config, tmp_path,
):
    """Global Statistics.ini is not used when real per-system data exists."""
    rl = tmp_path / "rl"
    # Real per-system file
    _write_stats_ini(
        rl / "Data" / "Statistics" / "MAME.ini",
        [{"name": "sf2", "count": 130, "total": 7516,
          "last": "2026-04-01 12:00:00"}],
    )
    # Aggregate file alongside it — should be ignored when per-system data exists
    _write_global_statistics_ini(
        rl / "Data" / "Statistics" / "Global Statistics.ini",
        top_time=[("Nintendo DS", "Kirby Super Star Ultra", 30016)],
    )
    cfg = Config(rocketlauncher_dir=str(rl))
    save_config(cfg)
    rows = load_all_playtime(cfg)
    # Only the per-game file results should appear
    assert len(rows) == 1
    assert rows[0].game == "sf2"


def test_read_global_statistics_ini_extracts_time_and_count(tmp_path):
    ini = tmp_path / "Global Statistics.ini"
    _write_global_statistics_ini(
        ini,
        top_time=[
            ("Nintendo DS", "Kirby Super Star Ultra", 30016),
            ("MAME", "sf2", 7516),
            ("Toolkit", "Refresh Most Played", 1),   # should be skipped
        ],
        top_count=[
            ("MAME", "1942", 340),
            ("MAME", "sf2", 130),   # merges with TopTen_Time_Played entry
        ],
    )
    rows = _read_global_statistics_ini(ini)
    by_key = {(r.system, r.game): r for r in rows}
    # Toolkit entry must be skipped
    assert ("Toolkit", "Refresh Most Played") not in by_key
    # Time-played entries
    assert by_key[("Nintendo DS", "Kirby Super Star Ultra")].total_seconds == 30016
    # Count merged onto existing time entry
    assert by_key[("MAME", "sf2")].total_seconds == 7516
    assert by_key[("MAME", "sf2")].times_played == 130
    # Count-only entry (not in time list)
    assert by_key[("MAME", "1942")].times_played == 340


def test_build_most_played_excludes_favorites_system_via_fallback(
    isolated_config, tmp_path,
):
    """Entries with system='Favorites' from Global Statistics.ini fallback must be excluded.

    When a game is played from the Favorites wheel, RL records a 'Favorites'
    system entry in Global Statistics.ini.  The wheel builder must drop those
    so they don't appear in Most Played.
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
    # Simulate Favorites DB dir existing on disk
    (hs / "Databases" / "Favorites").mkdir(parents=True)
    (hs / "Media" / "Nintendo Entertainment System" / "Images" / "Wheel").mkdir(parents=True)
    (hs / "Media" / "Nintendo Entertainment System" / "Images" / "Wheel" /
     "Kirby's Adventure.png").write_bytes(b"w")

    # No per-system stats files — only Global Statistics.ini with a Favorites entry
    _write_global_statistics_ini(
        rl / "Data" / "Statistics" / "Global Statistics.ini",
        top_time=[
            ("Favorites", "Kirby's Adventure", 1800),
            ("Nintendo Entertainment System", "Kirby's Adventure", 1800),
        ],
        top_count=[
            ("Favorites", "Kirby's Adventure", 1),
            ("Nintendo Entertainment System", "Kirby's Adventure", 5),
        ],
    )

    cfg = Config(
        roms_dir=str(roms), hyperspin_dir=str(hs), rocketlauncher_dir=str(rl),
    )
    save_config(cfg)

    summary = build_most_played_wheel(
        cfg, limit=20, media_mode=LinkMode.COPY, register_in_main_menu=False,
    )

    # NES entry should appear; Favorites entry must not
    assert summary.entries == 1
    db_text = summary.db_path.read_text(encoding="utf-8")
    assert "Nintendo Entertainment System" in db_text
    assert "Favorites" not in db_text


# ─── BOM handling in playstats files ─────────────────────────────────────────


def test_read_playstats_file_handles_utf8_bom(tmp_path):
    """Statistics.ini files written by Windows / some RocketLauncher versions
    include a UTF-8 BOM (\\xef\\xbb\\xbf).  The plain 'utf-8' codec keeps
    the BOM as \\ufeff in the first section header, so [1942] becomes
    [\\ufeff1942] — silently discarding that game's stats with no error.
    'utf-8-sig' strips the BOM so the first section is read correctly."""
    stats_file = tmp_path / "Statistics.ini"
    content = "[1942]\nNumber_of_Times_Played=5\nTotal_Time_Played=600\n"
    stats_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

    results = _read_playstats_file(stats_file, "MAME")
    assert len(results) == 1, "BOM must not cause the first game to be silently dropped"
    assert results[0].game == "1942"
    assert results[0].times_played == 5


def test_standalone_build_wheel_media_mode_defaults_to_auto():
    from spindoctor.playtime import _build_parser
    args = _build_parser().parse_args(["build-wheel"])
    assert args.media_mode == "auto"
