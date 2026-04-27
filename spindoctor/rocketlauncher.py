"""RocketLauncher system INI and HyperSpin Main Menu XML generation."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config, get_rom_extensions, get_systems
from .database import load_database


EMULATOR_MAP: dict[str, str] = {
    "mame": "MAME",
    "arcade": "MAME",
    "cps1": "MAME",
    "cps2": "MAME",
    "cps3": "MAME",
    "neogeo": "MAME",
    "neo geo": "MAME",
    "nes": "RetroArch",
    "nintendo entertainment system": "RetroArch",
    "famicom": "RetroArch",
    "snes": "RetroArch",
    "super nintendo": "RetroArch",
    "super famicom": "RetroArch",
    "genesis": "RetroArch",
    "mega drive": "RetroArch",
    "sega genesis": "RetroArch",
    "n64": "Project64",
    "nintendo 64": "Project64",
    "gba": "RetroArch",
    "game boy advance": "RetroArch",
    "gameboy": "RetroArch",
    "game boy": "RetroArch",
    "game boy color": "RetroArch",
    "gbc": "RetroArch",
    "psx": "RetroArch",
    "playstation": "RetroArch",
    "ps2": "PCSX2",
    "playstation 2": "PCSX2",
    "dreamcast": "Demul",
    "gamecube": "Dolphin",
    "wii": "Dolphin",
    "atari 2600": "RetroArch",
    "atari 7800": "RetroArch",
    "atari lynx": "RetroArch",
    "master system": "RetroArch",
    "sega master system": "RetroArch",
    "game gear": "RetroArch",
    "turbografx": "RetroArch",
    "turbografx-16": "RetroArch",
    "pc engine": "RetroArch",
}


def guess_emulator(system_name: str) -> str:
    return EMULATOR_MAP.get(system_name.lower(), "RetroArch")


# ─── RocketLauncher INI ───────────────────────────────────────────────────────

def generate_rl_system_ini(
    system_name: str,
    config: Config,
    output_base: Optional[Path] = None,
) -> Path:
    """Write a RocketLauncher per-system settings INI file.

    File goes to: <rl_dir|output_base>/Settings/<SystemName>.ini
    """
    rl_base = output_base or (Path(config.rocketlauncher_dir) if config.rocketlauncher_dir else None)
    if not rl_base:
        raise ValueError(
            "rocketlauncher_dir not configured. "
            "Run: spindoctor config set rocketlauncher_dir <path>  "
            "or pass --output-dir."
        )

    settings_dir = rl_base / "Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    ini_path = settings_dir / f"{system_name}.ini"

    rom_path = str(Path(config.roms_dir) / system_name)
    emulator = guess_emulator(system_name)
    extensions = "|".join(ext.lstrip(".") for ext in get_rom_extensions(system_name))

    lines = [
        "[Settings]",
        f"Default_Emulator={emulator}",
        f"Rom_Path={rom_path}",
        f"Rom_Extension={extensions}",
        "",
        f"[{emulator}]",
        f"Rom_Path={rom_path}",
        "",
    ]
    ini_path.write_text("\n".join(lines), encoding="utf-8")
    return ini_path


# ─── HyperSpin Main Menu XML ──────────────────────────────────────────────────

def generate_hs_main_menu(
    systems: list[str],
    config: Config,
    output_base: Optional[Path] = None,
) -> Path:
    """Generate Databases/Main Menu/Main Menu.xml listing all systems."""
    db_base = output_base / "Databases" if output_base else config.databases_dir
    dest_dir = db_base / "Main Menu"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / "Main Menu.xml"

    root = ET.Element("menu")
    hdr = ET.SubElement(root, "header")
    _set(hdr, "listname", "Main Menu")
    _set(hdr, "lastlistupdate", datetime.now().strftime("%Y-%m-%d"))
    _set(hdr, "listversion", "2.0")
    _set(hdr, "exporterversion", "SpinDoctor")

    for sys_name in sorted(systems):
        el = ET.SubElement(root, "game", name=sys_name)
        _set(el, "description", sys_name)
        _set(el, "enabled", "Yes")

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with open(out_path, "wb") as f:
        f.write(b'<?xml version="1.0"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)

    return out_path


# ─── System database stubs ────────────────────────────────────────────────────

def generate_system_db_stubs(
    systems: list[str],
    config: Config,
    output_base: Optional[Path] = None,
) -> list[Path]:
    """Create empty database XMLs for systems that don't have one yet."""
    from .database import HyperspinDatabase

    created = []
    db_base = output_base / "Databases" if output_base else config.databases_dir

    for sys_name in systems:
        xml_path = db_base / sys_name / f"{sys_name}.xml"
        if xml_path.exists():
            continue
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        db = HyperspinDatabase(sys_name, xml_path)
        db.load()
        db.save(backup=False)
        created.append(xml_path)

    return created


# ─── generate all ─────────────────────────────────────────────────────────────

def generate_all(
    config: Config,
    output_base: Optional[Path] = None,
    include_db_stubs: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run all config generation steps and return a results summary dict."""
    systems = get_systems(config)
    results: dict = {
        "systems": systems,
        "dry_run": dry_run,
        "rl_inis": [],
        "hs_main_menu": None,
        "db_stubs": [],
        "errors": [],
    }

    for sys_name in systems:
        if dry_run:
            results["rl_inis"].append(f"[dry-run] {sys_name}.ini")
        else:
            try:
                p = generate_rl_system_ini(sys_name, config, output_base)
                results["rl_inis"].append(str(p))
            except ValueError as e:
                results["errors"].append(str(e))
                results["rl_inis"].append(f"[skipped] {sys_name}")

    if dry_run:
        results["hs_main_menu"] = "[dry-run] Main Menu.xml"
    else:
        p = generate_hs_main_menu(systems, config, output_base)
        results["hs_main_menu"] = str(p)

    if include_db_stubs:
        if dry_run:
            results["db_stubs"] = [f"[dry-run] {s}.xml" for s in systems]
        else:
            created = generate_system_db_stubs(systems, config, output_base)
            results["db_stubs"] = [str(p) for p in created]

    return results


def _set(parent: ET.Element, tag: str, text: str) -> None:
    el = ET.SubElement(parent, tag)
    el.text = text
