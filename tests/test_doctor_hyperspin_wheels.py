"""Tests for the `doctor` checks of what HyperSpin itself shows.

* **HyperSpin ROMs only:** with ``[filters] roms_only=true`` in
  ``<hyperspin_dir>\\Settings\\<System>.ini``, HyperSpin lists only the games
  it finds in ``[exe info] rompath``.  After a ROM-drive move that folder can
  be gone while RocketLauncher's ``Rom_Path`` is fine, and the wheel is empty.
* **Spaces in game names:** a ``<game name="Some Hack V2 ">`` is looked up by
  HyperSpin as written, while its wheel art is usually saved trimmed.

Each test builds a small cabinet in a temp dir.
"""
from __future__ import annotations

import os

import pytest

from spindoctor import health
from spindoctor.config import Config

OK = health.Status.OK
WARN = health.Status.WARN
INFO = health.Status.INFO


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _cabinet(tmp_path, wheels, hidden=(), rom_paths=None, rocketlauncher=True):
    """HyperSpin (+ RocketLauncher) dirs.  *wheels* maps wheel name -> DB game
    names, written exactly as given (spaces included); *rom_paths* maps wheel
    name -> its RocketLauncher Rom_Path."""
    hs, rl = tmp_path / "HyperSpin", tmp_path / "RocketLauncher"
    menu = "".join(f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>'
                   for w in wheels)
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, games in wheels.items():
        xml = "".join(f'<game name="{g}"><description>{g}</description></game>' for g in games)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
    for wheel, path in (rom_paths or {}).items():
        _write(rl / "Settings" / wheel / "Emulators.ini",
               f"[ROMS]\nDefault_Emulator=Emu\nRom_Path={path}\n")
    _write(rl / "Settings" / "Global Emulators.ini",
           "[Emu]\nEmu_Path=..\\Emulators\\Emu\\emu.exe\nRom_Extension=zip|nes\n")
    return Config(roms_dir=str(tmp_path / "Games"), hyperspin_dir=str(hs),
                  rocketlauncher_dir=str(rl) if rocketlauncher else ""), hs


def _hs_ini(hs, system, rompath, roms_only="true", ext="zip", subfolders="", extra=""):
    """A HyperSpin Settings\\<System>.ini as HyperHQ writes it."""
    return _write(hs / "Settings" / f"{system}.ini", (
        f"[exe info]\npath=\nrompath={rompath}\nuserompath=\nexe=emu.exe\nromextension={ext}\n"
        f"parameters=\nsearchsubfolders={subfolders}\npcgame=false\nwinstate=HIDDEN\nhyperlaunch=true\n\n"
        f"[filters]\nparents_only=false\nthemes_only=false\nwheels_only=false\nroms_only={roms_only}\n\n"
        f"[themes]\nuse_parent_vids=true\n{extra}"))


