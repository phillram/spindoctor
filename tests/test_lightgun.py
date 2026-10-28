"""Sinden / DemulShooter wiring for lightgun systems."""
from __future__ import annotations

from pathlib import Path

import pytest

from spindoctor.config import Config
from spindoctor.lightgun import (
    DEFAULT_DEMULSHOOTER_ARGS,
    LightgunInstall,
    _upsert_ini_key,
    apply_wire_plan,
    audit_system_wiring,
    detect_lightgun_install,
    detect_lightgun_systems,
    guess_demulshooter_target,
    plan_wire_system,
)


@pytest.fixture(autouse=True)
def _no_system_scan_roots(monkeypatch):
    """Detection also scans Program Files, LocalAppData and the Start Menu;
    keep a lightgun install on the test machine out of these tests."""
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA",
                "APPDATA", "PROGRAMDATA"):
        monkeypatch.delenv(var, raising=False)


def _touch(p: Path, body: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ─── target mapping ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("system, expected", [
    ("MAME", "mame"),
    ("Sega Naomi", "demul07a"),
    ("Sega Atomiswave", "demul07a"),
    ("Sega Model 2", "model2"),
    ("Sega Model 3", "supermodel"),
    ("Flycast", "flycast"),
])
def test_guess_demulshooter_target_known(system, expected):
    assert guess_demulshooter_target(system) == expected


def test_guess_demulshooter_target_unknown_returns_none():
    assert guess_demulshooter_target("Nintendo Entertainment System") is None


# ─── install detection ───────────────────────────────────────────────────────

def test_detect_lightgun_install_finds_demulshooter(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    (tmp_path / "rl" / "Modules" / "DemulShooter").mkdir(parents=True)
    _touch(tmp_path / "rl" / "Modules" / "DemulShooter" / "DemulShooter.exe")

    install = detect_lightgun_install(cfg)
    assert install.has_demulshooter
    assert install.demulshooter_exe.name == "DemulShooter.exe"


def test_detect_lightgun_install_finds_sinden(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    sinden = tmp_path / "hs" / "Tools" / "SindenLightgun"
    _touch(sinden / "Lightgun.exe")
    _touch(sinden / "Lightgun.exe.config")
    install = detect_lightgun_install(cfg)
    assert install.has_sinden
    assert install.sinden_software_dir == sinden


def test_detect_lightgun_install_ignores_folders_merely_named_sinden(tmp_path):
    """A wheel called "Gun Games (Sinden)" puts "sinden" in database and
    media paths; that isn't the Sinden software."""
    cfg = Config(
        roms_dir=str(tmp_path),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    (tmp_path / "hs" / "Databases" / "Gun Games (Sinden)").mkdir(parents=True)
    (tmp_path / "hs" / "Media" / "Gun Games (Sinden)" / "Images").mkdir(parents=True)
    install = detect_lightgun_install(cfg)
    assert not install.has_sinden


def _two_demulshooters(tmp_path):
    exes = []
    for build in ("DemulShooter", "DemulShooter Scripts"):
        exe = tmp_path / "rl" / "Modules" / build / "DemulShooter.exe"
        _touch(exe)
        exes.append(exe)
    cfg = Config(
        roms_dir=str(tmp_path),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    return cfg, exes


def test_detect_lightgun_install_lists_every_demulshooter(tmp_path):
    cfg, exes = _two_demulshooters(tmp_path)
    install = detect_lightgun_install(cfg)
    assert sorted(install.demulshooter_candidates) == sorted(exes)
    assert install.demulshooter_exe in exes
    assert not install.demulshooter_from_config


def test_detect_lightgun_install_applies_demulshooter_path(tmp_path):
    """detect, audit and configure all go through detect_lightgun_install,
    so the configured exe must win there, not only in configure."""
    cfg, exes = _two_demulshooters(tmp_path)
    for chosen in exes:
        cfg.demulshooter_path = str(chosen)
        install = detect_lightgun_install(cfg)
        assert install.demulshooter_exe == chosen
        assert install.demulshooter_from_config


def test_bounded_walk_does_not_descend_past_max_depth(tmp_path, monkeypatch):
    """Filtering what's yielded isn't enough: os.walk itself must stop, or a
    scan of Program Files visits every folder in it."""
    import os

    from spindoctor.lightgun import _bounded_walk

    (tmp_path / "a" / "b" / "c" / "d").mkdir(parents=True)
    walked: list[str] = []
    real_walk = os.walk

    def recording_walk(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            walked.append(Path(dirpath).relative_to(tmp_path).as_posix())
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(os, "walk", recording_walk)
    yielded = {p.relative_to(tmp_path).as_posix() for _d, p in _bounded_walk(tmp_path, max_depth=2)}
    assert yielded == {".", "a", "a/b"}
    assert sorted(walked) == [".", "a", "a/b"]


def test_detect_lightgun_install_ignores_missing_demulshooter_path(tmp_path):
    cfg, exes = _two_demulshooters(tmp_path)
    cfg.demulshooter_path = str(tmp_path / "gone" / "DemulShooter.exe")
    install = detect_lightgun_install(cfg)
    assert install.demulshooter_exe in exes
    assert not install.demulshooter_from_config


# ─── INI scan / per-system audit ─────────────────────────────────────────────

def _wire_ini(rl_dir: Path, system: str, body: str) -> Path:
    settings = rl_dir / "Settings"
    settings.mkdir(parents=True, exist_ok=True)
    p = settings / f"{system}.ini"
    p.write_text(body, encoding="utf-8")
    return p


def test_audit_system_wiring_parses_existing_hooks(tmp_path):
    rl = tmp_path / "rl"
    body = (
        "[Settings]\n"
        "Default_Emulator=MAME\n"
        'Pre_Launch_App="C:\\Tools\\DemulShooter.exe" -target mame -noresize\n'
        'Post_Launch_App=taskkill /IM "DemulShooter.exe" /F\n'
    )
    _wire_ini(rl, "MAME", body)
    cfg = Config(
        roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(rl),
    )
    status = audit_system_wiring("MAME", cfg)
    assert status is not None
    assert status.is_wired
    assert status.target == "mame"
    assert "taskkill" in status.post_launch


def test_audit_system_wiring_missing_ini(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    assert audit_system_wiring("MAME", cfg) is None


def test_detect_lightgun_systems_lists_wired_systems(tmp_path):
    rl = tmp_path / "rl"
    _wire_ini(rl, "MAME",
              "[Settings]\nPre_Launch_App=C:\\T\\DemulShooter.exe -target mame\n")
    _wire_ini(rl, "Sega Naomi",
              "[Settings]\nPre_Launch_App=DemulShooter.exe -target demul07a\n")
    _wire_ini(rl, "Nintendo Entertainment System",
              "[Settings]\nDefault_Emulator=RetroArch\n")
    cfg = Config(
        roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(rl),
    )
    found = detect_lightgun_systems(cfg)
    assert found == ["MAME", "Sega Naomi"]


# ─── plan / apply ────────────────────────────────────────────────────────────

def test_plan_wire_system_writes_target_with_equals(tmp_path):
    """DemulShooter reads -target=<name>; with a space it gets no target."""
    rl = tmp_path / "rl"
    _wire_ini(rl, "MAME", "[Settings]\nDefault_Emulator=MAME\n")
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(rl),
    )
    install = LightgunInstall(
        demulshooter_exe=tmp_path / "tools" / "DemulShooter.exe",
    )
    _touch(install.demulshooter_exe)
    plan = plan_wire_system("MAME", cfg, install)
    assert plan.target == "mame"
    assert not plan.create_ini
    assert "DemulShooter.exe" in plan.pre_launch_command
    assert "-target=mame" in plan.pre_launch_command
    assert "-target mame" not in plan.pre_launch_command
    assert "taskkill" in plan.post_launch_command


def test_plan_wire_system_refuses_system_without_settings(tmp_path):
    """Generating the system's settings just to add two hook keys used to
    rewrite Rom_Path as a side effect."""
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    install = LightgunInstall(demulshooter_exe=tmp_path / "DemulShooter.exe")
    _touch(install.demulshooter_exe)
    with pytest.raises(ValueError, match="No RocketLauncher settings"):
        plan_wire_system("MAME", cfg, install)
    assert not (tmp_path / "rl" / "Settings").exists()


def _folder_layout_cabinet(tmp_path):
    rl = tmp_path / "rl"
    emu_ini = rl / "Settings" / "Sega Naomi" / "Emulators.ini"
    original = (
        "[ROMS]\nDefault_Emulator=Demul\nRom_Path=D:\\Games\\Sega Naomi\n\n"
        "[Demul]\nRom_Extension=zip\n"
    )
    _touch(emu_ini, original)
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(rl),
    )
    install = LightgunInstall(demulshooter_exe=tmp_path / "DemulShooter.exe")
    _touch(install.demulshooter_exe)
    return cfg, install, rl, emu_ini


def test_configure_folder_layout_adds_hooks_to_emulators_ini(tmp_path):
    """Only Settings/<System>/Emulators.ini exists.  apply used to call
    generate_rl_system_ini (rewriting Rom_Path) and then read the missing
    flat Settings/<System>.ini, raising FileNotFoundError."""
    cfg, install, rl, emu_ini = _folder_layout_cabinet(tmp_path)

    plan = plan_wire_system("Sega Naomi", cfg, install)
    assert plan.ini_path == emu_ini
    assert not plan.create_ini
    written = apply_wire_plan(plan, cfg)

    assert written == emu_ini
    body = emu_ini.read_text(encoding="utf-8")
    assert "Rom_Path=D:\\Games\\Sega Naomi" in body  # untouched
    assert "[Demul]\nRom_Extension=zip" in body
    roms = body.split("[Demul]")[0]
    assert "Pre_Launch_App=" in roms and "-target=demul07a" in roms
    assert "Post_Launch_App=" in roms
    assert not (rl / "Settings" / "Sega Naomi.ini").exists()

    status = audit_system_wiring("Sega Naomi", cfg)
    assert status.ini_path == emu_ini
    assert status.target == "demul07a"
    assert detect_lightgun_systems(cfg) == ["Sega Naomi"]


@pytest.mark.parametrize("hook, target", [
    ('"C:\\T\\DemulShooter.exe" -target=demul07a -rom=confmiss -noresize', "demul07a"),
    ("C:\\T\\DemulShooter.exe -target model2 -noresize", "model2"),
])
def test_audit_reads_target_in_either_form(tmp_path, hook, target):
    rl = tmp_path / "rl"
    _wire_ini(rl, "Sega Model 2", f"[Settings]\nPre_Launch_App={hook}\n")
    cfg = Config(roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
                 rocketlauncher_dir=str(rl))
    assert audit_system_wiring("Sega Model 2", cfg).target == target


def test_plan_wire_system_unknown_target_requires_override(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    install = LightgunInstall(
        demulshooter_exe=tmp_path / "DemulShooter.exe",
    )
    _touch(install.demulshooter_exe)
    _wire_ini(tmp_path / "rl", "Nintendo Entertainment System", "[Settings]\n")
    with pytest.raises(ValueError, match="No DemulShooter target"):
        plan_wire_system("Nintendo Entertainment System", cfg, install)
    plan = plan_wire_system(
        "Nintendo Entertainment System", cfg, install,
        target_override="custom_target",
    )
    assert plan.target == "custom_target"


def test_plan_wire_system_detects_existing_replacement(tmp_path):
    rl = tmp_path / "rl"
    body = (
        "[Settings]\n"
        "Pre_Launch_App=C:\\Old\\DemulShooter.exe -target mame -oldarg\n"
        "Post_Launch_App=echo done\n"
    )
    _wire_ini(rl, "MAME", body)
    cfg = Config(
        roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(rl),
    )
    install = LightgunInstall(
        demulshooter_exe=tmp_path / "DemulShooter.exe",
    )
    _touch(install.demulshooter_exe)
    plan = plan_wire_system("MAME", cfg, install)
    assert not plan.create_ini
    assert plan.replace_pre
    assert plan.replace_post


def test_apply_wire_plan_writes_keys_idempotently(tmp_path):
    rl = tmp_path / "rl"
    _wire_ini(rl, "MAME", "[Settings]\nDefault_Emulator=MAME\n")
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(rl),
    )
    install = LightgunInstall(
        demulshooter_exe=tmp_path / "DemulShooter.exe",
    )
    _touch(install.demulshooter_exe)
    plan = plan_wire_system("MAME", cfg, install)
    written = apply_wire_plan(plan, cfg)
    body = written.read_text(encoding="utf-8")
    assert "Pre_Launch_App=" in body
    assert "Post_Launch_App=" in body
    assert "-target=mame" in body
    # Re-running should be idempotent (no duplicate keys).
    apply_wire_plan(plan, cfg)
    body2 = written.read_text(encoding="utf-8")
    assert body2.count("Pre_Launch_App=") == 1
    assert body2.count("Post_Launch_App=") == 1


def test_apply_wire_plan_preserves_unrelated_keys(tmp_path):
    rl = tmp_path / "rl"
    body = (
        "[Settings]\n"
        "Default_Emulator=MAME\n"
        "Rom_Path=C:\\Roms\\MAME\n"
        "Custom_Field=keep me\n"
        "[MAME]\n"
        "Rom_Path=C:\\Roms\\MAME\n"
    )
    _wire_ini(rl, "MAME", body)
    cfg = Config(
        roms_dir=str(tmp_path), hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(rl),
    )
    install = LightgunInstall(
        demulshooter_exe=tmp_path / "DemulShooter.exe",
    )
    _touch(install.demulshooter_exe)
    plan = plan_wire_system("MAME", cfg, install)
    apply_wire_plan(plan, cfg)
    after = (rl / "Settings" / "MAME.ini").read_text(encoding="utf-8")
    assert "Custom_Field=keep me" in after
    assert "[MAME]" in after
    assert "Pre_Launch_App=" in after


def test_default_extra_args_are_sinden_friendly():
    assert "noresize" in DEFAULT_DEMULSHOOTER_ARGS


# ─── _upsert_ini_key direct ───────────────────────────────────────────────────

def test_upsert_inserts_when_missing():
    body = "[Settings]\nA=1\n"
    out = _upsert_ini_key(body, "Settings", "B", "2")
    assert "A=1" in out and "B=2" in out


def test_upsert_replaces_existing():
    body = "[Settings]\nA=1\nB=old\n"
    out = _upsert_ini_key(body, "Settings", "B", "new")
    assert "B=new" in out
    assert "B=old" not in out


def test_upsert_appends_section_when_missing():
    body = "[Other]\nX=1\n"
    out = _upsert_ini_key(body, "Settings", "B", "2")
    assert "[Other]" in out
    assert "[Settings]" in out
    assert "B=2" in out


# ─── config helpers ──────────────────────────────────────────────────────────

def test_lightgun_systems_helpers_round_trip():
    cfg = Config()
    cfg.set_lightgun("MAME", True)
    cfg.set_lightgun("Sega Naomi", True)
    assert cfg.lightgun_systems() == ["MAME", "Sega Naomi"]
    cfg.set_lightgun("MAME", False)
    assert cfg.lightgun_systems() == ["Sega Naomi"]
    # Removing the only flag clears the override entry entirely.
    cfg.set_lightgun("Sega Naomi", False)
    assert cfg.lightgun_systems() == []
    assert "Sega Naomi" not in cfg.system_overrides
