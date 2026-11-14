"""Tests for keeping LEDBlinky's Controls.ini / Colors.ini to the wheel games.

``ledblinky generate`` / ``setup`` add entries only for wheel games (and their
parents) that have none, ``ledblinky prune`` moves the entries for games in
no wheel to SpinDoctor's LEDBlinky library, and ``--all-roms`` brings them
back exactly as they were. Every fixture lives in a temp dir; MAME never runs
(a fresh ``-listxml`` cache stands in for it).
"""
from __future__ import annotations

import os
import re
import time
import types
from pathlib import Path

from tests.helpers import encode_legacy_text as _encode_legacy_text

import pytest
from click import unstyle
from click.testing import CliRunner

from spindoctor import gui, health, ledblinky
from spindoctor import ledblinky_library as ll
from spindoctor import ledblinky_profiles as lp
from spindoctor.cli import cli
from spindoctor.config import Config

CRLF = b"\r\n"


def _machine(name, players=2, buttons=2, cloneof=""):
    clone = f' cloneof="{cloneof}"' if cloneof else ""
    return (f'<machine name="{name}"{clone}><description>{name}</description>'
            f'<input players="{players}"><control type="joy" ways="8" buttons="{buttons}"/></input></machine>')


LISTXML = ("<mame>"
           + _machine("pacman", buttons=0)
           + _machine("galaga", buttons=1)
           + _machine("mspacman", buttons=0)
           + _machine("mspacmnf", buttons=0, cloneof="mspacman")
           + _machine("dkong", buttons=1)
           + _machine("robby", buttons=1)
           + _machine("sf2", buttons=6)
           + _machine("sf2ce", buttons=6, cloneof="sf2")
           + '<machine name="neogeo"><description>BIOS</description></machine>'
           + "</mame>").encode("utf-8")


def _ini(*sections: bytes, header: bool = True) -> bytes:
    """Sections joined the way SpinDoctor's emit_ini wrote them, with CRLF line ends."""
    head = (b"; Generated/merged by SpinDoctor.\r\n; 2026-06-09T22:48:21\r\n"
            b"; Existing community-maintained entries are preserved as-is.\r\n\r\n") if header else b""
    return head + b"\r\n".join(sections)


def _sec(name: str, *lines: str) -> bytes:
    return CRLF.join([f"[{name}]".encode("utf-8")] + [ln.encode("cp1252") for ln in lines]) + CRLF


