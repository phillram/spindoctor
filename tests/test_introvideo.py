"""Intro Video pool — folder-as-database add/remove/restore/list/swap,
plus the Windows logon auto-run install/uninstall."""
from __future__ import annotations

import random
import shutil
import sys
import time
from pathlib import Path

import pytest

import spindoctor.autostart as autostart_mod
from spindoctor.config import Config
from spindoctor.introvideo import (
    AUTORUN_TASK_NAME,
    IntroVideoError,
    SWAP_BAT_FILENAME,
    SWAP_RETRY_ATTEMPTS,
    add_video,
    add_videos,
    autorun_status,
    install_autorun,
    list_videos,
    remove_video,
    remove_videos,
    restore_video,
    swap_video,
    uninstall_autorun,
)


@pytest.fixture
def layout(tmp_path):
    pool_dir = tmp_path / "Intro Video Randomizer"
    pool_dir.mkdir(parents=True)
    (pool_dir / "Capcom Intro.mp4").write_bytes(b"a" * 100)
    (pool_dir / "FF16 Victory Theme.mp4").write_bytes(b"b" * 200)
    target = tmp_path / "Intro.mp4"
    cfg = Config()
    cfg.intro_randomizer_dir = str(pool_dir)
    cfg.intro_video_target = str(target)
    return cfg, pool_dir, target


# ── pool management ──────────────────────────────────────────────────────────

def test_list_videos_requires_pool_dir():
    with pytest.raises(IntroVideoError):
        list_videos(Config())


def test_list_videos_shows_enabled(layout):
    cfg, _pool_dir, _target = layout
    videos = list_videos(cfg)
    names = {v.filename: v.enabled for v in videos}
    assert names == {"Capcom Intro.mp4": True, "FF16 Victory Theme.mp4": True}


def test_list_videos_shows_disabled_separately(layout):
    cfg, pool_dir, _target = layout
    remove_video(cfg, "Capcom Intro.mp4", apply=True)
    videos = list_videos(cfg)
    names = {v.filename: v.enabled for v in videos}
    assert names == {"Capcom Intro.mp4": False, "FF16 Victory Theme.mp4": True}


def test_add_video_dry_run_does_not_copy(layout, tmp_path):
    cfg, pool_dir, _target = layout
    source = tmp_path / "new.mp4"
    source.write_bytes(b"new")
    result = add_video(cfg, source, apply=False)
    assert result.copied is True  # preview: "would copy"
    assert not (pool_dir / "new.mp4").exists()


def test_add_video_apply_copies(layout, tmp_path):
    cfg, pool_dir, _target = layout
    source = tmp_path / "new.mp4"
    source.write_bytes(b"new")
    result = add_video(cfg, source, apply=True)
    assert result.copied is True
    assert (pool_dir / "new.mp4").read_bytes() == b"new"


def test_add_video_never_overwrites_existing(layout, tmp_path):
    cfg, pool_dir, _target = layout
    source = tmp_path / "Capcom Intro.mp4"
    source.write_bytes(b"different bytes")
    result = add_video(cfg, source, apply=True)
    assert result.already_present is True
    assert result.copied is False
    assert (pool_dir / "Capcom Intro.mp4").read_bytes() == b"a" * 100


def test_add_video_missing_source_raises(layout, tmp_path):
    cfg, _pool_dir, _target = layout
    with pytest.raises(IntroVideoError):
        add_video(cfg, tmp_path / "nope.mp4", apply=True)


def test_add_videos_batch_validates_all_before_copying(layout, tmp_path):
    cfg, pool_dir, _target = layout
    good = tmp_path / "good.mp4"
    good.write_bytes(b"g")
    with pytest.raises(IntroVideoError):
        add_videos(cfg, [good, tmp_path / "missing.mp4"], apply=True)
    assert not (pool_dir / "good.mp4").exists()


def test_remove_video_dry_run_does_not_move(layout):
    cfg, pool_dir, _target = layout
    result = remove_video(cfg, "Capcom Intro.mp4", apply=False)
    assert result.moved is True  # preview: "would move"
    assert (pool_dir / "Capcom Intro.mp4").exists()
    assert not (pool_dir / "Disabled" / "Capcom Intro.mp4").exists()


def test_remove_video_apply_moves_to_disabled(layout):
    cfg, pool_dir, _target = layout
    result = remove_video(cfg, "Capcom Intro.mp4", apply=True)
    assert result.moved is True
    assert not (pool_dir / "Capcom Intro.mp4").exists()
    assert (pool_dir / "Disabled" / "Capcom Intro.mp4").read_bytes() == b"a" * 100


