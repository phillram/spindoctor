"""Global Emulators.ini generation tests."""
from __future__ import annotations

from spindoctor.config import Config
from spindoctor.rocketlauncher import generate_global_emulators_ini


def test_creates_ini_with_known_emulators(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
        emulators_dir=str(tmp_path / "emu"),
    )
    p, status = generate_global_emulators_ini(cfg)
    assert status == "created"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "[MAME]" in text
    assert "[RetroArch]" in text
    # Must use Emu_Path= — the key RocketLauncher actually reads.
    assert "Emu_Path=" in text
    # Must NOT use the old wrong key names.
    assert "Emulator_Application_Path=" not in text
    assert "Emulator_Path=" not in text


def test_global_emulators_ini_uses_rl_key_names(tmp_path):
    """Emu_Path and Rom_Extension are the keys RocketLauncher reads.
    Emulator_Application_Path / Emulator_Extension are SpinDoctor inventions
    that RL does not recognise — using them produces the
    'Could not find an Emu_path' error on launch."""
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        rocketlauncher_dir=str(tmp_path / "rl"),
        emulators_dir=str(tmp_path / "emu"),
    )
    p, _ = generate_global_emulators_ini(cfg)
    text = p.read_text(encoding="utf-8")
    assert "Emu_Path=" in text
    assert "Rom_Extension=" in text
    assert "Emulator_Application_Path=" not in text
    assert "Emulator_Extension=" not in text


def test_skips_existing_unless_overwrite(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    p, _ = generate_global_emulators_ini(cfg)
    p.write_text("custom\n", encoding="utf-8")

    p2, status = generate_global_emulators_ini(cfg)
    assert status == "skipped-exists"
    assert p2.read_text(encoding="utf-8") == "custom\n"

    p3, status3 = generate_global_emulators_ini(cfg, overwrite=True)
    assert status3 == "overwritten"
    assert "[MAME]" in p3.read_text(encoding="utf-8")