# Live files: written by an older `generate` for every ROM on disk, so they hold
# entries for games in no wheel (dkong, robby). pacman carries a hand edit and a
# byte that isn't UTF-8 (cp1252 "é"), as old community files do.
CONTROLS = _ini(
    _sec("dkong", "numPlayers=2", "alternating=0", "P1_BUTTON1=1", "P1_JOYSTICK=1", "P1_START=1", "P1_COIN=1"),
    _sec("pacman", "gamename=Pac-Man \xe9dition", "numPlayers=2", "P1_JOYSTICK=Hand edit", "P1_START=1"),
    _sec("robby", "numPlayers=1", "alternating=0", "P1_BUTTON1=1", "P1_START=1", "P1_COIN=1"),
)
COLORS = _ini(
    _sec("Contra (USA)", "P1_BUTTON1=White", "P1_START=White"),
    _sec("dkong", "P1_BUTTON1=Red", "P1_JOYSTICK=Red", "P1_START=White", "P1_COIN=White"),
    _sec("pacman", "P1_JOYSTICK=Yellow", "P1_START=Blue"),
    _sec("robby", "P1_BUTTON1=Lime", "P1_START=Red", "P1_COIN=Red"),
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _db(root: Path, system: str, games, xml_name: str = "") -> None:
    """A HyperSpin database: ``<System>\\<System>.xml``, or *xml_name* in that folder."""
    body = "".join(f'  <game name="{n}">\n    <description>{n}</description>\n'
                   f"    <cloneof>{c}</cloneof>\n  </game>\n" for n, c in games)
    _write(root / "Databases" / system / f"{xml_name or system}.xml", f"<menu>\n{body}</menu>\n")


@pytest.fixture
def cab(tmp_path, monkeypatch):
    """A cabinet with wheels, RocketLauncher settings, LEDBlinky files and a ROM folder."""
    home = tmp_path / "home"
    monkeypatch.setattr(ll, "LIBRARY_DIR", home / "ledblinky_library")
    monkeypatch.setattr(ledblinky, "LISTXML_CACHE_DIR", home / "mame_listxml_cache")
    monkeypatch.setattr(ledblinky, "_listxml_memo", {}, raising=False)

    def no_mame(cmd, **_kwargs):
        raise AssertionError("MAME must not run: its -listxml cache is fresh")
    monkeypatch.setattr(ledblinky.subprocess, "run", no_mame)

    exe = tmp_path / "Emulators" / "MAME" / "mame.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    old = time.time() - 3600
    os.utime(str(exe), (old, old))
    cache = ledblinky.listxml_cache_path(str(exe))
    cache.parent.mkdir(parents=True)
    cache.write_bytes(LISTXML)

    hs = tmp_path / "Arcade"
    _db(hs, "Main Menu", [(s, "") for s in ("MAME", "Capcom Play System II",
                                            "Nintendo Entertainment System", "Colecovision")])
    # MAME: LEDBlinky treats it as MAME. mspacmnf's parent isn't in any wheel.
    _db(hs, "MAME", [("pacman", ""), ("galaga", ""), ("mspacmnf", "mspacman")])
    # Launched by MAME, so its names are ROM names; sf2ce's parent comes from -listxml.
    _db(hs, "Capcom Play System II", [("sf2ce", "")])
    # A hidden wheel (not on the Main Menu) still counts.
    _db(hs, "MAME Hidden Gems", [("neogeo", "")])
    # Console wheels: in a wheel (prune keeps them), but not MAME ROM names.
    _db(hs, "Nintendo Entertainment System", [("Contra (USA)", "")])
    _db(hs, "Colecovision", [("cosmofighter", "")])

    rl = hs / "RocketLauncher"
    settings = rl / "Settings"
    _write(settings / "Global Emulators.ini",
           "[MAME]\nEmu_Path=..\\Emulators\\MAME\\mame.exe\n"
           "[RetroArch]\nEmu_Path=..\\Emulators\\RetroArch\\retroarch.exe\n")
    for system, emu in (("Capcom Play System II", "MAME"), ("Nintendo Entertainment System", "RetroArch"),
                        ("Colecovision", "MAME")):
        _write(settings / system / "Emulators.ini", f"[ROMS]\nDefault_Emulator={emu}\n")

    led = hs / "LEDBlinky"
    led.mkdir()
    (led / ledblinky.CONTROLS_INI_NAME).write_bytes(CONTROLS)
    (led / ledblinky.COLORS_INI_NAME).write_bytes(COLORS)
    _write(led / "Color-RGB.ini", "[Colors]\nRed=255,0,0\nWhite=255,255,255\nBlue=0,0,255\n")

    roms = tmp_path / "roms"
    (roms / "MAME").mkdir(parents=True)
    for rom in ("pacman", "galaga", "dkong", "robby", "mspacman"):
        (roms / "MAME" / f"{rom}.zip").write_bytes(b"PK")

    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs), ledblinky_dir=str(led),
                 rocketlauncher_dir=str(rl), mame_executable=str(exe),
                 backup_dir=str(tmp_path / "backups"))
    monkeypatch.setattr("spindoctor.cli.load_config", lambda: cfg)
    return types.SimpleNamespace(cfg=cfg, led=led, hs=hs, roms=roms, home=home, tmp=tmp_path,
                                 controls=led / ledblinky.CONTROLS_INI_NAME,
                                 colors=led / ledblinky.COLORS_INI_NAME)


def _run(*args):
    """Run ``spindoctor ledblinky <args>``; the output with table borders and wrapping removed."""
    result = CliRunner().invoke(cli, ["ledblinky", *args])
    assert result.exit_code == 0, result.output
    return " ".join(re.sub(r"[│┃|]", " ", unstyle(result.output)).split())


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def _names(raw: bytes) -> list[str]:
    return [s for s, _t in ll.RawIni(raw.decode("utf-8", "surrogateescape")).sections]


