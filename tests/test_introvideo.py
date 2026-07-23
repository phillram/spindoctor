"""Intro Video pool — folder-as-database add/remove/restore/list/swap,
plus the Windows logon auto-run install/uninstall."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

import spindoctor.autostart as autostart_mod
from spindoctor.config import Config
from spindoctor.introvideo import (
    AUTORUN_TASK_NAME,
    IntroVideoError,
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
    assert "introvideo swap --apply" in result.bat_path.read_text()
    assert result.bat_path.name in result.vbs_path.read_text()
    assert calls["name"] == AUTORUN_TASK_NAME
    assert calls["delay_minutes"] == 2
    assert "wscript.exe" in calls["command"]


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
    assert autorun_status() is True
    monkeypatch.setattr(autostart_mod, "task_exists", lambda name=None: False)
    assert autorun_status() is False


def test_autorun_status_not_supported_propagates(monkeypatch):
    def _raise(name=None):
        raise autostart_mod.NotSupportedError("Windows only")
    monkeypatch.setattr(autostart_mod, "task_exists", _raise)
    with pytest.raises(autostart_mod.NotSupportedError):
        autorun_status()
