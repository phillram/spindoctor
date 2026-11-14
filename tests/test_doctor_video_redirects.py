"""Tests for the `doctor` **Video redirects** check.

``path=`` under ``[video defaults]`` in ``<hyperspin_dir>\\Settings\\<System>.ini``
sends HyperSpin to another folder for a wheel's videos, and HyperSpin then
reads only that folder: a folder that's gone plays no videos at all, and
videos in the wheel's own ``Media\\<System>\\Video`` never play.

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

DRIVING = "Driving Games"


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _cabinet(tmp_path, wheels, hidden=()):
    """A HyperSpin dir.  *wheels* maps wheel name -> DB game names, written
    exactly as given (spaces included)."""
    hs = tmp_path / "HyperSpin"
    menu = "".join(f'<game name="{w}" enabled="False"/>' if w in hidden else f'<game name="{w}"/>'
                   for w in wheels)
    _write(hs / "Databases" / "Main Menu" / "Main Menu.xml", f"<menu>{menu}</menu>")
    for wheel, games in wheels.items():
        xml = "".join(f'<game name="{g}"><description>{g}</description></game>' for g in games)
        _write(hs / "Databases" / wheel / f"{wheel}.xml", f"<menu>{xml}</menu>")
    return Config(hyperspin_dir=str(hs)), hs


def _video_path(hs, system, path):
    """``Settings\\<System>.ini`` as HyperHQ writes it, with ``[video defaults] path=``."""
    return _write(hs / "Settings" / f"{system}.ini", (
        "[exe info]\npath=\nrompath=\nuserompath=\nexe=\nromextension=zip\n\n"
        "[filters]\nparents_only=false\nthemes_only=false\nwheels_only=false\nroms_only=false\n\n"
        "[themes]\nuse_parent_vids=true\nuse_parent_themes=false\n\n"
        f"[video defaults]\npath={path}\n\n[wheel]\nalpha=.15\n"))


def _videos(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        _write(folder / name)
    return folder


def _own(hs, system):
    return hs / "Media" / system / "Video"


def _node(chk, system):
    return next(c for c in chk.children if c.name.startswith(system))


GAMES = {DRIVING: ["outrun", "chasehq", "Daytona USA"]}


# ── a folder that doesn't exist ─────────────────────────────────────────────

def test_missing_folder_warns_that_the_wheel_plays_no_video(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    gone = tmp_path / "R" / "Elsewhere" / "Video"
    ini = _video_path(hs, DRIVING, f"{gone}{os.sep}")
    chk = health.check_video_redirects(cfg)
    node = _node(chk, DRIVING)
    assert chk.status == WARN and node.status == WARN
    assert node.detail == (f"path={gone}{os.sep} doesn't exist, so HyperSpin plays no video "
                           "on this wheel, and shows no error")
    assert node.fix == (f"In {ini}, leave path= blank under [video defaults], "
                        f"so HyperSpin reads {_own(hs, DRIVING)}")
    assert chk.detail == "1 of 1 wheel with [video defaults] path= loses videos in HyperSpin"


def test_missing_folder_notes_the_videos_in_the_wheels_own_folder(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    _videos(_own(hs, DRIVING), "outrun.mp4", "chasehq.flv", "galaga.mp4")
    _video_path(hs, DRIVING, tmp_path / "R" / "Video")
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.status == WARN
    assert node.detail.endswith(f"; its own {_own(hs, DRIVING)} holds videos for 2 of its 3 games")
    assert node.fix.startswith("In ") and "leave path= blank" in node.fix


def test_missing_folder_on_an_old_drive_suggests_the_same_folder_here(tmp_path):
    # R:\Arcade\Media\MAME\Video after a drive move: the same folder exists under
    # the HyperSpin folder, so its videos can be copied in (or path= repointed).
    cfg, hs = _cabinet(tmp_path, GAMES)
    shared = _videos(hs / "Media" / "MAME" / "Video", "outrun.mp4", "chasehq.mp4", "pacman.mp4")
    ini = _video_path(hs, DRIVING, tmp_path / "R" / "Arcade" / "Media" / "MAME" / "Video")
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.status == WARN and "doesn't exist" in node.detail
    assert node.fix == (f"Copy the 2 videos of this wheel's games in {shared} into "
                        f"{_own(hs, DRIVING)} (keep the ones already there), then leave path= "
                        f"blank under [video defaults] in {ini}; or set path={shared} there")


def test_missing_folder_that_was_the_wheels_own_suggests_a_blank_path(tmp_path):
    wii = "Nintendo Wii"
    cfg, hs = _cabinet(tmp_path, {wii: ["Wii Sports", "Mario Kart Wii"]})
    _videos(_own(hs, wii), "Wii Sports.mp4", "Mario Kart Wii.mp4")
    ini = _video_path(hs, wii, f"{tmp_path / 'R' / 'Arcade' / 'Media' / wii / 'Video'}{os.sep}")
    node = _node(health.check_video_redirects(cfg), wii)
    assert node.status == WARN
    assert node.detail.endswith(f"; its own {_own(hs, wii)} holds videos for 2 of its 2 games")
    assert node.fix == (f"In {ini}, leave path= blank under [video defaults], "
                        f"so HyperSpin reads {_own(hs, wii)}")


# ── another folder that exists ──────────────────────────────────────────────

def test_redirect_hiding_the_wheels_own_videos_warns_with_counts(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    shared = _videos(tmp_path / "Media" / "MAME" / "Video", "outrun.mp4", "pacman.mp4")
    _videos(_own(hs, DRIVING), "outrun.mp4", "chasehq.mp4", "Daytona USA.flv")
    ini = _video_path(hs, DRIVING, f"{shared}{os.sep}")
    chk = health.check_video_redirects(cfg)
    node = _node(chk, DRIVING)
    assert chk.status == WARN and node.status == WARN
    assert node.detail == (f"path={shared}{os.sep} sends HyperSpin elsewhere, so 3 videos in "
                           f"{_own(hs, DRIVING)} named after its games never play (HyperSpin "
                           f"has no per-game fallback); 2 of those games have no video in "
                           f"{shared}{os.sep}, so they play none")
    assert node.fix == (f"Copy the 1 video of this wheel's games in {shared} into "
                        f"{_own(hs, DRIVING)} (keep the ones already there), then leave path= "
                        f"blank under [video defaults] in {ini}")


def test_redirect_hiding_videos_that_are_also_in_the_other_folder_is_info(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    shared = _videos(tmp_path / "Shared", "outrun.mp4", "chasehq.mp4")
    _videos(_own(hs, DRIVING), "outrun.mp4", "chasehq.mp4")
    _video_path(hs, DRIVING, shared)
    chk = health.check_video_redirects(cfg)
    node = _node(chk, DRIVING)
    assert node.status == INFO and chk.status != WARN
    assert node.detail.endswith(f"so 2 videos in {_own(hs, DRIVING)} named after its games never "
                                f"play (HyperSpin has no per-game fallback); those games play "
                                f"their video from {shared} instead")
    assert node.fix.startswith(f"Copy the 2 videos of this wheel's games in {shared} into ")

    (_own(hs, DRIVING) / "chasehq.mp4").unlink()
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.detail.endswith(f"; that game plays its video from {shared} instead")


def test_one_hidden_video_reads_in_the_singular(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    _videos(_own(hs, DRIVING), "chasehq.mp4")
    _video_path(hs, DRIVING, _videos(tmp_path / "Shared", "outrun.mp4"))
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert "so 1 video in" in node.detail and "named after its games never plays" in node.detail
    assert "; 1 of those games has no video in" in node.detail and "so it plays none" in node.detail


def test_redirect_with_nothing_in_the_wheels_own_folder_is_ok(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    shared = _videos(tmp_path / "Shared", "outrun.mp4", "chasehq.flv", "pacman.mp4")
    _videos(_own(hs, DRIVING), "galaga.mp4", "outrun.png")  # no game's video; a still
    _video_path(hs, DRIVING, shared)
    chk = health.check_video_redirects(cfg)
    node = _node(chk, DRIVING)
    assert chk.status == OK and node.status == OK
    assert node.detail == f"videos from {shared}: 2 of its 3 games have one there"
    assert node.fix is None
    assert chk.detail == "1 wheel with [video defaults] path=; see each for where HyperSpin reads videos"


def test_path_naming_the_wheels_own_folder_is_ok(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    own = _videos(_own(hs, DRIVING), "outrun.mp4")
    _video_path(hs, DRIVING, f"{own}{os.sep}")
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.status == OK
    assert node.detail == "path= names the wheel's own video folder, as a blank path= would"


def test_videos_are_matched_by_the_name_as_written_in_any_case(tmp_path):
    cfg, hs = _cabinet(tmp_path, {DRIVING: ["outrun", "Some Hack V2 "]})
    _videos(_own(hs, DRIVING), "OUTRUN.MP4", "Some Hack V2 .flv", "chasehq.mp4")
    _videos(_own(hs, DRIVING) / "Trailers", "chasehq.mp4")  # HyperSpin doesn't look in subfolders
    _video_path(hs, DRIVING, _videos(tmp_path / "Shared"))
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.status == WARN and "so 2 videos in" in node.detail


# ── relative paths ──────────────────────────────────────────────────────────

def test_relative_path_on_the_main_menu_is_info(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    _videos(_own(hs, "Main Menu"), f"{DRIVING}.mp4")
    ini = _video_path(hs, "Main Menu", ".\\Video\\")
    chk = health.check_video_redirects(cfg)
    node = _node(chk, "Main Menu")
    assert node.name == "Main Menu" and node.status == INFO and chk.status == INFO
    assert node.detail == ("path=.\\Video\\ is relative, and which folder HyperSpin reads it "
                           "from isn't clear (its own folder, Media or Media\\Main Menu); its "
                           f"own {_own(hs, 'Main Menu')} holds videos for 1 of its 1 wheel")
    assert node.fix == (f"In {ini}, leave path= blank under [video defaults], "
                        f"so HyperSpin reads {_own(hs, 'Main Menu')}")


def test_relative_path_to_a_folder_with_the_videos_suggests_copying_them_in(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    shared = _videos(hs / "Media" / "MAME" / "Video", "outrun.mp4", "chasehq.mp4")
    _video_path(hs, DRIVING, ".\\MAME\\Video\\")
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.status == INFO
    assert node.fix.startswith(f"Copy the 2 videos of this wheel's games in {shared} into ")


# ── which wheels ────────────────────────────────────────────────────────────

def test_hidden_wheel_is_info(tmp_path):
    cfg, hs = _cabinet(tmp_path, {**GAMES, "MAME": ["pacman"]}, hidden={DRIVING})
    _video_path(hs, DRIVING, tmp_path / "gone")
    chk = health.check_video_redirects(cfg)
    node = _node(chk, DRIVING)
    assert node.name == f"{DRIVING} (hidden on the Main Menu)"
    assert node.status == INFO and chk.status != WARN


def test_wheels_without_a_path_or_off_the_main_menu_are_not_listed(tmp_path):
    cfg, hs = _cabinet(tmp_path, {**GAMES, "MAME": ["pacman"]})
    _video_path(hs, DRIVING, "")
    _video_path(hs, "MAME Classics", tmp_path / "gone")  # not on the Main Menu
    # MAME has no Settings INI at all: the wheel wiring check reports that.
    chk = health.check_video_redirects(cfg)
    assert chk.status == OK and chk.children == []
    assert chk.detail == ("no Main Menu wheel sets [video defaults] path=: each plays "
                          "its videos from Media\\<wheel>\\Video")


def test_ini_with_bom_quotes_and_any_case(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    (hs / "Settings").mkdir(parents=True)
    (hs / "Settings" / f"{DRIVING}.ini").write_bytes(
        b"\xef\xbb\xbf[Video Defaults]\r\nPATH=\"" + str(tmp_path / "gone").encode("utf-8")
        + b"\"\r\n")
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.status == WARN and node.detail.startswith(f"path={tmp_path / 'gone'} doesn't exist")


def test_a_shared_folder_is_listed_once(tmp_path, monkeypatch):
    cfg, hs = _cabinet(tmp_path, {**GAMES, "4-Player Games": ["tmnt"]})
    shared = _videos(tmp_path / "Shared", "outrun.mp4", "tmnt.mp4")
    _video_path(hs, DRIVING, shared)
    _video_path(hs, "4-Player Games", f"{shared}{os.sep}")
    listed = []
    real = health._hs_video_names
    monkeypatch.setattr(health, "_hs_video_names", lambda folder: listed.append(folder) or real(folder))
    chk = health.check_video_redirects(cfg)
    assert [c.status for c in chk.children] == [OK, OK]
    assert sum(1 for f in listed if os.path.normcase(str(f)) == os.path.normcase(str(shared))) == 1


@pytest.mark.skipif(os.name == "nt", reason="a drive path is checkable on Windows")
def test_windows_drive_path_off_windows_is_info(tmp_path):
    cfg, hs = _cabinet(tmp_path, GAMES)
    _video_path(hs, DRIVING, "R:\\Arcade\\Media\\MAME\\Video\\")
    node = _node(health.check_video_redirects(cfg), DRIVING)
    assert node.status == INFO and "can't be checked on this OS" in node.detail


def test_without_hyperspin_dir_skips(tmp_path):
    cfg = Config(hyperspin_dir=str(tmp_path / "missing"))
    chk = health.check_video_redirects(cfg)
    assert chk.status == INFO and "skipping" in chk.detail


def test_spaces_check_still_reads_the_redirect(tmp_path):
    cfg, hs = _cabinet(tmp_path, {DRIVING: ["Some Hack V2 "]})
    shared = _videos(tmp_path / "Shared", "Some Hack V2.mp4")
    _video_path(hs, DRIVING, f'"{shared}{os.sep}"')
    node = _node(health.check_game_name_spaces(cfg), DRIVING)
    assert "has video only under the trimmed name" in node.detail


def test_doctor_runs_it_after_roms_only(tmp_path):
    cfg, _hs = _cabinet(tmp_path, GAMES)
    names = [c.name for c in health.run_health_checks(cfg, fix=False).checks]
    i = names.index("HyperSpin ROMs only")
    assert names[i + 1:i + 3] == ["Video redirects", "Spaces in game names"]