# ── raw INI editing ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_render_keeps_every_byte_and_restores_removed_sections(newline):
    text = (CONTROLS.decode("utf-8", "surrogateescape") if newline == "\r\n"
            else CONTROLS.decode("utf-8", "surrogateescape").replace("\r\n", "\n"))
    raw = ll.RawIni("﻿" + text)
    assert raw.render() == "﻿" + text
    pruned = ll.RawIni(raw.render(remove=["dkong", "robby"]))
    assert [n for n, _t in pruned.sections] == ["pacman"]
    entries = raw.entries()
    # Back where they were, byte for byte: the first and the last section.
    assert pruned.render(add={"dkong": entries["dkong"], "robby": entries["robby"]}) == "﻿" + text


def test_render_inserts_in_name_order_and_adds_only_missing_blank_lines():
    raw = ll.RawIni("[aaa]\nk=1\n\n[ccc]\nk=3\n")
    out = raw.render(add={"bbb": "[bbb]\nk=2\n", "ddd": "[ddd]\nk=4\n\n", "aaa": "[aaa]\nignored\n"})
    assert out == "[aaa]\nk=1\n\n[bbb]\nk=2\n\n[ccc]\nk=3\n\n[ddd]\nk=4\n\n"
    # No final newline in the file: one is added before the new section.
    assert ll.RawIni("[aaa]\nk=1").render(add={"b": "[b]\nk=2\n"}) == "[aaa]\nk=1\n\n[b]\nk=2\n"


def test_render_replace_keeps_position_and_drops_repeats():
    raw = ll.RawIni("[a]\nx=1\n\n[b]\nold\n\n[c]\nz\n\n[B]\nrepeat\n")
    assert raw.entries()["b"] == "[b]\nold\n\n[B]\nrepeat\n"
    assert raw.render(replace={"b": "[b]\nnew\n\n"}) == "[a]\nx=1\n\n[b]\nnew\n\n[c]\nz\n\n"


def test_write_raw_round_trips_bytes_that_are_not_utf8(tmp_path):
    path = tmp_path / "x.ini"
    path.write_bytes(CONTROLS)
    ll.write_raw(tmp_path / "y.ini", ll.read_raw(path))
    assert (tmp_path / "y.ini").read_bytes() == CONTROLS
    assert list(tmp_path.glob("*.tmp")) == []


# ── wheel scope ───────────────────────────────────────────────────────────────


def test_wheel_scope_takes_wheels_that_use_mame_rom_names(cab):
    scope = ll.wheel_scope(cab.cfg, listxml=ledblinky.load_listxml_for_system(cab.cfg, "MAME"))
    assert scope.systems == ["Capcom Play System II", "MAME", "MAME Hidden Gems"]
    assert sorted(scope.games) == ["galaga", "mspacmnf", "neogeo", "pacman", "sf2ce"]
    assert scope.wheels_of["sf2ce"] == ["Capcom Play System II"]
    # Parents from the database (mspacman) and from -listxml (sf2).
    assert scope.parents == {"mspacman": "mspacman", "sf2": "sf2"}
    assert scope.parent_of["sf2"] == "sf2ce"
    # Console wheels, the MESS one included, aren't MAME ROM names but are wheel games.
    assert "cosmofighter" not in scope.games and "cosmofighter" in scope.any_wheel
    assert "contra (usa)" in scope.keep() and "mspacman" in scope.keep()
    assert scope.names() == ["galaga", "mspacman", "mspacmnf", "neogeo", "pacman", "sf2", "sf2ce"]


def test_wheel_scope_system_limits_the_games(cab):
    scope = ll.wheel_scope(cab.cfg, system="Capcom Play System II")
    assert scope.systems == ["Capcom Play System II"]
    assert sorted(scope.games) == ["sf2ce"]
    assert "pacman" in scope.any_wheel


def test_wheel_scope_without_rocketlauncher_uses_wheel_names_only(cab):
    cab.cfg.rocketlauncher_dir = ""
    scope = ll.wheel_scope(cab.cfg)
    assert scope.systems == ["MAME", "MAME Hidden Gems"]


def test_wheel_scope_reads_the_genre_databases_hyperspin_shows(cab):
    # Genre.xml lists the genre wheels; a commented-out one isn't shown.
    _write(cab.hs / "Databases" / "MAME" / "genre.xml",
           '<menu>\n  <game name="Trackball Games"/>\n  <!--<game name="Gun Games"/>-->\n</menu>\n')
    _db(cab.hs, "MAME", [("robby", "")], xml_name="trackball games")
    _db(cab.hs, "MAME", [("dkong", "")], xml_name="Gun Games")
    scope = ll.wheel_scope(cab.cfg)
    assert scope.wheels_of["robby"] == ["MAME"]
    assert "dkong" not in scope.any_wheel
    assert "controls.ini: 3 entries, 1 for games in no wheel, 2 kept" in _run("prune")