def test_remove_video_not_found(layout):
    cfg, _pool_dir, _target = layout
    result = remove_video(cfg, "Ghost.mp4", apply=True)
    assert result.moved is False
    assert result.reason == "not_found"


def test_remove_video_case_insensitive(layout):
    cfg, pool_dir, _target = layout
    result = remove_video(cfg, "capcom intro.mp4", apply=True)
    assert result.moved is True
    assert (pool_dir / "Disabled" / "Capcom Intro.mp4").exists()


def test_restore_video_moves_back(layout):
    cfg, pool_dir, _target = layout
    remove_video(cfg, "Capcom Intro.mp4", apply=True)
    result = restore_video(cfg, "Capcom Intro.mp4", apply=True)
    assert result.moved is True
    assert (pool_dir / "Capcom Intro.mp4").exists()
    assert not (pool_dir / "Disabled" / "Capcom Intro.mp4").exists()


def test_restore_video_not_found(layout):
    cfg, _pool_dir, _target = layout
    result = restore_video(cfg, "Ghost.mp4", apply=True)
    assert result.moved is False
    assert result.reason == "not_found"


def test_remove_never_deletes_the_file(layout):
    cfg, pool_dir, _target = layout
    remove_videos(cfg, ["Capcom Intro.mp4", "FF16 Victory Theme.mp4"], apply=True)
    disabled = pool_dir / "Disabled"
    assert {p.name for p in disabled.iterdir()} == {
        "Capcom Intro.mp4", "FF16 Victory Theme.mp4",
    }


def test_restore_conflict_when_pool_already_has_same_name(layout):
    cfg, pool_dir, _target = layout
    remove_video(cfg, "Capcom Intro.mp4", apply=True)
    # A different file lands back in the pool under the same name.
    (pool_dir / "Capcom Intro.mp4").write_bytes(b"conflict")
    result = restore_video(cfg, "Capcom Intro.mp4", apply=True)
    assert result.moved is False
    assert result.reason == "conflict"
    # Neither copy was touched.
    assert (pool_dir / "Capcom Intro.mp4").read_bytes() == b"conflict"
    assert (pool_dir / "Disabled" / "Capcom Intro.mp4").read_bytes() == b"a" * 100


# ── swap ──────────────────────────────────────────────────────────────────────

def test_swap_video_requires_target(tmp_path):
    cfg = Config()
    cfg.intro_randomizer_dir = str(tmp_path)
    with pytest.raises(IntroVideoError):
        swap_video(cfg, apply=True)


def test_swap_video_empty_pool_is_clean_noop(tmp_path):
    cfg = Config()
    cfg.intro_randomizer_dir = str(tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    cfg.intro_video_target = str(tmp_path / "Intro.mp4")
    result = swap_video(cfg, apply=True)
    assert result.picked is None
    assert result.pool_size == 0
    assert not Path(cfg.intro_video_target).exists()


def test_swap_video_dry_run_does_not_copy(layout):
    cfg, _pool_dir, target = layout
    result = swap_video(cfg, apply=False)
    assert result.picked in {"Capcom Intro.mp4", "FF16 Victory Theme.mp4"}
    assert not target.exists()


def test_swap_video_apply_copies_picked_file(layout):
    cfg, pool_dir, target = layout
    result = swap_video(cfg, apply=True, rng=random.Random(1))
    assert target.read_bytes() == (pool_dir / result.picked).read_bytes()


def test_swap_video_only_considers_enabled_videos(layout):
    cfg, pool_dir, target = layout
    remove_video(cfg, "Capcom Intro.mp4", apply=True)
    result = swap_video(cfg, apply=True, rng=random.Random(1))
    assert result.picked == "FF16 Victory Theme.mp4"
    assert result.pool_size == 1


def test_swap_video_uses_rng_for_reproducibility(layout):
    cfg, _pool_dir, _target = layout
    picks = {swap_video(cfg, apply=False, rng=random.Random(seed)).picked for seed in range(20)}
    # Both files should show up across enough seeds — proves it's a real
    # pick over the pool, not always returning the same/first entry.
    assert picks == {"Capcom Intro.mp4", "FF16 Victory Theme.mp4"}


def test_swap_video_retries_past_a_transient_lock(layout, monkeypatch):
    # Regression: intro_video_target can be briefly locked at boot (e.g.
    # HyperSpin still playing the *previous* intro when the logon-triggered
    # swap runs). The first two attempts fail with a sharing violation;
    # the third succeeds — swap_video must not give up early.
    cfg, pool_dir, target = layout
    real_copy2 = shutil.copy2
    calls = {"copy": 0, "sleep": 0}

    def _flaky_copy2(src, dst):
        calls["copy"] += 1
        if calls["copy"] < 3:
            raise PermissionError(13, "The process cannot access the file")
        return real_copy2(src, dst)

    monkeypatch.setattr(shutil, "copy2", _flaky_copy2)
    monkeypatch.setattr(time, "sleep", lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1))

    result = swap_video(cfg, apply=True, rng=random.Random(1))

    assert calls["copy"] == 3
    assert calls["sleep"] == 2  # slept after each of the two failures, not after the success
    assert target.read_bytes() == (pool_dir / result.picked).read_bytes()


