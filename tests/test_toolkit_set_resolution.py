"""`spindoctor toolkit set-resolution`: back to HyperSpin's [Resolution].

The display is faked everywhere except the Windows-only tests at the end,
which only read the current mode and test it with CDS_TEST (nothing changes).
"""
from __future__ import annotations

import sys

import pytest
from click.testing import CliRunner

import spindoctor.config as config_mod
from spindoctor import display_mode as dm
from spindoctor import toolkit_helpers as th
from spindoctor import toolkit_screen
from spindoctor.cli import cli
from spindoctor.config import Config


class FakeDisplay:
    def __init__(self, current=(1280, 720), results=(0, 0)):
        self.mode = current
        self.results = list(results)
        self.calls = []

    def current(self):
        return self.mode

    def change(self, width, height, flags):
        self.calls.append((width, height, flags))
        code = self.results.pop(0)
        if code == 0 and flags == dm.CDS_UPDATEREGISTRY:
            self.mode = (width, height)
        return code


def _settings(tmp_path, text):
    path = tmp_path / "Settings" / "Settings.ini"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return Config(hyperspin_dir=str(tmp_path))


# ── HyperSpin's resolution ───────────────────────────────────────────────────

def test_reads_hyperspin_resolution_case_insensitively(tmp_path):
    cfg = _settings(tmp_path, "[Main]\nMenu_Mode=multi\n[resolution]\nFullScreen=true\nwidth=1920\nHEIGHT=1080\n")
    assert dm.hyperspin_resolution(cfg) == (1920, 1080)


def test_missing_or_bad_resolution_is_none(tmp_path):
    assert dm.hyperspin_resolution(Config()) is None
    assert dm.hyperspin_resolution(Config(hyperspin_dir=str(tmp_path / "none"))) is None
    assert dm.hyperspin_resolution(_settings(tmp_path, "[Resolution]\nWidth=wide\nHeight=1080\n")) is None


# ── changing the mode ────────────────────────────────────────────────────────

def test_mode_is_tested_then_saved():
    display = FakeDisplay()
    outcome = dm.set_resolution(1920, 1080, display)
    assert display.calls == [(1920, 1080, dm.CDS_TEST), (1920, 1080, dm.CDS_UPDATEREGISTRY)]
    assert outcome.changed and outcome.note == "Resolution set to 1920 × 1080"
    assert outcome.line() == "set-resolution: 1280x720 -> 1920x1080"


def test_nothing_changes_when_already_there():
    display = FakeDisplay(current=(1920, 1080))
    outcome = dm.set_resolution(1920, 1080, display)
    assert display.calls == [] and outcome.code == 0 and not outcome.changed
    assert outcome.note == "Already 1920 × 1080"


def test_unsupported_mode_is_not_saved():
    display = FakeDisplay(results=(-2,))
    outcome = dm.set_resolution(5000, 3000, display)
    assert display.calls == [(5000, 3000, dm.CDS_TEST)]
    assert outcome.note == "Couldn't set 5000 × 3000"
    assert "doesn't support it" in outcome.line() and "still 1280x720" in outcome.line()


# ── the command and its helper ───────────────────────────────────────────────

@pytest.fixture
def run_cmd(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path / ".spindoctor")
    notes, sets = [], []
    monkeypatch.setattr(toolkit_screen, "note", lambda text, seconds=3.0: notes.append(text))

    def fake_set(width, height):
        sets.append((width, height))
        return dm.Outcome(width, height, (1280, 720), 0)

    monkeypatch.setattr(dm, "set_resolution", fake_set)

    def run(*args, cfg=None):
        monkeypatch.setattr("spindoctor.cli._cfg", lambda: cfg or Config())
        return CliRunner().invoke(cli, ["toolkit", "set-resolution", *args])

    run.notes, run.sets = notes, sets
    return run


def test_command_uses_hyperspins_resolution(run_cmd, tmp_path):
    cfg = _settings(tmp_path, "[Resolution]\nWidth=1920\nHeight=1080\n")
    result = run_cmd(cfg=cfg)
    assert result.exit_code == 0, result.output
    assert run_cmd.sets == [(1920, 1080)] and run_cmd.notes == ["Resolution set to 1920 × 1080"]
    assert "1280x720 -> 1920x1080" in (tmp_path / ".spindoctor" / "toolkit.log").read_text(encoding="utf-8")


def test_command_takes_width_and_height_together(run_cmd):
    assert run_cmd("--width", "1280", "--height", "1024", "--no-note").exit_code == 0
    assert run_cmd.sets == [(1280, 1024)] and run_cmd.notes == []
    assert run_cmd("--width", "1280").exit_code == 2


def test_command_without_a_resolution_says_so(run_cmd):
    result = run_cmd()
    assert result.exit_code == 1 and "[Resolution]" in result.output and run_cmd.sets == []


def test_command_is_windows_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    result = CliRunner().invoke(cli, ["toolkit", "set-resolution"])
    assert result.exit_code == 1 and "Windows only" in result.output


def test_helper_starts_the_command_without_waiting(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\spindoctor.exe")
    helper = th.find("set-windows-resolution")
    assert helper.name == "Set Windows Resolution"
    assert 'start "" "C:\\Apps\\spindoctor.exe" --run-tool spindoctor toolkit set-resolution\r\n' in helper.body()


# ── Windows only: read the mode and test it, change nothing ─────────────────

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows display API")


@windows_only
def test_devmode_has_the_windows_size():
    import ctypes

    assert ctypes.sizeof(dm.WindowsDisplay().DEVMODEW) == 220


@windows_only
def test_the_current_mode_passes_cds_test():
    display = dm.WindowsDisplay()
    width, height = display.current()
    assert width > 0 and height > 0
    assert display.change(width, height, dm.CDS_TEST) == 0