def test_wheel_scope_adds_only_parents_mame_knows(cab):
    # Some databases put other data in <cloneof>.
    _db(cab.hs, "MAME", [("pacman", ""), ("galaga", "10")])
    scope = ll.wheel_scope(cab.cfg, listxml=ledblinky.load_listxml_for_system(cab.cfg, "MAME"))
    assert "10" not in scope.parents
    assert "10" in scope.any_parent      # prune still keeps such an entry
    assert "10" in ll.wheel_scope(cab.cfg).parents   # nothing to check it against


def test_prune_keeps_the_rom_rocketlauncher_runs_a_wheel_game_as(cab):
    # RocketLauncher's MAME module starts robby for robbyxbox; dkong4play's base is dkong.
    _write(cab.hs / "RocketLauncher" / "Modules" / "MAME" / "MAME.ini",
           "[Settings]\nCheatMode=false\n[RobbyXbox]\nMameRomName=robby\n")
    _db(cab.hs, "Four Player Games", [("robbyxbox", ""), ("dkong4play", "")])
    assert ll.mame_rom_names(cab.cfg) == {"robbyxbox": "robby"}
    assert {"robby", "dkong"} <= ll.wheel_scope(cab.cfg).any_parent
    out = _run("prune")
    assert "controls.ini: 3 entries, 0 for games in no wheel, 3 kept" in out
    assert "Nothing to prune" in out
    # In a MAME-named wheel, the renamed ROM is added like a parent.
    _db(cab.hs, "MAME", [("pacman", ""), ("robbyxbox", "")])
    assert ll.wheel_scope(cab.cfg).parent_of["robby"] == "robbyxbox"


# ── generate ──────────────────────────────────────────────────────────────────


def test_generate_adds_only_missing_wheel_games_and_parents(cab):
    out = _run("generate", "--apply")
    assert "Scope: 5 games in 3 wheels, plus 2 parent ROMs" in out
    controls = cab.controls.read_bytes()
    colors = cab.colors.read_bytes()
    # neogeo has no input data, so it gets nothing.
    assert _names(controls) == ["dkong", "galaga", "mspacman", "mspacmnf", "pacman", "robby", "sf2", "sf2ce"]
    assert _names(colors) == ["Contra (USA)", "dkong", "galaga", "mspacman", "mspacmnf", "pacman",
                              "robby", "sf2", "sf2ce"]
    # Every existing entry, the header and the non-UTF-8 byte are untouched, and
    # taking the new sections out again gives back the original file.
    for _name, text in ll.RawIni(_text(CONTROLS)).sections:
        assert text in _text(controls)
    assert controls.startswith(CONTROLS[:CONTROLS.index(b"[dkong]")])
    assert b"Pac-Man \xe9dition" in controls
    new = ["galaga", "mspacman", "mspacmnf", "sf2", "sf2ce"]
    assert ll.RawIni(_text(controls)).render(remove=new).rstrip() == _text(CONTROLS).rstrip()
    assert b"\r\n[galaga]\r\nnumPlayers=2\r\n" in controls     # the file's own line ends
    # Backups went to backup_dir, not next to the live files.
    assert sorted(p.name.split(".")[0] for p in (cab.tmp / "backups" / "LEDBlinky").iterdir()) \
        == ["Colors", "controls"]


def test_generate_dry_run_and_nothing_missing_leave_files_alone(cab):
    _run("generate")
    assert cab.controls.read_bytes() == CONTROLS
    _run("generate", "--apply")
    after = cab.controls.read_bytes(), cab.colors.read_bytes()
    stamp = cab.controls.stat().st_mtime
    out = _run("generate", "--apply")
    assert "Nothing missing" in out
    assert (cab.controls.read_bytes(), cab.colors.read_bytes()) == after
    assert cab.controls.stat().st_mtime == stamp


def test_generate_matches_names_case_insensitively(cab):
    cab.controls.write_bytes(CONTROLS.replace(b"[pacman]", b"[PacMan]"))
    _run("generate", "--apply")
    names = _names(cab.controls.read_bytes())
    assert "PacMan" in names and "pacman" not in names


