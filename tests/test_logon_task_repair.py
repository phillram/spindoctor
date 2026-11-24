"""The logon tasks after an upgrade renamed or moved the EXE.

The wheel-refresh and intro-video logon tasks run a ``.bat`` in
``~/.spindoctor`` that starts the SpinDoctor EXE by full path. 3.4.0 renamed
the GUI from ``spindoctor-gui.exe`` to ``spindoctor.exe``; a cabinet that
upgraded without re-clicking Enable auto-run got "Windows cannot find
'...\\spindoctor-gui.exe'" three times at every log on, once per ``start`` in
the wheel-refresh ``.bat``. Now the ``.bat`` quits quietly when its EXE is gone,
and the GUI points both tasks at itself at launch when theirs no longer exists.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import spindoctor.autostart as autostart_mod
from spindoctor import gui, introvideo
from spindoctor._runtime import missing_exe_guard

REFRESH_BAT = "spindoctor-refresh-wheels.bat"


def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".spindoctor").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home / ".spindoctor"


def _frozen(monkeypatch, exe):
    """Run as the frozen EXE *exe*, which exists."""
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def _registered(monkeypatch, value=True):
    names = []

    def task_exists(name=autostart_mod.DEFAULT_LOGON_TASK):
        names.append(name)
        return value
    monkeypatch.setattr(autostart_mod, "task_exists", task_exists)
    return names


def _old_refresh_bat(folder, exe):
    """The wheel-refresh .bat as 3.0 to 3.3 wrote it."""
    text = "@echo off\r\nset FAILED=0\r\n"
    for tool, verb in (("spindoctor-fav", "rebuild"), ("spindoctor-recent", "rebuild"),
                       ("spindoctor-stats", "build-wheel")):
        text += (f'start /LOW /B /WAIT "" "{exe}" --run-tool {tool} {verb} --apply\r\n'
                 "if errorlevel 1 set FAILED=1\r\n")
    path = folder / REFRESH_BAT
    path.write_text(text + "exit /b %FAILED%\r\n", encoding="utf-8")
    return path


def _old_swap_bat(folder, exe):
    path = folder / introvideo.SWAP_BAT_FILENAME
    path.write_text(f'@echo off\r\nstart /LOW /B /WAIT "" "{exe}" --run-tool spindoctor '
                    "introvideo swap --apply\r\nexit /b %errorlevel%\r\n", encoding="utf-8")
    return path


def _lines(path):
    """The .bat's commands; Windows text mode doubles the CR of each ``\\r\\n``."""
    text = path.read_bytes().decode("utf-8")
    return [line.strip("\r") for line in text.split("\n") if line.strip("\r")]


def _app():
    return object.__new__(gui._SpinDoctorGUI)


def _run_now(work, on_done, on_error):
    try:
        result = work()
    except Exception as exc:  # noqa: BLE001
        on_error(exc)
    else:
        on_done(result)


# ── the .bat quits quietly when its EXE is gone ─────────────────────────────

def test_guard_names_the_frozen_exe(tmp_path, monkeypatch):
    exe = tmp_path / "spindoctor" / "spindoctor.exe"
    _frozen(monkeypatch, exe)
    assert missing_exe_guard() == f'if not exist "{exe}" exit /b 2\r\n'


