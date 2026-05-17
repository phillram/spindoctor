"""PCLauncher per-game INI generation + Global Emulators integration."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from spindoctor.config import Config
from spindoctor.rocketlauncher import (
    EMULATOR_EXECUTABLES,
    EMULATOR_EXTENSIONS,
    generate_global_emulators_ini,
    generate_pclauncher_inis,
    guess_emulator,
)


def test_pclauncher_in_emulator_dicts():
    assert EMULATOR_EXECUTABLES["PCLauncher"] == "PCLauncher.exe"
    assert "exe" in EMULATOR_EXTENSIONS["PCLauncher"]
    assert "lnk" in EMULATOR_EXTENSIONS["PCLauncher"]
    assert "url" in EMULATOR_EXTENSIONS["PCLauncher"]


@pytest.mark.parametrize("name", [
    "PC", "PC Games", "Windows", "Windows Games", "Steam", "Steam Games",
])
def test_guess_emulator_routes_pc_aliases_to_pclauncher(name):
    assert guess_emulator(name) == "PCLauncher"


def test_global_emulators_ini_includes_pclauncher_block(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
        emulators_dir=str(tmp_path / "emu"),
    )
    p, status = generate_global_emulators_ini(cfg)
    assert status == "created"
    text = p.read_text(encoding="utf-8")
    assert "[PCLauncher]" in text
    assert "PCLauncher.exe" in text
    assert "exe|lnk|url|bat" in text


def test_generate_pclauncher_inis_writes_per_game_files(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    # PureWindowsPath so .parent works on macOS / Linux test runners.
    titles = {
        "Cyberpunk 2077": PureWindowsPath(r"C:\Games\Cyberpunk 2077\bin\launcher.exe"),
        "Hades": PureWindowsPath(r"C:\Games\Hades.lnk"),
    }
    module_dir, written, skipped = generate_pclauncher_inis(
        "PC Games", titles, cfg,
    )
    assert module_dir.name == "PC Games"
    assert module_dir.parent.name == "PCLauncher"
    assert len(written) == 2
    assert skipped == []

    cyber = (module_dir / "Cyberpunk 2077.ini").read_text(encoding="utf-8")
    assert r"ApplicationPath=C:\Games\Cyberpunk 2077\bin\launcher.exe" in cyber
    assert r"StartIn=C:\Games\Cyberpunk 2077\bin" in cyber
    assert "ApplicationParameters=" in cyber

    hades = (module_dir / "Hades.ini").read_text(encoding="utf-8")
    assert r"ApplicationPath=C:\Games\Hades.lnk" in hades


def test_generate_pclauncher_inis_skips_existing_unless_overwrite(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
    )
    titles = {"Hades": Path(r"C:\Games\Hades.lnk")}
    module_dir, written, _ = generate_pclauncher_inis(
        "PC Games", titles, cfg,
    )
    # Mutate the file the user might have customised.
    (module_dir / "Hades.ini").write_text("custom\n", encoding="utf-8")

    _, written2, skipped2 = generate_pclauncher_inis(
        "PC Games", titles, cfg,
    )
    assert written2 == []
    assert len(skipped2) == 1
    assert (module_dir / "Hades.ini").read_text(encoding="utf-8") == "custom\n"

    _, written3, _ = generate_pclauncher_inis(
        "PC Games", titles, cfg, overwrite=True,
    )
    assert len(written3) == 1
    assert "ApplicationPath" in (module_dir / "Hades.ini").read_text(encoding="utf-8")


def test_generate_pclauncher_inis_requires_rocketlauncher_dir(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
    )
    with pytest.raises(ValueError, match="rocketlauncher_dir"):
        generate_pclauncher_inis(
            "PC Games", {"Hades": Path(r"C:\Games\Hades.lnk")}, cfg,
        )