def test_generate_system_limits_to_that_wheel(cab):
    _run("generate", "--system", "Capcom Play System II", "--apply")
    assert _names(cab.controls.read_bytes()) == ["dkong", "pacman", "robby", "sf2", "sf2ce"]


def test_generate_takes_a_missing_entry_from_the_library_first(cab):
    ll.Library().save(controls={"galaga": "[galaga]\r\nnumPlayers=1\r\nP1_BUTTON1=Fire (kept)\r\n\r\n"},
                      colors={})
    out = _run("generate", "--apply")
    assert "From SpinDoctor's library: 1 controls, 0 colors" in out
    assert b"[galaga]\r\nnumPlayers=1\r\nP1_BUTTON1=Fire (kept)\r\n\r\n" in cab.controls.read_bytes()


def test_generate_overwrite_resynthesises_in_place(cab):
    _run("generate", "--overwrite", "--apply")
    entry = ll.RawIni.load(cab.controls).entries()["pacman"]
    assert "Hand edit" not in entry and "P1_JOYSTICK=1" in entry
    assert _names(cab.controls.read_bytes())[:3] == ["dkong", "galaga", "mspacman"]


def test_generate_output_dir_leaves_the_live_files(cab):
    out_dir = cab.tmp / "out"
    _run("generate", "--apply", "--output-dir", str(out_dir))
    assert cab.controls.read_bytes() == CONTROLS
    assert "galaga" in _names((out_dir / ledblinky.CONTROLS_INI_NAME).read_bytes())


def test_setup_uses_the_wheel_scope(cab):
    out = _run("setup", "--apply", "--no-backup")
    assert "Scope: 5 games in 3 wheels" in out
    assert "galaga" in _names(cab.controls.read_bytes())


# ── prune, and adding everything back ─────────────────────────────────────────


def test_prune_dry_run_changes_nothing(cab):
    out = _run("prune")
    assert "controls.ini: 3 entries, 2 for games in no wheel, 1 kept" in out
    assert "Colors.ini : 4 entries, 2 for games in no wheel, 2 kept" in out
    assert "Dry-run" in out
    assert cab.controls.read_bytes() == CONTROLS and cab.colors.read_bytes() == COLORS
    assert not ll.LIBRARY_DIR.exists()


def test_prune_saves_to_the_library_first_then_trims(cab):
    (cab.led / "controls.ini.20200101_000000.bak").write_text(
        "[galaga]\nP1NumButtons=1\nP1_BUTTON1=Fire\n", encoding="utf-8")
    out = _run("prune", "--apply")
    assert "Pruned." in out
    # Kept: wheel games of any wheel (the console's Colors.ini entry too), untouched.
    assert _names(cab.controls.read_bytes()) == ["pacman"]
    assert _names(cab.colors.read_bytes()) == ["Contra (USA)", "pacman"]
    assert ll.RawIni.load(cab.controls).entries()["pacman"] == \
        ll.RawIni(CONTROLS.decode("utf-8", "surrogateescape")).entries()["pacman"]
    # The library holds exactly what was removed.
    lib = ll.Library()
    live = ll.RawIni(CONTROLS.decode("utf-8", "surrogateescape")).entries()
    assert lib.controls.entries() == {"dkong": live["dkong"], "robby": live["robby"]}
    assert sorted(lib.colors.entries()) == ["dkong", "robby"]
    assert lib.community_path.read_text(encoding="utf-8").startswith("[galaga]")
    # Backups of both files.
    assert len(list((cab.tmp / "backups" / "LEDBlinky").iterdir())) == 2


def test_prune_keeps_parents_of_wheel_games(cab):
    cab.controls.write_bytes(CONTROLS + CRLF + _sec("mspacman", "numPlayers=2") + _sec("sf2", "numPlayers=2"))
    out = _run("prune", "--apply")
    assert "2 kept only as the parent of a wheel game" in out
    assert _names(cab.controls.read_bytes()) == ["pacman", "mspacman", "sf2"]