def test_swap_video_raises_intro_video_error_when_lock_never_clears(layout, monkeypatch):
    cfg, _pool_dir, target = layout
    calls = {"copy": 0, "sleep": 0}

    def _always_locked(src, dst):
        calls["copy"] += 1
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(shutil, "copy2", _always_locked)
    monkeypatch.setattr(time, "sleep", lambda _s: calls.__setitem__("sleep", calls["sleep"] + 1))

    with pytest.raises(IntroVideoError):
        swap_video(cfg, apply=True, rng=random.Random(1))

    assert calls["copy"] == SWAP_RETRY_ATTEMPTS
    assert calls["sleep"] == SWAP_RETRY_ATTEMPTS - 1  # no sleep after the final failed attempt
    assert not target.exists()


# ── Windows logon auto-run ───────────────────────────────────────────────────

def test_install_autorun_dry_run_does_not_touch_autostart(layout, monkeypatch):
    cfg, _pool_dir, _target = layout

    def _boom(*a, **k):
        raise AssertionError("dry-run must not touch Task Scheduler")
    monkeypatch.setattr(autostart_mod, "create_logon_task", _boom)

    result = install_autorun(cfg, apply=False)
    assert result.registered is False
    assert result.task_name == AUTORUN_TASK_NAME


def test_install_autorun_requires_pool_and_target():
    with pytest.raises(IntroVideoError):
        install_autorun(Config(), apply=False)


def test_install_autorun_apply_writes_bat_and_vbs_and_registers(layout, tmp_path, monkeypatch):
    cfg, _pool_dir, _target = layout
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    calls = {}

    def _fake_create(command, *, name, delay_minutes=None):
        calls["command"] = command
        calls["name"] = name
        calls["delay_minutes"] = delay_minutes
        return autostart_mod.TaskCreateResult(name=name, command=command, output="SUCCESS")
    monkeypatch.setattr(autostart_mod, "create_logon_task", _fake_create)

    result = install_autorun(cfg, apply=True, delay_minutes=2)
    assert result.registered is True
    assert result.bat_path.exists()
    assert result.vbs_path.exists()
    bat_text = result.bat_path.read_text()
    vbs_text = result.vbs_path.read_text()
    assert "introvideo swap --apply" in bat_text
    assert calls["name"] == AUTORUN_TASK_NAME
    assert calls["delay_minutes"] == 2
    assert "wscript.exe" in calls["command"]

    # Regression: the bat must propagate spindoctor.exe's exit code as its
    # own, and the vbs must propagate that via WScript.Quit — otherwise
    # Task Scheduler's Last Result always reports 0 (success) even when
    # the swap actually failed, which is exactly what made a real swap
    # failure invisible in the field.
    assert "exit /b %errorlevel%" in bat_text
    assert "ws.Run(" in vbs_text
    assert "WScript.Quit(rc)" in vbs_text

    # Regression: the vbs must embed the bat's full, already-known path
    # directly — NOT re-derive its own folder at runtime from
    # WScript.ScriptFullName. That runtime derivation had a real,
    # confirmed-on-a-real-cabinet bug (a backslash-escaping mistake made
    # its InStrRev search string never match a real Windows path, so the
    # computed bat path silently collapsed to a bare filename with no
    # folder — which only happened to work when double-clicked, because
    # Explorer's working directory is the file's own folder; every
    # Task-Scheduler-triggered run silently failed to even find the .bat,
    # regardless of delay). Embedding the full path removes the
    # dependency on the caller's working directory — and this whole
    # class of bug — entirely.
    assert str(result.bat_path) in vbs_text
    assert "ScriptFullName" not in vbs_text
    assert "InStrRev" not in vbs_text


