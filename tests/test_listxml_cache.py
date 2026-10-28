"""MAME -listxml cache: one dump per MAME executable, not one per system.

The dump depends only on the MAME binary, but it used to be cached as
``mame_listxml_cache/<System>.xml``. ``audit --all`` re-ran ``mame -listxml``
for every MAME-ish system and wrote identical ~200 MB copies. These tests
mock ``subprocess.run``; MAME is never executed.
"""
from __future__ import annotations

import os
import re
import time
import types

import pytest

from spindoctor import cleanup, health, ledblinky
from spindoctor.audit import audit_system
from spindoctor.config import Config

LISTXML = (
    b'<?xml version="1.0"?><mame>'
    b'<machine name="pacman"><description>Pac-Man</description>'
    b'<input players="1"><control type="joy" player="1" buttons="0" ways="4"/></input></machine>'
    b'<machine name="galaga"><description>Galaga</description>'
    b'<input players="2"><control type="joy" player="1" buttons="1" ways="2"/></input></machine>'
    b"</mame>"
)


def _make_exe(path, age_s=3600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    t = time.time() - age_s
    os.utime(str(path), (t, t))
    return path


@pytest.fixture
def mame(tmp_path, monkeypatch):
    """A fake MAME binary, an empty cache dir and a counting ``subprocess.run``."""
    home = tmp_path / "home"
    cache_dir = home / "mame_listxml_cache"
    monkeypatch.setattr(ledblinky, "LISTXML_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cleanup, "CONFIG_DIR", home)
    monkeypatch.setattr(ledblinky, "_listxml_memo", {}, raising=False)

    state = types.SimpleNamespace(calls=[], xml=LISTXML, fail=False, returncode=0)

    class _Proc:
        stderr = b""

        def __init__(self, stdout, returncode):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(cmd, **_kwargs):
        state.calls.append(list(cmd))
        if state.fail:
            raise FileNotFoundError(cmd[0])
        return _Proc(state.xml, state.returncode)

    monkeypatch.setattr(ledblinky.subprocess, "run", fake_run)

    exe = _make_exe(tmp_path / "Emulators" / "MAME" / "mame.exe")
    roms = tmp_path / "roms"
    hs = tmp_path / "hs"
    roms.mkdir()
    (hs / "Databases").mkdir(parents=True)
    cfg = Config(roms_dir=str(roms), hyperspin_dir=str(hs), mame_executable=str(exe))
    state.exe = exe
    state.cfg = cfg
    state.cache_dir = cache_dir
    state.home = home
    return state


def _files(directory):
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


# ─── one dump per MAME binary ───────────────────────────────────────────────


def test_two_systems_run_listxml_once_and_share_one_cache_file(mame):
    a = ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    b = ledblinky.load_listxml_for_system(mame.cfg, "Neo Geo")
    assert len(mame.calls) == 1
    assert mame.calls[0] == [str(mame.exe), "-listxml"]
    assert _files(mame.cache_dir) == [ledblinky.listxml_cache_path(str(mame.exe)).name]
    assert set(a) == set(b) == {"pacman", "galaga"}


def test_cache_file_name_is_exe_stem_plus_path_hash(mame):
    path = ledblinky.listxml_cache_path(str(mame.exe))
    assert path.parent == mame.cache_dir
    assert re.match(r"^mame-[0-9a-f]{8}\.xml$", path.name)


def test_listxml_is_parsed_once_per_process(mame, monkeypatch):
    parses = []
    real_parse = ledblinky.parse_listxml

    def counting_parse(xml_bytes, **kwargs):
        parses.append(len(xml_bytes))
        return real_parse(xml_bytes, **kwargs)

    monkeypatch.setattr(ledblinky, "parse_listxml", counting_parse)
    for system in ("MAME", "Neo Geo", "Capcom CPS2", "Arcade Classics"):
        ledblinky.load_listxml_for_system(mame.cfg, system)
    assert len(parses) == 1
    assert len(mame.calls) == 1


def test_cache_file_is_reused_by_a_later_process(mame):
    ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    ledblinky._listxml_memo.clear()  # what a fresh process starts with
    info = ledblinky.load_listxml_for_system(mame.cfg, "Neo Geo")
    assert len(mame.calls) == 1
    assert "galaga" in info


def test_crashed_mame_run_is_used_but_not_cached(mame):
    """MAME exiting non-zero after writing part of the dump: the partial data
    is used this time, but must not sit in the cache looking fresh."""
    mame.returncode = 1
    xml = ledblinky.run_mame_listxml(
        str(mame.exe), cache_path=ledblinky.listxml_cache_path(str(mame.exe)),
    )
    assert xml == LISTXML
    assert _files(mame.cache_dir) == []


def test_bare_mame_on_path_is_resolved_for_the_freshness_check(mame, monkeypatch):
    """With mame_executable = "mame", Path("mame").exists() is False, which
    made any cache count as fresh even after MAME was upgraded."""
    monkeypatch.setattr(ledblinky.shutil, "which", lambda name: str(mame.exe))
    mame.cfg.mame_executable = "mame"
    ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    _make_exe(mame.exe, age_s=-3600)  # upgraded: now newer than the cache
    ledblinky._listxml_memo.clear()
    ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    assert len(mame.calls) == 2


def test_newer_mame_binary_invalidates_cache_and_memo(mame):
    ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    cache = ledblinky.listxml_cache_path(str(mame.exe))
    # The cache was written before a MAME upgrade replaced the binary.
    old = time.time() - 1800
    os.utime(str(cache), (old, old))
    new = time.time() - 60
    os.utime(str(mame.exe), (new, new))
    mame.xml = LISTXML.replace(b"</mame>", b'<machine name="dkong"><input players="1"/></machine></mame>')

    info = ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    assert len(mame.calls) == 2
    assert "dkong" in info
    assert b"dkong" in cache.read_bytes()

    # The rewritten cache is now newer than the binary, so it is used again.
    ledblinky._listxml_memo.clear()
    ledblinky.load_listxml_for_system(mame.cfg, "Neo Geo")
    assert len(mame.calls) == 2


def test_different_mame_binaries_get_different_cache_files(mame, tmp_path):
    gun_exe = _make_exe(tmp_path / "Emulators" / "MAME (gun)" / "mame.exe")
    gun_cfg = Config(roms_dir=mame.cfg.roms_dir, hyperspin_dir=mame.cfg.hyperspin_dir,
                     mame_executable=str(gun_exe))
    main_path = ledblinky.listxml_cache_path(str(mame.exe))
    gun_path = ledblinky.listxml_cache_path(str(gun_exe))
    assert main_path != gun_path

    ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    ledblinky.load_listxml_for_system(gun_cfg, "MAME")
    assert [c[0] for c in mame.calls] == [str(mame.exe), str(gun_exe)]
    assert _files(mame.cache_dir) == sorted([main_path.name, gun_path.name])

    # Switching back finds the first binary's file still fresh.
    ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    assert len(mame.calls) == 2


def test_same_binary_spelled_differently_shares_the_cache_file(mame, tmp_path, monkeypatch):
    exe = mame.exe
    dotted = exe.parent / ".." / exe.parent.name / exe.name
    assert ledblinky.listxml_cache_path(str(dotted)) == ledblinky.listxml_cache_path(str(exe))

    monkeypatch.chdir(tmp_path)
    relative = os.path.join("Emulators", "MAME", "mame.exe")
    assert ledblinky.listxml_cache_path(relative) == ledblinky.listxml_cache_path(str(exe))

    # A bare command name resolves through PATH.
    monkeypatch.setattr(ledblinky.shutil, "which", lambda name: str(exe))
    assert ledblinky.listxml_cache_path("mame") == ledblinky.listxml_cache_path(str(exe))


# ─── callers ────────────────────────────────────────────────────────────────


def test_audit_of_several_mame_systems_runs_listxml_once(mame):
    roms = mame.cfg.roms_dir
    for system in ("MAME", "Neo Geo", "Capcom CPS1"):
        (mame.cfg.databases_dir / system).mkdir(parents=True)
        (mame.cfg.databases_dir / system / f"{system}.xml").write_text(
            '<menu><game name="pacman"/></menu>', encoding="utf-8")
        os.makedirs(os.path.join(roms, system))
        result = audit_system(system, mame.cfg, check_media_flag=False, fuzzy=False)
        assert result.listxml_error is None
        assert [e.has_mame_input for e in result.entries] == [True]
    assert len(mame.calls) == 1
    assert len(_files(mame.cache_dir)) == 1


def _led_cabinet(mame):
    led = mame.cache_dir.parent.parent / "led"
    led.mkdir()
    mame.cfg.ledblinky_dir = str(led)
    (led / ledblinky.CONTROLS_INI_NAME).write_text("[pacman]\nP1_JOYSTICK=Red\n", encoding="utf-8")
    (led / ledblinky.COLORS_INI_NAME).write_text("[pacman]\nP1_JOYSTICK=Red\n", encoding="utf-8")
    dbdir = mame.cfg.databases_dir / "MAME"
    dbdir.mkdir(parents=True)
    (dbdir / "MAME.xml").write_text(
        '<menu><game name="pacman"/><game name="galaga"/></menu>', encoding="utf-8")
    mame.fail = True  # doctor must never run MAME


def test_led_coverage_check_finds_cache_under_new_name(mame):
    _led_cabinet(mame)
    cache = ledblinky.listxml_cache_path(mame.cfg.mame_executable)
    cache.parent.mkdir(parents=True)
    cache.write_bytes(LISTXML)

    result = health.check_led_coverage(mame.cfg)
    assert "not cached" not in result.detail
    assert result.status == health.Status.WARN
    assert result.detail.startswith("1/2 covered")
    assert mame.calls == []


def test_led_coverage_check_ignores_legacy_per_system_file(mame):
    _led_cabinet(mame)
    mame.cache_dir.mkdir(parents=True)
    (mame.cache_dir / "MAME.xml").write_bytes(LISTXML)

    result = health.check_led_coverage(mame.cfg)
    assert result.status == health.Status.INFO
    assert "not cached" in result.detail
    assert mame.calls == []


# ─── legacy files, failures ─────────────────────────────────────────────────


def test_legacy_per_system_files_are_left_for_cleanup(mame):
    mame.cache_dir.mkdir(parents=True)
    for legacy in ("MAME.xml", "Neo Geo.xml"):
        (mame.cache_dir / legacy).write_bytes(b"<mame/>")

    ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    assert len(mame.calls) == 1  # the old per-system file is not trusted
    assert (mame.cache_dir / "MAME.xml").read_bytes() == b"<mame/>"

    report = cleanup.scan(mame.cfg, ["listxml-cache"])["listxml-cache"]
    assert sorted(f.path.name for f in report.files) == sorted(
        ["MAME.xml", "Neo Geo.xml", ledblinky.listxml_cache_path(str(mame.exe)).name])


def test_failed_run_is_not_memoized(mame):
    mame.fail = True
    warnings = []
    assert ledblinky.load_listxml_for_system(mame.cfg, "MAME", warnings=warnings) == {}
    assert len(warnings) == 1 and "MAME -listxml failed" in warnings[0]

    mame.fail = False
    assert "pacman" in ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    assert len(mame.calls) == 2


def test_unwritable_cache_still_returns_data_and_leaves_no_temp_file(mame, monkeypatch):
    def refuse(src, dst):
        raise PermissionError("cache file is in use")

    monkeypatch.setattr(ledblinky.os, "replace", refuse)
    info = ledblinky.load_listxml_for_system(mame.cfg, "MAME")
    assert "pacman" in info
    assert _files(mame.cache_dir) == []