def test_prune_then_all_roms_brings_every_entry_back_byte_for_byte(cab):
    # zzlost has an entry but no ROM file: --all-roms takes it from the library too.
    controls = CONTROLS + CRLF + _sec("zzlost", "numPlayers=1", "P1_START=1")
    cab.controls.write_bytes(controls)
    _run("prune", "--apply")
    assert cab.controls.read_bytes() != controls
    out = _run("generate", "--all-roms", "--apply")
    assert "5 ROM files in" in out and "plus 1 more in SpinDoctor's library" in out
    assert "From SpinDoctor's library: 3 controls, 2 colors" in out
    # dkong, robby and zzlost are back exactly where and as they were; galaga
    # and mspacman (ROM files with no entry before) are new.
    for path, original in ((cab.controls, controls), (cab.colors, COLORS)):
        restored = ll.RawIni(_text(path.read_bytes())).render(remove=["galaga", "mspacman"])
        assert restored.encode("utf-8", "surrogateescape") == original


def test_generate_puts_back_a_pruned_game_when_it_joins_a_wheel(cab):
    _run("prune", "--apply")
    _db(cab.hs, "MAME", [("pacman", ""), ("galaga", ""), ("mspacmnf", "mspacman"), ("robby", "")])
    _run("generate", "--apply")
    original = ll.RawIni(_text(CONTROLS)).entries()["robby"]
    assert original in _text(cab.controls.read_bytes())
    assert "dkong" not in ll.RawIni.load(cab.controls).entries()


def test_prune_refuses_when_there_are_no_wheel_databases(cab):
    import shutil
    shutil.rmtree(str(cab.hs / "Databases"))
    result = CliRunner().invoke(cli, ["ledblinky", "prune", "--apply"])
    assert result.exit_code == 1
    assert cab.controls.read_bytes() == CONTROLS


def test_prune_leaves_the_live_files_when_the_library_cannot_be_written(cab, monkeypatch):
    def broken(self, controls, colors):
        raise OSError("disk full")
    monkeypatch.setattr(ll.Library, "save", broken)
    with pytest.raises(OSError):
        ll.prune_entries(cab.cfg, dry_run=False)
    assert cab.controls.read_bytes() == CONTROLS and cab.colors.read_bytes() == COLORS


@pytest.mark.parametrize("damage", ["missing", "empty", "garbage", "wrong-root", "missing-folder"])
def test_prune_refuses_an_incomplete_wheel_database(cab, damage):
    path = cab.hs / "Databases" / "MAME" / "MAME.xml"
    if damage in ("missing", "missing-folder"):
        path.unlink()
        if damage == "missing-folder":
            path.parent.rmdir()
    else:
        path.write_bytes({"empty": b"", "garbage": b"not XML", "wrong-root": b"<unrelated/>"}[damage])
    with pytest.raises(ValueError, match="safely prune"):
        ll.prune_entries(cab.cfg, dry_run=False)
    assert cab.controls.read_bytes() == CONTROLS and cab.colors.read_bytes() == COLORS
    assert not ll.LIBRARY_DIR.exists()


def test_main_menu_is_not_a_game_database(cab):
    import shutil
    for folder in (cab.hs / "Databases").iterdir():
        if folder.name != "Main Menu":
            shutil.rmtree(folder)
    assert not ll.wheel_scope(cab.cfg).any_wheel
    with pytest.raises(ValueError):
        ll.prune_entries(cab.cfg, dry_run=False)
    assert cab.controls.read_bytes() == CONTROLS


def test_prune_refuses_missing_genre_database(cab):
    _db(cab.hs, "MAME", [("Missing Genre", "")], xml_name="Genre")
    with pytest.raises(ValueError, match="safely prune"):
        ll.prune_entries(cab.cfg, dry_run=False)
    assert cab.controls.read_bytes() == CONTROLS


@pytest.mark.parametrize("cache_state", ["missing", "stale"])
def test_prune_loads_parent_data_like_generate(cab, monkeypatch, cache_state):
    cache = ledblinky.listxml_cache_path(cab.cfg.mame_executable)
    if cache_state == "missing":
        cache.unlink()
    else:
        os.utime(str(cache), (0, 0))
    calls = []

    def run(mame, cache_path):
        calls.append(mame)
        return LISTXML

    monkeypatch.setattr(ledblinky, "run_mame_listxml", run)
    cab.controls.write_bytes(CONTROLS + CRLF + _sec("sf2", "numPlayers=2"))
    ll.prune_entries(cab.cfg, dry_run=False)
    assert calls == [cab.cfg.mame_executable]
    assert "sf2" in ll.RawIni.load(cab.controls).entries()


