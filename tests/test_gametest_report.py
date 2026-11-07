"""``spindoctor test``: the HTML report and the per-game ``doctor`` notes."""
from __future__ import annotations

import json
from pathlib import Path

from spindoctor import coin_start, gametest, gametest_notes
from spindoctor.gametest_report import write_report

from tests.gametest_helpers import FakeWindows, GameBehaviour, build_cabinet, home  # noqa: F401


def _embedded(html: str) -> dict:
    start = html.index("const DATA = ") + len("const DATA = ")
    return json.loads(html[start:html.index(";</script>", start)])


def test_the_report_embeds_the_run_and_survives_script_tags(tmp_path):
    data = {"run": {"started": "2026-11-06T12:00:00", "finished": True, "seconds": 20},
            "results": [{"System": "NES", "Game": "</script><b>x", "Status": "PASS", "Reason": "ok",
                         "Doctor": "", "Screenshot": "screenshots/NES/x.jpg"}]}
    path = write_report(tmp_path, data)
    html = path.read_text(encoding="utf-8")
    assert html.count("</script>") == 2  # the page's own two script blocks only
    assert _embedded(html) == data
    assert "<title>Game Test Report</title>" in html


def test_a_run_writes_report_html_with_every_row(tmp_path, home):
    cfg = build_cabinet(tmp_path)
    fake = FakeWindows(Path(cfg.rocketlauncher_dir), [GameBehaviour(), GameBehaviour(black=True)])
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    summary = gametest.run_plan(cfg, plan, gametest.RunSettings(game_seconds=5, cooldown=0), fake)
    data = _embedded((summary.run_dir / "report.html").read_text(encoding="utf-8"))
    assert [(r["Game"], r["Status"]) for r in data["results"]] == [
        ("Missing", "SKIPPED"), ("Alpha", "PASS"), ("Bravo", "WARN"), ("Charlie", "PASS")]
    assert data["run"]["finished"] is True


# ─── doctor notes ─────────────────────────────────────────────────────────────

def _ahk(lines):
    return ("class SystemUserFunction extends UserFunction {\n\tInitUserFeatures() {\n"
            + "".join(f"\t\t{line}\n" for line in lines) + "\t}\n}\n")


def test_no_notes_on_a_clean_cabinet(tmp_path):
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["NES", "MAME"], all_games=True)
    assert [g.doctor for g in plan.games] == ["", "", "", "", "", ""]


def test_a_user_functions_problem_is_noted_on_its_game(tmp_path):
    cfg = build_cabinet(tmp_path)
    uf = Path(cfg.rocketlauncher_dir) / "Lib" / "User Functions"
    uf.joinpath("NES").mkdir(parents=True)
    gone = tmp_path / "Gone" / "LCore.exe"
    (uf / "NES" / "Alpha.ahk").write_text(_ahk([f"Run, {gone}"]), encoding="utf-8")
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    notes = {g.game: g.doctor for g in plan.games}
    assert notes["Alpha"].startswith("User Functions Lib\\User Functions\\NES\\Alpha.ahk: ")
    assert "isn't there" in notes["Alpha"]
    assert notes["Bravo"] == ""


def test_a_system_user_functions_file_applies_to_all_its_games(tmp_path):
    cfg = build_cabinet(tmp_path)
    uf = Path(cfg.rocketlauncher_dir) / "Lib" / "User Functions"
    uf.mkdir(parents=True)
    (uf / "NES.ahk").write_text(_ahk([f"Run, {tmp_path / 'Gone.exe'}"]), encoding="utf-8")
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    assert all("NES.ahk" in g.doctor for g in plan.games)


def test_hyperspin_roms_only_hides_games_it_cant_find(tmp_path):
    cfg = build_cabinet(tmp_path)
    ini = Path(cfg.hyperspin_dir) / "Settings" / "NES.ini"
    roms = tmp_path / "roms" / "NES"
    ini.write_text(f"[filters]\nroms_only=true\n[exe info]\nrompath={roms}\nromextension=nes\n",
                   encoding="utf-8")
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    notes = {g.game: g.doctor for g in plan.games}
    assert notes["Alpha"] == ""
    assert notes["Missing"].startswith("HyperSpin ROMs only: HyperSpin hides this game")
    ini.write_text(f"[filters]\nroms_only=true\n[exe info]\nrompath={tmp_path / 'gone'}\n",
                   encoding="utf-8")
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    assert all("can't be read" in g.doctor for g in plan.games)


def test_spaced_names_are_noted(tmp_path):
    cfg = build_cabinet(tmp_path)
    db = Path(cfg.hyperspin_dir) / "Databases" / "NES" / "NES.xml"
    db.write_text(db.read_text(encoding="utf-8").replace('name="Bravo"', 'name="Bravo "'),
                  encoding="utf-8")
    plan = gametest.pick_games(cfg, systems=["NES"], all_games=True)
    bravo = next(g for g in plan.games if g.game == "Bravo")
    assert bravo.doctor == ("Spaces in game names: the database writes it as 'Bravo ', "
                            "so HyperSpin looks for its media under that name")


def test_coin_start_findings_are_noted(tmp_path, monkeypatch):
    class Reader:
        def fix(self):
            return "rebind Start in MAME's Tab menu"

    class Finding:
        def text(self):
            return "galaga (1 Player Start: joystick only)"

    monkeypatch.setattr(gametest_notes._CoinStart, "_reader", lambda self, system, emu: Reader())
    monkeypatch.setattr(coin_start, "check_game", lambda reader, game: Finding() if game == "galaga" else None)
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["MAME"], all_games=True)
    notes = {g.game: g.doctor for g in plan.games}
    assert notes["galaga"] == ("Coin/Start: galaga (1 Player Start: joystick only); "
                               "no key presses it (rebind Start in MAME's Tab menu)")
    assert notes["pacman"] == ""


def test_a_broken_note_never_stops_the_plan(tmp_path, monkeypatch):
    def boom(self, *a):
        raise RuntimeError("bad cfg")

    monkeypatch.setattr(gametest_notes._CoinStart, "notes", boom)
    cfg = build_cabinet(tmp_path)
    plan = gametest.pick_games(cfg, systems=["MAME"], all_games=True)
    assert [g.doctor for g in plan.games] == ["", ""]


def test_notes_reach_the_results_and_the_dry_run_listing(tmp_path, home):
    from click.testing import CliRunner
    from spindoctor.cli import cli
    from spindoctor.config import save_config

    cfg = build_cabinet(tmp_path)
    db = Path(cfg.hyperspin_dir) / "Databases" / "NES" / "NES.xml"
    db.write_text(db.read_text(encoding="utf-8").replace('name="Bravo"', 'name="Bravo "'),
                  encoding="utf-8")
    save_config(cfg)
    result = CliRunner().invoke(cli, ["test", "--system", "NES", "--all"])
    assert result.exit_code == 0, result.output
    assert "doctor: Spaces in game names" in result.output
    fake = FakeWindows(Path(cfg.rocketlauncher_dir))
    plan = gametest.pick_games(cfg, systems=["NES"], games=["Bravo"])
    summary = gametest.run_plan(cfg, plan, gametest.RunSettings(game_seconds=5, cooldown=0), fake)
    row = gametest.read_csv(summary.run_dir / "results.csv")[0]
    assert row["Game"] == "Bravo" and row["Doctor"].startswith("Spaces in game names")
