"""Tests for the `doctor` **Future Pinball scripting** check
(``health.check_future_pinball_typelib``).

Future Pinball's table scripts need its type library registered with Windows;
a copied folder has no registration, so tables ignore coin, start and flippers.
"""
from __future__ import annotations

import sys

import pytest

from spindoctor import health
from spindoctor.config import Config


def _cabinet(tmp_path, emu_path=None, ini_extra=""):
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    exe = tmp_path / "Emulators" / "Future Pinball" / "Future Pinball.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    path = emu_path or r"..\Emulators\Future Pinball\Future Pinball.exe"
    (rl / "Settings" / "Global Emulators.ini").write_text(
        f"[Future Pinball]\r\nEmu_Path={path}\r\nModule=Future Pinball.ahk\r\n{ini_extra}", encoding="utf-8")
    return Config(rocketlauncher_dir=str(rl)), exe


@pytest.fixture(autouse=True)
def _windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def _registered(monkeypatch, path):
    monkeypatch.setattr(health, "_future_pinball_typelib_path", lambda: path)


def test_not_registered_warns_and_says_what_stops_working(tmp_path, monkeypatch):
    config, _exe = _cabinet(tmp_path)
    _registered(monkeypatch, None)
    result = health.check_future_pinball_typelib(config)
    assert result.status == health.Status.WARN
    assert "flippers" in result.detail
    assert "troubleshooting.md" in result.fix


def test_registered_for_the_installed_program_is_fine(tmp_path, monkeypatch):
    config, exe = _cabinet(tmp_path)
    _registered(monkeypatch, str(exe))
    result = health.check_future_pinball_typelib(config)
    assert result.status == health.Status.OK


def test_registered_with_no_path_is_fine(tmp_path, monkeypatch):
    config, _exe = _cabinet(tmp_path)
    _registered(monkeypatch, "")
    assert health.check_future_pinball_typelib(config).status == health.Status.OK


def test_registered_for_a_missing_program_warns(tmp_path, monkeypatch):
    config, _exe = _cabinet(tmp_path)
    gone = str(tmp_path / "gone" / "Future Pinball.exe")
    _registered(monkeypatch, gone)
    result = health.check_future_pinball_typelib(config)
    assert result.status == health.Status.WARN
    assert gone in result.detail


def test_bams_loader_finds_future_pinball_beside_it(tmp_path, monkeypatch):
    config, exe = _cabinet(tmp_path, emu_path=r"..\Emulators\Future Pinball\BAM\FPLoader.exe")
    _registered(monkeypatch, None)
    assert health.check_future_pinball_typelib(config).status == health.Status.WARN


def test_without_future_pinball_there_is_nothing_to_check(tmp_path, monkeypatch):
    rl = tmp_path / "RocketLauncher"
    (rl / "Settings").mkdir(parents=True)
    (rl / "Settings" / "Global Emulators.ini").write_text("[MAME]\r\nEmu_Path=..\\mame.exe\r\n", encoding="utf-8")
    _registered(monkeypatch, None)
    result = health.check_future_pinball_typelib(Config(rocketlauncher_dir=str(rl)))
    assert result.status == health.Status.INFO


def test_other_systems_only_get_info(tmp_path, monkeypatch):
    config, _exe = _cabinet(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    _registered(monkeypatch, None)
    assert health.check_future_pinball_typelib(config).status == health.Status.INFO


def test_run_health_checks_includes_both_checks(monkeypatch):
    from spindoctor.health import HealthReport  # noqa: F401

    names = []
    monkeypatch.setattr(health.HealthReport, "add", lambda self, check: names.append(check.name))
    health.run_health_checks(Config())
    assert "Keymapper hotkeys" in names
    assert "Future Pinball scripting" in names
