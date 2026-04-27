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
    assert "Emulator_Path=" in text


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