def test_prune_refuses_unavailable_mame_parent_data(cab, monkeypatch):
    monkeypatch.setattr(ledblinky, "load_listxml_for_system", lambda *args: {})
    with pytest.raises(ValueError, match="parent data is unavailable"):
        ll.prune_entries(cab.cfg, dry_run=False)
    assert cab.controls.read_bytes() == CONTROLS


def test_prune_refuses_to_remove_every_live_control(cab):
    before = _ini(_sec("unknown", "numPlayers=1"))
    cab.controls.write_bytes(before)
    preview = ll.prune_entries(cab.cfg)
    assert preview.warnings
    with pytest.raises(ValueError, match="every Controls.ini entry"):
        ll.prune_entries(cab.cfg, dry_run=False)
    assert cab.controls.read_bytes() == before and cab.colors.read_bytes() == COLORS


# ── audit ─────────────────────────────────────────────────────────────────────


def test_audit_reports_covered_available_and_no_data(cab):
    ll.Library().save(controls={"galaga": "[galaga]\nk=1\n\n"}, colors={"galaga": "[galaga]\nk=1\n\n"})
    report = cab.tmp / "audit.csv"
    out = _run("audit", "--report", str(report))
    assert "Covered (controls.ini + Colors.ini) 1" in out
    assert "Missing, in SpinDoctor's library 1" in out
    assert "Missing, would synthesise from -listxml 4" in out
    assert "No data: game has no input 1" in out
    assert "2 of 3 in controls.ini, 2 of 4 in Colors.ini" in out
    rows = report.read_text(encoding="utf-8").splitlines()
    assert rows[0].endswith(",status,in_library,wheels,parent_of")
    assert any(r.startswith("galaga,") and ",from-library,True,MAME," in r for r in rows)
    assert any(r.startswith("sf2,") and r.endswith(",would-synth,False,,sf2ce") for r in rows)


def test_audit_all_roms_checks_the_rom_folder(cab):
    out = _run("audit", "--all-roms")
    assert "5 ROM files in" in out
    assert "Covered (controls.ini + Colors.ini) 3" in out


# ── doctor ────────────────────────────────────────────────────────────────────


def test_doctor_counts_the_wheel_games(cab):
    result = health.check_led_coverage(cab.cfg)
    assert result.status == health.Status.WARN
    assert result.detail.startswith("1/7 covered")
    assert "5 could be generated" in result.detail
    assert result.fix == "spindoctor ledblinky generate --apply"


def test_doctor_uses_the_library_when_mame_data_is_not_cached(cab):
    ledblinky.listxml_cache_path(cab.cfg.mame_executable).unlink()
    assert health.check_led_coverage(cab.cfg).status == health.Status.INFO   # nothing to go on
    ll.Library().save(controls={"galaga": "[galaga]\nk=1\n\n"}, colors={})
    result = health.check_led_coverage(cab.cfg)
    assert result.status == health.Status.WARN
    assert "1 could be generated (1 from SpinDoctor's library)" in result.detail
    assert "library only" in result.detail


def test_doctor_warns_when_most_entries_are_for_games_in_no_wheel(cab, monkeypatch):
    monkeypatch.setattr(ll, "PRUNE_WARN_ENTRIES", 2)
    result = health.check_led_coverage(cab.cfg)
    child = result.children[0]
    assert child.status == health.Status.WARN
    assert child.detail.startswith("2 of 3 controls.ini entries")
    assert child.fix == "spindoctor ledblinky prune --apply"
    _run("prune", "--apply")
    assert health.check_led_coverage(cab.cfg).children == []


# ── profiles ──────────────────────────────────────────────────────────────────


@pytest.fixture
def builder_cab(cab):
    (cab.led / lp.INPUT_MAP_NAME).write_text("<inputMap/>", encoding="utf-8")
    (cab.led / lp.CONTROLS_XML_NAME).write_text('<?xml version="1.0"?>\n<dat>\n</dat>\n', encoding="utf-8")
    return cab