def test_no_guard_on_a_source_install(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert missing_exe_guard() == ""


def test_refresh_bat_checks_for_its_exe_before_any_start(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    exe = tmp_path / "spindoctor" / "spindoctor.exe"
    _frozen(monkeypatch, exe)
    lines = _lines(_app()._write_refresh_bat())
    assert lines[1] == f'if not exist "{exe}" exit /b 2'
    starts = [i for i, line in enumerate(lines) if line.startswith("start ")]
    assert len(starts) == 3 and min(starts) > 1


def test_swap_bat_checks_for_its_exe_before_start(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    exe = tmp_path / "spindoctor" / "spindoctor.exe"
    _frozen(monkeypatch, exe)
    lines = _lines(introvideo._write_swap_bat())
    assert lines[1] == f'if not exist "{exe}" exit /b 2'
    assert lines[2].startswith("start ") and "introvideo swap --apply" in lines[2]


def test_source_install_bats_have_no_guard(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert "if not exist" not in _app()._write_refresh_bat().read_text(encoding="utf-8")
    assert "if not exist" not in introvideo._write_swap_bat().read_text(encoding="utf-8")


# ── runs_missing_exe ─────────────────────────────────────────────────────────

def test_a_bat_running_a_gone_exe_is_found(tmp_path):
    bat = _old_refresh_bat(tmp_path, tmp_path / "spindoctor" / "spindoctor-gui.exe")
    assert autostart_mod.runs_missing_exe(bat) is True


def test_a_bat_running_an_existing_exe_is_not(tmp_path):
    exe = tmp_path / "spindoctor" / "spindoctor.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    assert autostart_mod.runs_missing_exe(_old_refresh_bat(tmp_path, exe)) is False


def test_no_bat_and_path_commands_are_not_missing_exes(tmp_path):
    assert autostart_mod.runs_missing_exe(tmp_path / REFRESH_BAT) is False
    bat = tmp_path / REFRESH_BAT
    bat.write_text('@echo off\r\nstart /LOW /B /WAIT "" spindoctor-fav rebuild --apply\r\n'
                   'start "" "%ProgramFiles%\\gone\\x.exe"\r\n', encoding="utf-8")
    assert autostart_mod.runs_missing_exe(bat) is False


# ── the GUI points the tasks at itself ───────────────────────────────────────

def test_refresh_task_is_pointed_at_this_exe_when_its_exe_is_gone(tmp_path, monkeypatch):
    folder = _home(tmp_path, monkeypatch)
    old = tmp_path / "spindoctor" / "spindoctor-gui.exe"
    new = tmp_path / "spindoctor" / "spindoctor.exe"
    _frozen(monkeypatch, new)
    bat = _old_refresh_bat(folder, old)
    names = _registered(monkeypatch)

    assert _app()._repair_refresh_task() is True
    text = bat.read_text(encoding="utf-8")
    assert str(old) not in text
    assert text.count(f'"{new}" --run-tool spindoctor-') == 3
    assert "if not exist" in text
    vbs = (folder / REFRESH_BAT).with_suffix(".vbs").read_text(encoding="utf-8")
    assert str(bat) in vbs
    assert names == [autostart_mod.DEFAULT_LOGON_TASK]


def test_swap_task_is_pointed_at_this_exe_when_its_exe_is_gone(tmp_path, monkeypatch):
    folder = _home(tmp_path, monkeypatch)
    old = tmp_path / "spindoctor" / "spindoctor-gui.exe"
    new = tmp_path / "spindoctor" / "spindoctor.exe"
    _frozen(monkeypatch, new)
    bat = _old_swap_bat(folder, old)
    names = _registered(monkeypatch)

    assert introvideo.repair_autorun() is True
    text = bat.read_text(encoding="utf-8")
    assert str(old) not in text and f'"{new}" --run-tool spindoctor introvideo swap' in text
    assert bat.with_suffix(".vbs").is_file()
    assert names == [introvideo.AUTORUN_TASK_NAME]
    assert introvideo.autorun_status().stale is False


def test_a_task_whose_exe_still_exists_is_left_alone(tmp_path, monkeypatch):
    # Two installs side by side: each keeps the tasks the other set up.
    folder = _home(tmp_path, monkeypatch)
    other = tmp_path / "other" / "spindoctor.exe"
    other.parent.mkdir()
    other.write_bytes(b"MZ")
    _frozen(monkeypatch, tmp_path / "spindoctor" / "spindoctor.exe")
    refresh = _old_refresh_bat(folder, other)
    swap = _old_swap_bat(folder, other)
    before = (refresh.read_bytes(), swap.read_bytes())
    names = _registered(monkeypatch)

    assert _app()._repair_refresh_task() is False
    assert introvideo.repair_autorun() is False
    assert (refresh.read_bytes(), swap.read_bytes()) == before
    assert names == []  # no schtasks call when nothing is broken


def test_a_bat_no_task_runs_is_left_alone(tmp_path, monkeypatch):
    folder = _home(tmp_path, monkeypatch)
    old = tmp_path / "spindoctor" / "spindoctor-gui.exe"
    _frozen(monkeypatch, tmp_path / "spindoctor" / "spindoctor.exe")
    refresh = _old_refresh_bat(folder, old)
    swap = _old_swap_bat(folder, old)
    before = (refresh.read_bytes(), swap.read_bytes())
    _registered(monkeypatch, False)

    assert _app()._repair_refresh_task() is False
    assert introvideo.repair_autorun() is False
    assert (refresh.read_bytes(), swap.read_bytes()) == before


def test_a_source_install_repairs_nothing(tmp_path, monkeypatch):
    folder = _home(tmp_path, monkeypatch)
    old = tmp_path / "spindoctor" / "spindoctor-gui.exe"
    refresh = _old_refresh_bat(folder, old)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    _registered(monkeypatch)

    assert _app()._repair_refresh_task() is False
    assert introvideo.repair_autorun() is False
    assert str(old) in refresh.read_text(encoding="utf-8")


def test_launch_repairs_both_tasks_and_says_so(tmp_path, monkeypatch):
    folder = _home(tmp_path, monkeypatch)
    old = tmp_path / "spindoctor" / "spindoctor-gui.exe"
    new = tmp_path / "spindoctor" / "spindoctor.exe"
    _frozen(monkeypatch, new)
    _old_refresh_bat(folder, old)
    _old_swap_bat(folder, old)
    _registered(monkeypatch)
    app = _app()
    app._run_background = _run_now
    app._append_output = Mock()
    app._set_status = Mock()
    app._refresh_autorefresh_status = Mock()
    app._refresh_introvideo_autorun_status = Mock()

    app._repair_logon_tasks()

    message = app._set_status.call_args[0][0]
    assert "wheel refresh and intro video" in message and str(new) in message
    app._append_output.assert_called_once_with(message + "\n")
    app._refresh_autorefresh_status.assert_called_once_with()
    app._refresh_introvideo_autorun_status.assert_called_once_with()


def test_launch_repairs_the_other_task_when_one_fails(tmp_path, monkeypatch):
    folder = _home(tmp_path, monkeypatch)
    old = tmp_path / "spindoctor" / "spindoctor-gui.exe"
    _frozen(monkeypatch, tmp_path / "spindoctor" / "spindoctor.exe")
    swap = _old_swap_bat(folder, old)
    _registered(monkeypatch)
    app = _app()
    app._run_background = _run_now
    app._append_output = Mock()
    app._set_status = Mock()
    app._refresh_autorefresh_status = Mock()
    app._refresh_introvideo_autorun_status = Mock()

    def _boom():
        raise PermissionError("locked")
    app._repair_refresh_task = _boom

    app._repair_logon_tasks()

    assert str(old) not in swap.read_text(encoding="utf-8")
    message = app._set_status.call_args[0][0]
    assert "intro video" in message and "wheel refresh" not in message


def test_launch_is_quiet_when_nothing_needed_repair(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    _frozen(monkeypatch, tmp_path / "spindoctor" / "spindoctor.exe")
    _registered(monkeypatch)
    app = _app()
    app._run_background = _run_now
    app._append_output = Mock()
    app._set_status = Mock()

    app._repair_logon_tasks()

    app._append_output.assert_not_called()
    app._set_status.assert_not_called()


def test_launch_from_source_starts_no_background_work(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    app = _app()
    app._run_background = Mock()
    app._repair_logon_tasks()
    app._run_background.assert_not_called()
