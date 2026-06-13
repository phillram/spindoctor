"""Build standalone Windows executables for SpinDoctor.

Produces five self-contained one-file binaries that run on Windows 7 SP1
and newer when built with Python 3.8 + PyInstaller 5.x:

    dist/spindoctor.exe          ← full CLI (every command)
    dist/spindoctor-gui.exe      ← Tkinter GUI launcher (--windowed)
    dist/spindoctor-fav.exe
    dist/spindoctor-recent.exe
    dist/spindoctor-stats.exe

Each is a standalone self-extracting binary — no installer, no DLL hell,
no Python required on the target box. Drop any of them wherever you like.

Usage (locally, on Windows):

    pip install -e .[all]
    pip install -r build/requirements-build.txt
    python build/build_windows.py

The GitHub Actions release workflow runs this on a windows-2022 runner
with Python 3.8.10 + PyInstaller 5.x — the combination that produces a
bootloader Windows 7 SP1 still loads.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "_pyinstaller"
ICON = ROOT / "spindoctor" / "assets" / "icon.ico"
ASSETS_DIR = ROOT / "spindoctor" / "assets"

# (entry-point module:attr, exe name, windowed?)
# windowed=True → --windowed (no console window) — only for the GUI.
TARGETS = [
    ("spindoctor.cli:cli",            "spindoctor",        False),
    ("spindoctor.gui:main",           "spindoctor-gui",    True),
    ("spindoctor.favorites:main",     "spindoctor-fav",    False),
    ("spindoctor.recent:main",        "spindoctor-recent", False),
    ("spindoctor.playtime:main",      "spindoctor-stats",  False),
]

# Hidden imports PyInstaller's static analysis misses because they are
# imported lazily, via plugin discovery, or through C-extension hooks.
# Split per-target so each binary only bundles what it actually uses —
# this keeps the standalone tools (fav/recent/stats) meaningfully smaller
# than the full CLI and GUI.
_CORE: list[str] = [
    "spindoctor",
    "spindoctor.update_check",
    "lxml._elementpath",
    "lxml.etree",
    "rich.logging",
    "click",
]

HIDDEN_IMPORTS: dict[str, list[str]] = {
    "spindoctor": _CORE + [
        "spindoctor.cli",
        "spindoctor.favorites",
        "spindoctor.recent",
        "spindoctor.playtime",
        "spindoctor.autostart",
        "spindoctor.themes",
        "spindoctor.scraper",
        "spindoctor.archives",
        "spindoctor.preview",
        "spindoctor.tools_audit",
        "spindoctor.lightgun",
        "spindoctor.verify",
    ],
    "spindoctor-gui": _CORE + [
        "spindoctor.cli",
        "spindoctor.favorites",
        "spindoctor.recent",
        "spindoctor.playtime",
        "spindoctor.gui",
        "spindoctor.autostart",
        "spindoctor.themes",
        "spindoctor.scraper",
        "spindoctor.archives",
        "spindoctor.preview",
        "spindoctor.tools_audit",
        "spindoctor.lightgun",
        "spindoctor.verify",
        "tkinterdnd2",
    ],
    "spindoctor-fav":    _CORE + ["spindoctor.favorites"],
    "spindoctor-recent": _CORE + ["spindoctor.recent"],
    "spindoctor-stats":  _CORE + ["spindoctor.playtime"],
}


def write_shim(entry: str, name: str) -> Path:
    """Write a tiny __main__-style shim that calls the package entry point.

    The shim filename must NOT collide with any importable top-level package
    name — prefixing with an underscore puts it in a distinct namespace so
    PyInstaller's --name argument keeps the exe named correctly.
    """
    module, attr = entry.split(":")
    shim_dir = BUILD / "shims"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / f"_{name.replace('-', '_')}_entry.py"
    shim.write_text(
        "import sys\n"
        f"from {module} import {attr}\n"
        "if __name__ == '__main__':\n"
        f"    sys.exit({attr}() or 0)\n"
    )
    return shim


def run_pyinstaller(shim: Path, name: str, windowed: bool) -> None:
    mode_flag = "--windowed" if windowed else "--console"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", mode_flag,
        "--name", name,
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD / "specs"),
    ]
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    if ASSETS_DIR.exists():
        # Bundle only the top-level asset files — NOT subdirectories.
        # The archive/ subdir holds deprecated originals kept for reference;
        # it is excluded from pip installs and must also be excluded here
        # so it doesn't bloat every frozen exe.
        for asset_file in sorted(ASSETS_DIR.iterdir()):
            if asset_file.is_file():
                cmd += ["--add-data", f"{asset_file}{os.pathsep}spindoctor/assets"]
    for hi in HIDDEN_IMPORTS[name]:
        cmd += ["--hidden-import", hi]
    cmd.append(str(shim))
    print("$", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    if BUILD.exists():
        shutil.rmtree(BUILD)
    DIST.mkdir(parents=True, exist_ok=True)

    for entry, name, windowed in TARGETS:
        shim = write_shim(entry, name)
        run_pyinstaller(shim, name, windowed)

    suffix = ".exe" if sys.platform == "win32" else ""
    print("\nBuilt:")
    for _, name, _ in TARGETS:
        exe = DIST / f"{name}{suffix}"
        if exe.exists():
            print(f"  {exe.name}  ({exe.stat().st_size // (1024 * 1024)} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
