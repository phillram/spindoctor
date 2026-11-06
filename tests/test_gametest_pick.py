"""``spindoctor test``: picking games and checking their files.

The file check must use RocketLauncher's own rules, as ``doctor`` does, so a
game that can't launch is reported as skipped (with the reason) instead of
costing a 90-second "didn't start".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from spindoctor import gametest
from spindoctor.edit import EditFilter, _matches, genre_matches
from spindoctor.database import GameEntry
from spindoctor.rl_rom_paths import _RomLookup

from tests.gametest_helpers import build_cabinet


def _names(plan):
    return [(g.system, g.game) for g in plan.games]


def test_per_system_default_picks_three_ready_games_in_wheel_order(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["NES"], seed=1)
    # Missing (no ROM) and Hidden (enabled=No) are never random picks.
    assert sorted(g.game for g in plan.games) == ["Alpha", "Bravo", "Charlie"]
    assert all(g.launch for g in plan.games)
    assert [g.game for g in plan.games] == ["Alpha", "Bravo", "Charlie"]


def test_random_picks_repeat_with_the_same_seed(tmp_path):
    cfg = build_cabinet(tmp_path)
    a = gametest.pick_games(cfg, systems=["NES"], per_system=2, seed=7)
    b = gametest.pick_games(cfg, systems=["NES"], per_system=2, seed=7)
    assert _names(a) == _names(b) and len(a.games) == 2


def test_all_lists_every_enabled_game_and_says_why_one_cannot_launch(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    assert [g.game for g in plan.games] == ["Alpha", "Bravo", "Charlie", "Missing"]
    missing = plan.games[-1]
    assert not missing.launch
    assert "game file not found in Rom_Path (.nes, .zip)" in missing.reason
    assert "Rom_Path" in missing.fix
    assert [g.game for g in plan.to_launch] == ["Alpha", "Bravo", "Charlie"]
    assert plan.games[0].description == "Alpha (USA)"
    assert plan.games[0].emulator == "Nestopia"


def test_genre_is_the_whole_genre_unless_wildcards(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["NES"], genres=["shooter"], all_games=True)
    assert [g.game for g in plan.games] == ["Alpha", "Missing"]
    plan = gametest.pick_games(cfg, systems=["NES"], genres=["Shoot*"], all_games=True)
    assert [g.game for g in plan.games] == ["Alpha", "Charlie", "Missing"]


def test_genre_without_a_system_searches_every_launchable_wheel(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, genres=["Shooter"], count=8, seed=3)
    # Missing has no ROM; PC Games, Direct, Favorites and Orphan are skipped.
    assert sorted(_names(plan)) == [("MAME", "galaga"), ("NES", "Alpha")]
    skipped = dict(plan.skipped_systems)
    assert "PCLauncher" in skipped["PC Games"]
    assert "HyperSpin starts these games itself" in skipped["Direct"]
    assert "Custom Wheel" in skipped["Favorites"]
    assert "no settings" in skipped["Orphan"]


def test_count_draws_from_all_wheels_together(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["NES", "MAME"], count=4, seed=11)
    assert len(plan.games) == 4
    assert {g.system for g in plan.games} <= {"NES", "MAME"}
    assert all(g.launch for g in plan.games)


def test_game_patterns_list_every_match(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["NES"], games=["?ravo", "miss*"])
    assert [g.game for g in plan.games] == ["Bravo", "Missing"]
    plan = gametest.pick_games(cfg, games=["galaga"])
    assert _names(plan) == [("MAME", "galaga")]


def test_naming_a_skipped_wheel_launches_it(tmp_path):
    cfg = build_cabinet(tmp_path)
    cfg.test_skip_systems = ["MAME"]
    plan = gametest.pick_games(cfg, all_systems=True, all_games=True)
    assert ("MAME", "on the test_skip_systems list") in plan.skipped_systems
    plan = gametest.pick_games(cfg, systems=["mame", "Favorites", "PC Games"], all_games=True)
    assert {g.system for g in plan.games} == {"MAME", "Favorites", "PC Games"}
    assert plan.skipped_systems == []


def test_hyperspin_launched_wheels_are_skipped_even_when_named(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["Direct"], all_games=True, include_skipped=True)
    assert plan.games == []
    assert plan.skipped_systems[0][0] == "Direct"


def test_include_skipped_takes_the_skip_rules_off(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, all_systems=True, all_games=True, include_skipped=True)
    systems = {g.system for g in plan.games}
    assert {"NES", "MAME", "PC Games", "Favorites"} <= systems
    assert {s for s, _w in plan.skipped_systems} == {"Direct", "Orphan"}


def test_settings_switches_turn_the_skips_off(tmp_path):
    cfg = build_cabinet(tmp_path)
    cfg.test_skip_pclauncher = False
    cfg.test_skip_custom_wheels = False
    plan = gametest.pick_games(cfg, all_systems=True, all_games=True)
    assert {"PC Games", "Favorites"} <= {g.system for g in plan.games}


def test_unknown_wheel_and_empty_selection_are_errors(tmp_path):
    cfg = build_cabinet(tmp_path)
    with pytest.raises(gametest.PlanError, match="No wheel named"):
        gametest.pick_games(cfg, systems=["Atari 9000"])
    with pytest.raises(gametest.PlanError, match="--system"):
        gametest.pick_games(cfg)


def test_main_menu_wheels_leave_out_search(tmp_path):
    cfg = build_cabinet(tmp_path)
    assert "Search" not in gametest.main_menu_wheels(cfg)
    assert gametest.main_menu_wheels(cfg)[0] == "NES"


# ─── the per-game file check ──────────────────────────────────────────────────

def _check(cfg, system, game):
    look = _RomLookup(Path(cfg.rocketlauncher_dir))
    return gametest.check_game(look, system, game)


def test_games_ini_emulator_override_is_used(tmp_path):
    cfg = build_cabinet(tmp_path)
    assert _check(cfg, "MAME", "pacman") == ("MAME2", "", "")
    assert _check(cfg, "MAME", "galaga") == ("MAME", "", "")


def test_missing_emulator_program_is_a_problem(tmp_path):
    cfg = build_cabinet(tmp_path)
    (tmp_path / "emu" / "mame2.exe").unlink()
    emu, problem, fix = _check(cfg, "MAME", "pacman")
    assert emu == "MAME2"
    assert problem.startswith("emulator not found:") and "mame2.exe" in problem
    assert "Emu_Path" in fix
    assert _check(cfg, "MAME", "galaga")[1] == ""


def test_missing_module_is_a_problem_unless_a_game_module_replaces_it(tmp_path):
    cfg = build_cabinet(tmp_path)
    rl = Path(cfg.rocketlauncher_dir)
    (rl / "Modules" / "Nestopia" / "Nestopia.ahk").unlink()
    problem = _check(cfg, "NES", "Alpha")[1]
    assert problem.startswith("RocketLauncher module not found:") and "Nestopia.ahk" in problem
    gm = rl / "Modules" / "Game Modules" / "Alpha" / "Alpha.ahk"
    gm.parent.mkdir(parents=True)
    gm.write_text("; game module", encoding="utf-8")
    assert _check(cfg, "NES", "Alpha")[1] == ""


def test_modules_path_setting_moves_the_modules_folder(tmp_path):
    cfg = build_cabinet(tmp_path)
    rl = Path(cfg.rocketlauncher_dir)
    (rl / "Settings" / "RocketLauncher.ini").write_text(
        "[Settings]\nModules_Path=.\\Mods\n", encoding="utf-8")
    assert "module not found" in _check(cfg, "NES", "Alpha")[1]
    target = rl / "Mods" / "Nestopia" / "Nestopia.ahk"
    target.parent.mkdir(parents=True)
    target.write_text("; module", encoding="utf-8")
    assert _check(cfg, "NES", "Alpha")[1] == ""


def test_no_emu_path_is_a_problem_but_not_for_pclauncher(tmp_path):
    cfg = build_cabinet(tmp_path)
    ini = Path(cfg.rocketlauncher_dir) / "Settings" / "NES" / "Emulators.ini"
    ini.write_text(ini.read_text(encoding="utf-8").replace("Emu_Path=", "Old_Path="), encoding="utf-8")
    assert _check(cfg, "NES", "Alpha")[1] == "no Emu_Path for Nestopia"
    assert _check(cfg, "PC Games", "Doom") == ("PCLauncher", "", "")


def test_skipchecks_rom_only_skips_the_rom_search(tmp_path):
    cfg = build_cabinet(tmp_path)
    assert _check(cfg, "NES", "Missing")[1]
    (Path(cfg.rocketlauncher_dir) / "Settings" / "NES" / "RocketLauncher.ini").write_text(
        "[Settings]\nSkipchecks=Rom Only\n", encoding="utf-8")
    assert _check(cfg, "NES", "Missing")[1] == ""


def test_rocketlauncher_stops_are_reported(tmp_path):
    cfg = build_cabinet(tmp_path)
    ini = Path(cfg.rocketlauncher_dir) / "Settings" / "NES" / "Emulators.ini"
    ini.write_text(ini.read_text(encoding="utf-8").replace("Default_Emulator=Nestopia", "Default_Emulator="),
                   encoding="utf-8")
    emu, problem, fix = _check(cfg, "NES", "Alpha")
    assert "stops before looking for it" in problem and "Default_Emulator" in problem
    assert "Default_Emulator" in fix


def test_system_override_to_a_system_with_no_settings(tmp_path):
    cfg = build_cabinet(tmp_path)
    (Path(cfg.rocketlauncher_dir) / "Settings" / "NES" / "Games.ini").write_text(
        "[Bravo]\nSystem=Famicom\n", encoding="utf-8")
    problem = _check(cfg, "NES", "Bravo")[1]
    assert "Famicom" in problem and "no RocketLauncher settings" in problem


def test_doctor_rom_paths_unchanged_by_the_shared_lookup(tmp_path):
    """``doctor`` now resolves each game through ``_RomLookup.game_source``."""
    from spindoctor import health

    cfg = build_cabinet(tmp_path)
    check = health.check_rom_paths(cfg)
    nes = next(c for c in check.children if c.name == "NES")
    assert any("Missing" in (row.detail or "") for row in nes.children)
    mame = next(c for c in check.children if c.name == "MAME")
    assert mame.status == health.Status.OK


# ─── the shared genre rule ────────────────────────────────────────────────────

@pytest.mark.parametrize("genre, wanted, hit", [
    ("Shooter", "shooter", True),
    ("Shooter / Flying", "Shooter", False),
    ("Shooter / Flying", "Shoot*", True),
    ("Platform", "?latform", True),
    ("", "Shooter", False),
    (None, "*", True),
])
def test_genre_matches(genre, wanted, hit):
    assert genre_matches(genre, wanted) is hit


def test_batch_edit_filter_gets_genre_wildcards():
    game = GameEntry(name="x", description="x", genre="Shooter / Flying")
    assert _matches(EditFilter(system="S", genre="shoot*"), game)
    assert not _matches(EditFilter(system="S", genre="Shooter"), game)