def _files(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        _write(folder / name)
    return folder


def _node(chk, system):
    return next(c for c in chk.children if c.name.startswith(system))


AAE = {"AAE": ["astdelux", "alienst", "armora"]}


# ── HyperSpin ROMs only ─────────────────────────────────────────────────────

def test_roms_only_with_a_missing_rompath_warns_and_names_the_rl_folder(tmp_path):
    games = _files(tmp_path / "Games" / "AAE", "astdelux.zip", "alienst.zip", "armora.zip")
    cfg, hs = _cabinet(tmp_path, AAE, rom_paths={"AAE": games})
    ini = _hs_ini(hs, "AAE", tmp_path / "J" / "Games" / "AAE")
    chk = health.check_hyperspin_roms_only(cfg)
    node = _node(chk, "AAE")
    assert chk.status == WARN and node.status == WARN
    assert "doesn't exist" in node.detail and "lists no games" in node.detail
    assert str(ini) in node.fix
    assert f"set rompath={games} under [exe info] (it holds 3 of the 3 games)" in node.fix
    assert "roms_only=false under [filters]" in node.fix
    assert chk.detail == "1 of 1 wheel with roms_only=true shows no games in HyperSpin"


def test_roms_only_with_an_empty_rompath_warns(tmp_path):
    cfg, hs = _cabinet(tmp_path, AAE)
    _hs_ini(hs, "AAE", "")
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == WARN and "rompath is empty" in node.detail
    assert "point rompath under [exe info] at the folder" in node.fix


def test_roms_only_folder_with_none_of_the_games_warns(tmp_path):
    folder = _files(tmp_path / "Old" / "AAE", "readme.txt", "galaga.zip")
    cfg, hs = _cabinet(tmp_path, AAE)
    _hs_ini(hs, "AAE", folder)
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == WARN
    assert "holds none of its 3 games with romextension=zip" in node.detail


def test_roms_only_folder_with_the_wrong_extension_says_which(tmp_path):
    folder = _files(tmp_path / "Games" / "AAE", "astdelux.7z", "alienst.7z")
    cfg, hs = _cabinet(tmp_path, AAE)
    _hs_ini(hs, "AAE", folder)
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == WARN
    assert "add 7z to romextension= under [exe info]" in node.fix


def test_roms_only_folder_with_games_is_ok(tmp_path):
    folder = _files(tmp_path / "Games" / "AAE", "astdelux.zip", "alienst.zip", "galaga.zip")
    cfg, hs = _cabinet(tmp_path, AAE)
    _hs_ini(hs, "AAE", str(folder) + os.sep, ext="zip, 7z")
    chk = health.check_hyperspin_roms_only(cfg)
    node = _node(chk, "AAE")
    assert node.status == OK and chk.status == OK
    assert "2 of 3 games found" in node.detail and "HyperSpin hides the other 1" in node.detail


@pytest.mark.parametrize("roms_only", ["false", ""])
def test_roms_only_off_is_silent(tmp_path, roms_only):
    cfg, hs = _cabinet(tmp_path, {"AAE": ["astdelux"], "MAME": ["pacman"]})
    _hs_ini(hs, "AAE", tmp_path / "J" / "Games" / "AAE", roms_only=roms_only)
    # MAME has no HyperSpin Settings INI at all: the wheel wiring check reports that.
    chk = health.check_hyperspin_roms_only(cfg)
    assert chk.status == OK and chk.children == []
    assert "no Main Menu wheel uses roms_only=true" in chk.detail


def test_roms_only_on_a_hidden_wheel_is_info(tmp_path):
    cfg, hs = _cabinet(tmp_path, AAE, hidden={"AAE"})
    _hs_ini(hs, "AAE", tmp_path / "J" / "Games" / "AAE")
    chk = health.check_hyperspin_roms_only(cfg)
    node = _node(chk, "AAE")
    assert node.name == "AAE (hidden on the Main Menu)"
    assert node.status == INFO and chk.status != WARN


def test_roms_only_on_a_wheel_not_on_the_main_menu_is_skipped(tmp_path):
    cfg, hs = _cabinet(tmp_path, AAE)
    _hs_ini(hs, "AAE", _files(tmp_path / "Games" / "AAE", "astdelux.zip"))
    _hs_ini(hs, "DOS Box", tmp_path / "missing")
    chk = health.check_hyperspin_roms_only(cfg)
    assert [c.name for c in chk.children] == ["AAE"]
    assert chk.status == OK


def test_relative_rompath_resolves_from_the_hyperspin_folder(tmp_path):
    cfg, hs = _cabinet(tmp_path, AAE)
    _files(hs / "Roms" / "AAE", "astdelux.zip")
    _files(tmp_path / "RocketLauncher" / "Roms" / "AAE", "alienst.zip", "armora.zip")
    _hs_ini(hs, "AAE", "Roms\\AAE\\")
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == OK and "1 of 3 games found" in node.detail

    _hs_ini(hs, "AAE", "..\\Elsewhere\\AAE")
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == WARN and "..\\Elsewhere\\AAE doesn't exist" in node.detail


def test_ini_with_bom_and_any_case_keys(tmp_path):
    cfg, hs = _cabinet(tmp_path, AAE)
    folder = tmp_path / "J" / "Games" / "AAE"
    (hs / "Settings").mkdir(parents=True)
    (hs / "Settings" / "AAE.ini").write_bytes(
        b"\xef\xbb\xbf[EXE INFO]\r\nRomPath=" + str(folder).encode("utf-8")
        + b"\r\nRomExtension=ZIP\r\n\r\n[Filters]\r\nROMS_ONLY=True\r\n")
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == WARN and "doesn't exist" in node.detail

    _files(folder, "ASTDELUX.ZIP")
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == OK and "1 of 3 games found" in node.detail


@pytest.mark.parametrize("subfolders, status", [("true", OK), ("false", WARN)])
def test_searchsubfolders_counts_games_below_rompath(tmp_path, subfolders, status):
    folder = tmp_path / "Games" / "AAE"
    _files(folder / "roms", "astdelux.zip")
    cfg, hs = _cabinet(tmp_path, AAE)
    _hs_ini(hs, "AAE", folder, subfolders=subfolders)
    assert _node(health.check_hyperspin_roms_only(cfg), "AAE").status == status


def test_suggests_the_same_folder_under_roms_dir_without_rocketlauncher(tmp_path):
    games = _files(tmp_path / "Games" / "AAE", "armora.zip")
    cfg, hs = _cabinet(tmp_path, AAE, rocketlauncher=False)
    _hs_ini(hs, "AAE", str(tmp_path / "J" / "Games" / "AAE") + os.sep)
    node = _node(health.check_hyperspin_roms_only(cfg), "AAE")
    assert node.status == WARN
    assert f"set rompath={games}" in node.fix and "(it holds 1 of the 3 games)" in node.fix


def test_roms_only_finds_a_game_named_with_a_space(tmp_path):
    folder = _files(tmp_path / "Games" / "NES", "Some Hack V2 .zip")
    cfg, hs = _cabinet(tmp_path, {"NES": ["Some Hack V2 "]})
    _hs_ini(hs, "NES", folder)
    assert _node(health.check_hyperspin_roms_only(cfg), "NES").status == OK


# ── Spaces in game names ────────────────────────────────────────────────────

NES = "Nintendo Entertainment System"


def test_spaced_names_warn(tmp_path):
    cfg, hs = _cabinet(tmp_path, {NES: ["Some Hack V2 ", "Mario", " Lead Space"]})
    chk = health.check_game_name_spaces(cfg)
    node = _node(chk, NES)
    assert chk.status == WARN and node.status == WARN
    assert node.detail.startswith('2 game names start or end with a space: " Lead Space", "Some Hack V2 "')
    assert "under the name as written" in node.detail
    assert "only under the trimmed name" not in node.detail
    assert str(hs / "Databases" / NES / f"{NES}.xml") in node.fix
    assert 'remove the spaces around each name="..." and its <description>' in node.fix
    assert chk.detail == "2 game names on 1 wheel start or end with a space"


def test_media_only_under_the_trimmed_name_is_noted(tmp_path):
    cfg, hs = _cabinet(tmp_path, {NES: ["Some Hack V2 ", "Other Hack "]})
    media = hs / "Media" / NES
    _write(media / "Images" / "Wheel" / "Some Hack V2.png")
    _write(media / "Video" / "Some Hack V2.mp4")
    _write(media / "Images" / "Wheel" / "Other Hack .png")  # under the name as written: found
    node = _node(health.check_game_name_spaces(cfg), NES)
    assert "but 1 of them has wheel art, video only under the trimmed name" in node.detail
    assert ", and any media saved under the name as written (find-orphan-media" in node.fix


def test_redirected_video_folder_is_checked(tmp_path):
    cfg, hs = _cabinet(tmp_path, {NES: ["Some Hack V2 "]})
    shared = tmp_path / "Shared Video"
    _write(shared / "Some Hack V2.flv")
    _hs_ini(hs, NES, "", roms_only="false", extra=f"\n[video defaults]\npath={shared}{os.sep}\n")
    node = _node(health.check_game_name_spaces(cfg), NES)
    assert "has video only under the trimmed name" in node.detail


def test_spaced_name_fix_shows_the_rom_rename(tmp_path):
    roms = _files(tmp_path / "Games" / NES, "Some Hack V2 .nes")
    cfg, hs = _cabinet(tmp_path, {NES: ["Some Hack V2 "]}, rom_paths={NES: roms})
    node = _node(health.check_game_name_spaces(cfg), NES)
    assert '(e.g. "Some Hack V2 .nes" to "Some Hack V2.nes")' in node.fix


def test_many_spaced_names_are_capped(tmp_path):
    cfg, hs = _cabinet(tmp_path, {NES: [f"Hack {i} " for i in range(7)]})
    node = _node(health.check_game_name_spaces(cfg), NES)
    assert node.detail.startswith("7 game names start or end with a space: ")
    assert '"Hack 4 ", and 2 more;' in node.detail


def test_spaced_names_on_a_hidden_wheel_are_info(tmp_path):
    cfg, hs = _cabinet(tmp_path, {NES: ["Some Hack V2 "], "MAME": ["pacman"]}, hidden={NES})
    chk = health.check_game_name_spaces(cfg)
    node = _node(chk, NES)
    assert node.name == f"{NES} (hidden on the Main Menu)"
    assert node.status == INFO and chk.status != WARN


def test_no_spaced_names_is_ok(tmp_path):
    cfg, hs = _cabinet(tmp_path, {NES: ["Mario", "Zelda"], "MAME": ["pacman"]})
    _write(hs / "Databases" / "Elsewhere" / "Elsewhere.xml", '<menu><game name="Not Shown "/></menu>')
    chk = health.check_game_name_spaces(cfg)
    assert chk.status == OK and chk.children == []
    assert chk.detail == "no game name starts or ends with a space on the Main Menu's 2 wheels"


# ── both ────────────────────────────────────────────────────────────────────

def test_without_hyperspin_dir_both_checks_skip(tmp_path):
    cfg = Config(roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "missing"))
    for chk in (health.check_hyperspin_roms_only(cfg), health.check_game_name_spaces(cfg)):
        assert chk.status == INFO and "skipping" in chk.detail


def test_doctor_runs_both_checks_after_rom_paths(tmp_path):
    cfg, _hs = _cabinet(tmp_path, AAE)
    names = [c.name for c in health.run_health_checks(cfg, fix=False).checks]
    i = names.index("ROM paths")
    assert names[i + 1:i + 4] == ["HyperSpin ROMs only", "Video redirects", "Spaces in game names"]
