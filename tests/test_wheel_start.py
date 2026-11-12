"""`wheel-start`: where HyperSpin wheels start (first, last or random game).

HyperSpin reads ``random_game`` and ``use_last_game`` from the ``[navigation]``
section of ``Settings\\<System>.ini``.  The command shows them per wheel and
sets them, changing only those two values (every other byte of the file
stays), with a backup first.  Every cabinet is built under tmp_path.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import wheel_start as ws
from spindoctor.backup import find_sidecars
from spindoctor.cli import cli
from spindoctor.config import Config

NES = "Nintendo Entertainment System"

# The shape HyperHQ writes, CRLF, with a blank line inside [navigation].
NES_INI = (
    b"[exe info]\r\n"
    b"path=\r\n"
    b"hyperlaunch=true\r\n"
    b"\r\n"
    b"[navigation]\r\n"
    b"game_jump=50\r\n"
    b"use_indexes=false\r\n"
    b"use_last_game=false\r\n"
    b"last_game=Some Game (USA)\r\n"
    b"random_game=true\r\n"
    b"\r\n"
    b"start_on_favorites=false\r\n"
    b"\r\n"
    b"[special art a]\r\n"
    b"default=true\r\n"
)

GENESIS_INI = (
    b"[navigation]\r\n"
    b"use_last_game=true\r\n"
    b"last_game=Other Game\r\n"
    b"random_game=false\r\n"
)

MAIN_MENU = (
    '<?xml version="1.0"?>\n<menu>\n'
    f'  <game name="{NES}"/>\n'
    '  <game name="Sega Genesis"/>\n'
    '  <game name="Search" exe="true"/>\n'
    '  <game name="No Settings Wheel"/>\n'
    '</menu>\n'
)


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    monkeypatch.setattr(ws, "hyperspin_running", lambda: False)
    hs = tmp_path / "hyperspin"
    settings = hs / "Settings"
    menu = hs / "Databases" / "Main Menu"
    for d in (settings, menu, tmp_path / "roms"):
        d.mkdir(parents=True)
    (menu / "Main Menu.xml").write_text(MAIN_MENU, encoding="utf-8")
    (settings / f"{NES}.ini").write_bytes(NES_INI)
    (settings / "Sega Genesis.ini").write_bytes(GENESIS_INI)
    (settings / "Search.ini").write_bytes(b"[navigation]\r\nrandom_game=true\r\n")
    (settings / "Settings.ini").write_bytes(b"[Main]\r\nUse_Last_Game=false\r\n")
    backups = tmp_path / "backups"
    config_mod.save_config(Config(roms_dir=str(tmp_path / "roms"), hyperspin_dir=str(hs),
                                  backup_dir=str(backups)))
    yield {"hs": hs, "settings": settings, "backups": backups,
           "nes": settings / f"{NES}.ini", "genesis": settings / "Sega Genesis.ini"}
    config_mod.reset_override_cache()


def _run(*args):
    return CliRunner().invoke(cli, list(args), catch_exceptions=False)


# ── reading ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body, mode", [
    ("random_game=true\nuse_last_game=false\n", "random"),
    ("random_game=false\nuse_last_game=true\n", "last"),
    ("random_game=false\nuse_last_game=false\n", "first"),
    ("game_jump=50\n", "first"),                         # missing keys are off
    ("random_game=true\nuse_last_game=true\n", "both"),
    ("Random_Game = TRUE\n", "random"),                  # any case, spaces round =
    ("random_game=yes\n", "first"),                      # only "true" is on
])
def test_read_text_gives_the_mode(body, mode):
    assert ws.read_text("[navigation]\n" + body).mode == mode


def test_read_text_only_reads_the_navigation_section():
    text = ("[wheel]\nrandom_game=true\n[NAVIGATION]\n; random_game=true\n"
            "use_last_game=true\n[filters]\nrandom_game=true\n")
    assert ws.read_text(text) == ws.WheelStart(False, True)


def test_read_text_uses_the_first_copy_of_a_key():
    text = "[navigation]\nrandom_game=true\n[navigation]\nrandom_game=false\n"
    assert ws.read_text(text).random_game is True


# ── writing the text ──────────────────────────────────────────────────────────

def test_set_text_changes_only_the_two_values():
    text = NES_INI.decode("ascii")
    out = ws.set_text(text, "first")
    assert out == text.replace("random_game=true", "random_game=false")
    out = ws.set_text(text, "last")
    assert out == (text.replace("random_game=true", "random_game=false")
                   .replace("use_last_game=false", "use_last_game=true"))


def test_set_text_keeps_spelling_spacing_and_line_ends():
    text = "[Navigation]\r\nRandom_Game = TRUE  \r\nUSE_LAST_GAME= false\r\n"
    assert ws.set_text(text, "first") == (
        "[Navigation]\r\nRandom_Game = false  \r\nUSE_LAST_GAME= false\r\n")


def test_set_text_leaves_a_file_that_already_asks_for_the_mode():
    text = NES_INI.decode("ascii")
    assert ws.set_text(text, "random") == text


def test_set_text_sets_every_copy():
    text = "[navigation]\nrandom_game=true\n[wheel]\nx=1\n[navigation]\nrandom_game=true\n"
    out = ws.set_text(text, "first")
    assert out.count("random_game=false") == 2 and "random_game=true" not in out
    assert out.count("use_last_game=false") == 1           # added once, to the first section


def test_set_text_adds_missing_keys_after_the_sections_last_line():
    text = "[navigation]\r\ngame_jump=50\r\n\r\n[filters]\r\nparents_only=false\r\n"
    assert ws.set_text(text, "random") == (
        "[navigation]\r\ngame_jump=50\r\nrandom_game=true\r\nuse_last_game=false\r\n"
        "\r\n[filters]\r\nparents_only=false\r\n")


def test_set_text_adds_the_section_at_the_end():
    text = "[exe info]\nhyperlaunch=true\n\n[filters]\nparents_only=false"   # no last line end
    assert ws.set_text(text, "last") == (
        "[exe info]\nhyperlaunch=true\n\n[filters]\nparents_only=false\n"
        "\n[navigation]\nrandom_game=false\nuse_last_game=true\n")
    assert ws.set_text("", "random") == "[navigation]\r\nrandom_game=true\r\nuse_last_game=false\r\n"


def test_set_text_adds_a_key_to_a_last_section_with_no_line_end():
    assert ws.set_text("[navigation]\nrandom_game=true", "first") == (
        "[navigation]\nrandom_game=false\nuse_last_game=false\n")


@pytest.mark.parametrize("mode", ws.MODES)
def test_set_text_round_trips(mode):
    for text in (NES_INI.decode("ascii"), GENESIS_INI.decode("ascii"), "", "[wheel]\nx=1\n"):
        assert ws.read_text(ws.set_text(text, mode)).mode == mode


# ── the file ──────────────────────────────────────────────────────────────────

def test_set_wheel_start_keeps_every_other_byte_and_backs_up(cabinet):
    cfg = config_mod.load_config()
    change = ws.set_wheel_start(cabinet["nes"], "first", cfg)
    assert (change.old, change.new) == ("random", "first")
    assert cabinet["nes"].read_bytes() == NES_INI.replace(b"random_game=true", b"random_game=false")
    assert change.backup.parent == cabinet["backups"] / "HyperSpin"
    assert change.backup.name.startswith(f"{NES}.ini.") and change.backup.read_bytes() == NES_INI
    assert ws.set_wheel_start(cabinet["nes"], "first", cfg) is None          # nothing to do


def test_set_wheel_start_keeps_a_bom_and_legacy_bytes(tmp_path):
    path = tmp_path / "Wheel.ini"
    path.write_bytes(b"\xef\xbb\xbf[navigation]\r\nlast_game=Pok\xc3\xa9mon\r\nrandom_game=true\r\n")
    ws.set_wheel_start(path, "first")
    assert path.read_bytes() == (b"\xef\xbb\xbf[navigation]\r\nlast_game=Pok\xc3\xa9mon\r\n"
                                 b"random_game=false\r\nuse_last_game=false\r\n")
    path.write_bytes(b"[navigation]\r\nlast_game=Pok\xe9mon\r\nrandom_game=true\r\n")   # cp1252
    ws.set_wheel_start(path, "first")
    assert path.read_bytes() == (b"[navigation]\r\nlast_game=Pok\xe9mon\r\n"
                                 b"random_game=false\r\nuse_last_game=false\r\n")


def test_set_wheel_start_refuses_an_unknown_mode(tmp_path):
    path = tmp_path / "Wheel.ini"
    path.write_bytes(NES_INI)
    with pytest.raises(ValueError):
        ws.set_wheel_start(path, "both")
    assert path.read_bytes() == NES_INI


def test_backup_follows_the_config(tmp_path):
    path = tmp_path / "Settings" / "Wheel.ini"
    path.parent.mkdir()
    path.write_bytes(NES_INI)
    beside = ws.backup_settings_file(path, Config())
    assert beside.parent == path.parent and beside.name.startswith("Wheel.ini.")
    assert ws.backup_settings_file(path, Config(backup_before_modify=False)) is None
    assert ws.backup_settings_file(path, None) is None
    again = ws.backup_settings_file(path, Config())
    assert again != beside and again.exists()                  # never over the first one


def test_backups_are_found_for_the_ini_not_the_wheels_database(cabinet):
    cfg = config_mod.load_config()
    backup = ws.set_wheel_start(cabinet["nes"], "first", cfg).backup
    assert backup in find_sidecars(cabinet["nes"], cfg)
    xml = cabinet["hs"] / "Databases" / NES / f"{NES}.xml"
    assert backup not in find_sidecars(xml, cfg)


def test_hyperspin_running_reads_the_process_list(monkeypatch):
    from spindoctor import _win32

    class Proc:
        def __init__(self, name):
            self.name = name

    monkeypatch.setattr(_win32, "list_processes", lambda: [Proc("explorer.exe"), Proc("HyperSpin.exe")])
    assert ws.hyperspin_running() is True
    monkeypatch.setattr(_win32, "list_processes", lambda: [Proc("explorer.exe")])
    assert ws.hyperspin_running() is False

    def unsupported():
        raise _win32.UnsupportedPlatform("this needs Windows")

    monkeypatch.setattr(_win32, "list_processes", unsupported)
    assert ws.hyperspin_running() is False


# ── the command ───────────────────────────────────────────────────────────────

def test_command_lists_the_main_menu_wheels(cabinet):
    result = _run("wheel-start")
    assert result.exit_code == 0, result.output
    out = result.output
    assert NES in out and "a random game" in out
    assert "Sega Genesis" in out and "the last game it was on" in out
    assert "No Settings Wheel" in out and "no settings file" in out
    assert "Search" not in out                                  # runs a program, not a wheel
    assert "1 last, 1 random" in out


def test_command_lists_named_wheels_in_any_case(cabinet):
    result = _run("wheel-start", "-s", NES.upper())
    assert result.exit_code == 0 and NES in result.output and "Genesis" not in result.output


def test_set_needs_the_wheels_named(cabinet):
    result = _run("wheel-start", "--set", "first")
    assert result.exit_code == 2 and "--system" in result.output
    result = _run("wheel-start", "-s", NES, "--all", "--set", "first")
    assert result.exit_code == 2 and "not both" in result.output


def test_set_is_a_dry_run_without_apply(cabinet):
    result = _run("wheel-start", "-s", NES, "--set", "first")
    assert result.exit_code == 0, result.output
    assert "would change" in result.output and "Dry run" in result.output
    assert cabinet["nes"].read_bytes() == NES_INI
    assert not cabinet["backups"].exists()


def test_set_apply_changes_the_named_wheel(cabinet):
    result = _run("wheel-start", "-s", NES, "--set", "FIRST", "--apply")
    assert result.exit_code == 0, result.output
    assert "a random game → the first game" in result.output and "1 changed" in result.output
    assert cabinet["nes"].read_bytes() == NES_INI.replace(b"random_game=true", b"random_game=false")
    assert cabinet["genesis"].read_bytes() == GENESIS_INI
    assert len(list((cabinet["backups"] / "HyperSpin").iterdir())) == 1


def test_set_all_changes_every_main_menu_wheel(cabinet):
    result = _run("wheel-start", "--all", "--set", "random", "--apply")
    assert result.exit_code == 0, result.output
    assert "1 changed, 1 already start on a random game, 1 with no settings file" in result.output
    assert ws.read_wheel_start(cabinet["genesis"]).mode == "random"
    assert cabinet["nes"].read_bytes() == NES_INI                            # already random
    assert (cabinet["settings"] / "Search.ini").read_bytes() == b"[navigation]\r\nrandom_game=true\r\n"


def test_set_refuses_while_hyperspin_runs(cabinet, monkeypatch):
    monkeypatch.setattr(ws, "hyperspin_running", lambda: True)
    result = _run("wheel-start", "-s", NES, "--set", "first", "--apply")
    assert result.exit_code == 1 and "HyperSpin is running" in result.output
    assert cabinet["nes"].read_bytes() == NES_INI
    assert _run("wheel-start", "-s", NES, "--set", "first").exit_code == 0   # a dry run is fine


def test_set_refuses_an_unknown_wheel_before_writing(cabinet):
    result = _run("wheel-start", "-s", NES, "-s", "Nintendo Entertainment Sytem", "--set", "first", "--apply")
    assert result.exit_code == 1 and "No HyperSpin settings file" in result.output
    assert cabinet["nes"].read_bytes() == NES_INI


def test_set_refuses_hyperspins_own_settings(cabinet):
    result = _run("wheel-start", "-s", "Settings", "--set", "last", "--apply")
    assert result.exit_code == 1 and "not a game wheel" in result.output
    assert (cabinet["settings"] / "Settings.ini").read_bytes() == b"[Main]\r\nUse_Last_Game=false\r\n"