def test_profiles_borrow_a_donor_from_the_library(builder_cab):
    _db(builder_cab.hs, "MAME", [("pacman", ""), ("robbyb", "")])  # robby is its prefix donor
    assert lp.ProfileBuilder(builder_cab.cfg).controls_for("robby") is not None
    _run("prune", "--apply")                                # robby moves to the library
    b = lp.ProfileBuilder(builder_cab.cfg)
    assert b.controls_for("robby") is None
    b.fill_mame_family(["MAME"])
    assert b.result.controls_ini_added == [("robbyb", "robby")]
    assert b.controls_for("robbyb")["P1_BUTTON1"] == "1"
    assert b.colors_for("robbyb")["P1_BUTTON1"] == "Lime"


def test_profiles_use_a_wheel_games_own_entry_from_the_library(builder_cab):
    _run("prune", "--apply")
    _db(builder_cab.hs, "MAME", [("dkong", "")])
    b = lp.ProfileBuilder(builder_cab.cfg)
    b.fill_mame_family(["MAME"])
    assert b.result.controls_ini_added == [("dkong", "dkong")]
    assert b.colors_for("dkong")["P1_JOYSTICK"] == "Red"


def test_profiles_read_the_community_file_from_the_library(builder_cab):
    community = builder_cab.led / "controls.ini.20200101_000000.bak"
    community.write_text("[galaga]\nP1NumButtons=1\nP1_BUTTON1=Fire\n", encoding="utf-8")
    _run("prune", "--apply")
    community.unlink()
    assert lp.ProfileBuilder(builder_cab.cfg).community_for("galaga")["P1_BUTTON1"] == "Fire"


# ── GUI ───────────────────────────────────────────────────────────────────────


def _gui_stub(all_roms=False, apply=False):
    calls = []
    flag = types.SimpleNamespace
    return types.SimpleNamespace(
        _led_all_roms_var=flag(get=lambda: all_roms), _led_overwrite_var=flag(get=lambda: False),
        _global_apply_var=flag(get=lambda: apply), _global_verbose_var=flag(get=lambda: False),
        _run_cli=lambda binary, args: calls.append(args), calls=calls)


def test_gui_buttons_use_the_wheel_scope_unless_all_roms_is_ticked():
    stub = _gui_stub()
    gui._SpinDoctorGUI._run_led_generate(stub)
    gui._SpinDoctorGUI._run_led_audit(stub)
    gui._SpinDoctorGUI._run_led_setup(stub)
    assert stub.calls == [["ledblinky", "generate"], ["ledblinky", "audit"], ["ledblinky", "setup"]]
    stub = _gui_stub(all_roms=True, apply=True)
    gui._SpinDoctorGUI._run_led_generate(stub)
    gui._SpinDoctorGUI._run_led_prune(stub)
    assert stub.calls == [["ledblinky", "generate", "--all-roms", "--apply"], ["ledblinky", "prune", "--apply"]]


@pytest.mark.parametrize("operation", ("remove", "replace"))
def test_library_keeps_section_boundary_comment_banners(operation):
    text = "[a]\r\nx=1\r\n\r\n; Next category\r\n# keep this too\r\n\r\n[b]\r\ny=2\r\n"
    raw = ll.RawIni(text)
    assert raw.render() == text
    result = raw.render(**({"remove": ["a"]} if operation == "remove"
                           else {"replace": {"a": "[a]\r\nx=3\r\n"}}))
    assert "\r\n; Next category\r\n# keep this too\r\n\r\n[b]\r\ny=2\r\n" in result
    assert result.count("Next category") == 1
    assert "Next category" not in raw.entries()["a"]


@pytest.mark.parametrize("encoding", ("utf-16", "utf-16-be"))
def test_library_roundtrips_utf16_live_files(tmp_path, encoding):
    path = tmp_path / "Controls.ini"
    text = "; café\r\n[a]\r\nx=1\r\n"
    path.write_bytes(_encode_legacy_text(text, encoding))
    raw = ll.RawIni.load(path)
    ll.write_raw(path, raw.render())
    assert path.read_bytes() == _encode_legacy_text(text, encoding)


def test_community_discovery_uses_numeric_oldest_and_checks_content(tmp_path):
    for counter, content in ((10, "P1NumButtons=10"), (2, "P1NumButtons=2"), (1, "unrelated")):
        (tmp_path / f"controls.ini.20260101_120000_{counter}.bak").write_bytes(content.encode())
    assert ll.find_community_controls(tmp_path).name.endswith("_2.bak")
