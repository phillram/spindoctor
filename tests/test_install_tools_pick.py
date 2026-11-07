"""`install-tools` / `uninstall-tools --tool`: each helper picked on its own.

`install-tools` used to write the four Refresh helpers as one bundle.  Now it
writes only the helpers ``--tool`` names (and lists them when none is
given), leaves helpers an earlier run installed alone, and keeps the rest of
a wheel's PCLauncher module INI byte for byte.  `uninstall-tools --tool`
removes just those helpers; `doctor`'s fix names the helpers to re-install;
the GUI shows the same list as a checklist.

Every test builds its own cabinet under tmp_path.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import health
from spindoctor import toolkit_helpers as th
from spindoctor.cli import cli
from spindoctor.config import Config
from spindoctor.database import HyperspinDatabase
from spindoctor.rocketlauncher import strip_toolkit_sections, write_toolkit_module_ini

REFRESH = ("Refresh Favorites", "Refresh Recently Played", "Refresh Most Played", "Refresh All")


@pytest.fixture
def cabinet(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config_mod, "CONFIG_DIR", home / ".spindoctor")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", home / ".spindoctor" / "config.json")
    config_mod.reset_override_cache()
    hs = tmp_path / "hyperspin"
    rl = tmp_path / "rocketlauncher"
    for d in (tmp_path / "roms", hs / "Databases" / "Toolkit", hs / "Media", rl / "Settings"):
        d.mkdir(parents=True)
    (hs / "Databases" / "Toolkit" / "Toolkit.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<menu></menu>\n', encoding="utf-8")
    config_mod.save_config(Config(
        roms_dir=str(tmp_path / "roms"), hyperspin_dir=str(hs), rocketlauncher_dir=str(rl),
        emulators_dir=str(tmp_path / "emulators"),
    ))
    yield {"hs": hs, "rl": rl,
           "menu": rl / "Modules" / "HyperLaunch" / "Tools" / "spindoctor",
           "pcl": rl / "Modules" / "PCLauncher" / "Toolkit",
           "module": rl / "Modules" / "PCLauncher" / "Toolkit.ini",
           "db": hs / "Databases" / "Toolkit" / "Toolkit.xml"}
    config_mod.reset_override_cache()


def _run(*args):
    return CliRunner().invoke(cli, list(args), catch_exceptions=False)


def _games(cab):
    db = HyperspinDatabase("Toolkit", cab["db"])
    db.load()
    return set(db.games())


# ── the helper list ──────────────────────────────────────────────────────────

def test_every_helper_has_a_unique_name_and_key():
    names = [h.name for h in th.HELPERS]
    assert len(set(names)) == len(names)
    assert len({h.key for h in th.HELPERS}) == len(names)
    assert names[:4] == list(REFRESH)
    assert th.find("Refresh All").key == "refresh-all"
    assert all(h.summary and h.body for h in th.HELPERS)
    assert th.ALL_NAMES == set(names) | {"Refresh Both"}
    assert not set(th.LEGACY_NAMES) & set(names)


def test_pick_takes_keys_names_commas_and_repeats_in_list_order():
    picked = th.pick(["refresh-all", "Refresh Favorites, refresh_most_played", "REFRESH-ALL"])
    assert [h.name for h in picked] == ["Refresh Favorites", "Refresh Most Played", "Refresh All"]
    assert th.pick([]) == [] and th.pick([" , "]) == []


def test_pick_names_every_unknown_value():
    with pytest.raises(ValueError) as exc:
        th.pick(["refresh-all,refresh-everything", "Refresh Both"])
    assert "refresh-everything" in str(exc.value) and "Refresh Both" in str(exc.value)


def test_tool_option_round_trips_through_pick():
    option = th.tool_option(th.HELPERS)
    assert option.startswith("--tool ") and " " not in option[len("--tool "):]
    assert th.pick([option[len("--tool "):]]) == list(th.HELPERS)


# ── install-tools ────────────────────────────────────────────────────────────

def test_no_pick_lists_the_helpers_and_writes_nothing(cabinet):
    result = _run("install-tools")
    assert result.exit_code == 2
    for h in th.HELPERS:
        assert h.key in result.output and h.name in result.output
    assert "--tool" in result.output
    assert not cabinet["menu"].exists()


def test_an_unknown_helper_stops_before_writing(cabinet):
    result = _run("install-tools", "--tool", "refresh-all,refresh-everything")
    assert result.exit_code == 2
    assert "refresh-everything" in result.output
    assert not cabinet["menu"].exists()


def test_only_the_picked_helpers_are_written(cabinet):
    result = _run("install-tools", "--tool", "refresh-all")
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in cabinet["menu"].iterdir()) == ["Refresh All.bat"]
    assert "Refresh All.bat" in result.output


def test_repeated_and_comma_separated_picks_combine(cabinet):
    result = _run("install-tools", "--tool", "refresh-favorites", "--tool",
                  "Refresh Most Played,refresh-favorites")
    assert result.exit_code == 0, result.output
    assert sorted(p.stem for p in cabinet["menu"].iterdir()) == ["Refresh Favorites", "Refresh Most Played"]


def test_helpers_not_picked_this_time_are_left_alone(cabinet):
    assert _run("install-tools", "--tool", ",".join(th.find(n).key for n in REFRESH)).exit_code == 0
    kept = cabinet["menu"] / "Refresh Favorites.bat"
    kept.write_bytes(b"@echo off\r\nREM edited by hand\r\n")
    assert _run("install-tools", "--tool", "refresh-all").exit_code == 0
    assert sorted(p.stem for p in cabinet["menu"].iterdir()) == sorted(REFRESH)
    assert kept.read_bytes() == b"@echo off\r\nREM edited by hand\r\n"


def test_a_legacy_refresh_both_bat_is_still_removed(cabinet):
    cabinet["menu"].mkdir(parents=True)
    (cabinet["menu"] / "Refresh Both.bat").write_text("@echo off\n", encoding="utf-8")
    assert _run("install-tools", "--tool", "refresh-favorites").exit_code == 0
    assert not (cabinet["menu"] / "Refresh Both.bat").exists()


def test_bat_files_end_lines_with_one_cr(cabinet):
    assert _run("install-tools", "--tool", "refresh-all,refresh-favorites").exit_code == 0
    for bat in cabinet["menu"].iterdir():
        data = bat.read_bytes()
        assert b"\r\r\n" not in data, bat.name
        assert data.endswith(b"\r\n") and data.count(b"\n") == data.count(b"\r\n"), bat.name


def test_add_to_system_adds_only_the_picked_entries_and_keeps_earlier_ones(cabinet):
    keys = ",".join(th.find(n).key for n in REFRESH[:3])
    assert _run("install-tools", "--tool", keys, "--add-to-system", "Toolkit", "--apply").exit_code == 0
    assert _games(cabinet) == set(REFRESH[:3])
    result = _run("install-tools", "--tool", "refresh-all", "--add-to-system", "Toolkit", "--apply")
    assert result.exit_code == 0, result.output
    assert _games(cabinet) == set(REFRESH)
    module = cabinet["module"].read_text(encoding="utf-8")
    for name in REFRESH:
        assert module.count(f"[{name}]") == 1, name
    assert sorted(p.name for p in cabinet["pcl"].iterdir()) == sorted(
        [f"{n}.bat" for n in REFRESH] + [f"{n}.ini" for n in REFRESH])


def test_add_to_system_dry_run_names_only_the_picked_entries(cabinet):
    result = _run("install-tools", "--tool", "refresh-most-played", "--add-to-system", "Toolkit")
    assert result.exit_code == 0, result.output
    assert "Refresh Most Played" in result.output and "Refresh All" not in result.output
    assert _games(cabinet) == set()


# ── the PCLauncher module INI ────────────────────────────────────────────────

def test_module_ini_keeps_everything_else_byte_for_byte(tmp_path):
    rl = tmp_path / "rl"
    module = rl / "Modules" / "PCLauncher" / "Toolkit.ini"
    module.parent.mkdir(parents=True)
    head = ("\ufeff[Example]\r\nApplication=\r\n\r\n[exit]\r\nApplication=..\\Tools\\exit.exe\r\n"
            "Parameters=desktop\r\n").encode("utf-8")
    old_ours = b"[refresh all]\r\nApplication=C:\\old\\Refresh All.bat\r\n"
    kept_ours = b"[Refresh Favorites]\r\nApplication=C:\\old\\Refresh Favorites.bat\r\n"
    tail = "[caf\u00e9]\r\nApplication=..\\Tools\\caf\u00e9.exe\r\n".encode("utf-8")
    module.write_bytes(head + old_ours + kept_ours + tail)
    bat = tmp_path / "Toolkit" / "Refresh All.bat"
    write_toolkit_module_ini("Toolkit", [("Refresh All", bat)], rl)
    data = module.read_bytes()
    assert data.startswith(head + kept_ours + tail)
    added = data[len(head + kept_ours + tail):].decode("utf-8")
    assert added == f"[Refresh All]\r\nApplication={bat}\r\nWorkingFolder={bat.parent}\r\n\r\n"
    assert b"C:\\old\\Refresh All.bat" not in data


def test_module_ini_keeps_lf_newlines_and_drops_legacy_sections(tmp_path):
    rl = tmp_path / "rl"
    module = rl / "Modules" / "PCLauncher" / "Toolkit.ini"
    module.parent.mkdir(parents=True)
    module.write_bytes(b"[Gun]\nApplication=gun.exe\n[Refresh Both]\nApplication=both.bat\n")
    bat = tmp_path / "Toolkit" / "Refresh Favorites.bat"
    write_toolkit_module_ini("Toolkit", [("Refresh Favorites", bat)], rl)
    text = module.read_bytes().decode("utf-8")
    assert "\r" not in text and "Refresh Both" not in text
    assert text.startswith("[Gun]\nApplication=gun.exe\n[Refresh Favorites]\n")


def test_strip_toolkit_sections_reads_names_the_way_rocketlauncher_does():
    text = ("[Keep]\na=1\n[ Refresh All ] ; ours\nApplication=x.bat\n"
            "[REFRESH FAVORITES]\nApplication=y.bat\n[Refresh All Wheels]\nb=2\n")
    kept, found = strip_toolkit_sections(text, ["Refresh All", "Refresh Favorites"])
    assert kept == "[Keep]\na=1\n[Refresh All Wheels]\nb=2\n"
    assert found == ["Refresh All", "REFRESH FAVORITES"]


# ── uninstall-tools --tool ───────────────────────────────────────────────────

def test_uninstall_tool_removes_only_that_helper_from_the_tools_menu(cabinet):
    assert _run("install-tools", "--tool", "refresh-all,refresh-favorites").exit_code == 0
    result = _run("uninstall-tools", "--tool", "refresh-all", "--apply")
    assert result.exit_code == 0, result.output
    assert [p.name for p in cabinet["menu"].iterdir()] == ["Refresh Favorites.bat"]


def test_uninstall_tool_from_a_wheel_removes_only_that_helper(cabinet):
    keys = ",".join(th.find(n).key for n in REFRESH)
    assert _run("install-tools", "--tool", keys, "--add-to-system", "Toolkit", "--apply").exit_code == 0
    module_before = cabinet["module"].read_bytes()
    result = _run("uninstall-tools", "--tool", "refresh-most-played", "--add-to-system", "Toolkit", "--apply")
    assert result.exit_code == 0, result.output
    assert _games(cabinet) == set(REFRESH) - {"Refresh Most Played"}
    assert not (cabinet["pcl"] / "Refresh Most Played.bat").exists()
    assert not (cabinet["pcl"] / "Refresh Most Played.ini").exists()
    assert (cabinet["pcl"] / "Refresh All.bat").exists()
    module = cabinet["module"].read_bytes()
    assert b"[Refresh Most Played]" not in module and b"[Refresh All]" in module
    kept, _found = strip_toolkit_sections(module_before.decode("utf-8"), ["Refresh Most Played"])
    assert module.decode("utf-8") == kept


def test_uninstall_without_a_pick_still_removes_every_helper(cabinet):
    assert _run("install-tools", "--tool", "refresh-all,refresh-favorites").exit_code == 0
    (cabinet["menu"] / "Refresh Both.bat").write_text("@echo off\n", encoding="utf-8")
    assert _run("uninstall-tools", "--apply").exit_code == 0
    assert list(cabinet["menu"].iterdir()) == []


def test_uninstall_unknown_helper_exits_2(cabinet):
    result = _run("uninstall-tools", "--tool", "refresh-everything", "--apply")
    assert result.exit_code == 2 and "refresh-everything" in result.output


# ── doctor ───────────────────────────────────────────────────────────────────

def test_doctor_fix_names_the_helpers_in_that_folder(tmp_path):
    rl = tmp_path / "RocketLauncher"
    menu = rl / "Modules" / "HyperLaunch" / "Tools" / "spindoctor"
    menu.mkdir(parents=True)
    old = tmp_path / "old" / "spindoctor-gui.exe"
    for stem in ("Refresh Most Played", "Refresh Both"):
        (menu / f"{stem}.bat").write_text(
            f'start "" /B /WAIT "{old}" --run-tool spindoctor-stats build-wheel --apply\r\n',
            encoding="utf-8")
    chk = health.check_refresh_helpers(Config(rocketlauncher_dir=str(rl)))
    assert chk.name == "SpinDoctor helpers"
    row = chk.children[0]
    # The legacy Refresh Both comes back as the helper that replaced it.
    assert row.fix == "spindoctor install-tools --tool refresh-most-played,refresh-all"
    assert _picks_are_valid(row.fix)


def _picks_are_valid(fix):
    value = fix.split("--tool ", 1)[1].split(" ", 1)[0]
    return bool(th.pick([value]))


# ── GUI checklist ────────────────────────────────────────────────────────────

def test_gui_checklist_passes_the_ticked_helpers(monkeypatch):
    from tests.test_gui import _build_gui_for_test

    app, _tk = _build_gui_for_test(monkeypatch)
    try:
        assert list(app._tools_pick_vars) == [h.key for h in th.HELPERS]
        ran = []
        monkeypatch.setattr(app, "_run_cli", lambda _bin, args: ran.append(list(args)))
        prompts = []
        monkeypatch.setattr(app, "_flash_validation", prompts.append)

        app._run_install_tools()  # nothing ticked
        assert ran == [] and "Tick at least one helper" in prompts[-1]

        app._tools_pick_vars["refresh-all"].set(True)
        app._tools_pick_vars["refresh-favorites"].set(True)
        app._run_install_tools()
        app._tools_wheel_var.set("Toolkit")
        app._run_install_tools_into_wheel()
        assert ran == [
            ["install-tools", "--tool", "refresh-favorites,refresh-all"],
            ["install-tools", "--tool", "refresh-favorites,refresh-all", "--add-to-system", "Toolkit"],
        ]

        monkeypatch.setattr(app.messagebox, "askyesno", lambda *_a, **_k: True)
        app._global_apply_var.set(True)
        app._run_uninstall_tools_from_wheel()
        assert ran[-1] == ["uninstall-tools", "--tool", "refresh-favorites,refresh-all",
                           "--add-to-system", "Toolkit", "--apply"]
    finally:
        app.root.destroy()