def test_install_autorun_bat_dir_is_stable_even_when_frozen(layout, tmp_path, monkeypatch):
    """Regression: the bat/vbs must always land in ~/.spindoctor/ — the
    same stable location config.json uses — even on a frozen (packaged
    .exe) install, NOT next to sys.executable. Portable Windows installs
    unzip each release into its own version-numbered folder, so a
    next-to-the-exe location would silently orphan the registered Task
    Scheduler entry on every upgrade.
    """
    cfg, _pool_dir, _target = layout
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    # Simulate a frozen install with sys.executable living somewhere
    # completely different from the stable ~/.spindoctor/ location.
    fake_exe_dir = tmp_path / "spindoctor-win10-v2.11.0"
    fake_exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe_dir / "spindoctor-gui.exe"))
    monkeypatch.setattr(autostart_mod, "create_logon_task", lambda *a, **k: autostart_mod.TaskCreateResult(
        name=AUTORUN_TASK_NAME, command="", output="SUCCESS",
    ))

    result = install_autorun(cfg, apply=True)

    assert result.bat_path.parent == fake_home / ".spindoctor"
    assert result.vbs_path.parent == fake_home / ".spindoctor"
    assert fake_exe_dir not in result.bat_path.parents


def test_uninstall_autorun_dry_run_reports_status_without_deleting(monkeypatch):
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)

    def _boom(*a, **k):
        raise AssertionError("dry-run must not delete the task")
    monkeypatch.setattr(autostart_mod, "delete_logon_task", _boom)

    result = uninstall_autorun(apply=False)
    assert result.registered is True


def test_uninstall_autorun_apply_deletes_when_registered(monkeypatch):
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)
    calls = {}

    def _fake_delete(name):
        calls["name"] = name
        return "SUCCESS"
    monkeypatch.setattr(autostart_mod, "delete_logon_task", _fake_delete)

    result = uninstall_autorun(apply=True)
    assert result.registered is False
    assert calls["name"] == AUTORUN_TASK_NAME


def test_uninstall_autorun_apply_noop_when_not_registered(monkeypatch):
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: False)

    def _boom(*a, **k):
        raise AssertionError("must not call delete when nothing is registered")
    monkeypatch.setattr(autostart_mod, "delete_logon_task", _boom)

    result = uninstall_autorun(apply=True)
    assert result.registered is False


def test_autorun_status_reflects_task_exists(monkeypatch):
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)
    assert autorun_status().registered is True
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: False)
    status = autorun_status()
    assert status.registered is False
    assert status.stale is False  # never stale when not even registered


def test_autorun_status_not_supported_propagates(monkeypatch):
    def _raise(name=None):
        raise autostart_mod.NotSupportedError("Windows only")
    monkeypatch.setattr(autostart_mod, "task_exists", _raise)
    with pytest.raises(autostart_mod.NotSupportedError):
        autorun_status()


def test_autorun_status_not_stale_on_source_install(monkeypatch):
    # Non-frozen: the bat calls bare "spindoctor", nothing version-
    # specific to go stale, regardless of whether a bat file even exists.
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert autorun_status().stale is False


def test_autorun_status_stale_when_bat_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fakehome")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "v2.11.0" / "spindoctor-gui.exe"))

    status = autorun_status()
    assert status.registered is True
    assert status.stale is True


def test_autorun_status_stale_when_bat_references_old_install(tmp_path, monkeypatch):
    fake_home = tmp_path / "fakehome"
    new_exe_dir = tmp_path / "v2.12.0"
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(new_exe_dir / "spindoctor-gui.exe"))
    # _sibling_spindoctor_exe() only returns the full quoted path if the
    # sibling actually exists on disk — must create it for a meaningful
    # "current install" comparison.
    new_exe_dir.mkdir(parents=True)
    (new_exe_dir / "spindoctor.exe").write_text("", encoding="utf-8")

    # Simulate a bat written by an OLDER version of spindoctor (v2.11.0),
    # sitting in the stable ~/.spindoctor/ location.
    bat_dir = fake_home / ".spindoctor"
    bat_dir.mkdir(parents=True)
    old_exe = tmp_path / "v2.11.0" / "spindoctor.exe"
    (bat_dir / SWAP_BAT_FILENAME).write_text(
        f'@echo off\r\nstart /LOW /B /WAIT "" "{old_exe}" introvideo swap --apply\r\n'
        "exit /b %errorlevel%\r\n",
        encoding="utf-8",
    )

    assert autorun_status().stale is True


def test_autorun_status_not_stale_when_bat_matches_current_install(tmp_path, monkeypatch):
    fake_home = tmp_path / "fakehome"
    exe_dir = tmp_path / "v2.11.0"
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "spindoctor-gui.exe"))
    exe_dir.mkdir(parents=True)
    (exe_dir / "spindoctor.exe").write_text("", encoding="utf-8")

    bat_dir = fake_home / ".spindoctor"
    bat_dir.mkdir(parents=True)
    (bat_dir / SWAP_BAT_FILENAME).write_text(
        f'@echo off\r\nstart /LOW /B /WAIT "" "{exe_dir / "spindoctor.exe"}" introvideo swap --apply\r\n'
        "exit /b %errorlevel%\r\n",
        encoding="utf-8",
    )

    assert autorun_status().stale is False
