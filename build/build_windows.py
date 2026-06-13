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
#
# _CORE_CLI   — modules needed by every CLI/GUI binary (click, rich).
# _CORE_LXML  — lxml C extensions; needed by CLI/GUI, excluded from
#               standalone tools (database.py uses the stdlib ET fallback
#               when lxml is absent — see _lxml_etree() in database.py).
# _CORE_BASE  — modules needed by ALL five binaries, including the
#               lightweight standalone tools (fav/recent/stats).
#
# The standalone tools use argparse, not click, and do not import rich
# anywhere in their transitive dependency graph. Listing click and rich
# as hidden imports for those targets would force PyInstaller to bundle
# them even though they are never called — so they are kept out of
# _CORE_BASE and only appear in _CORE_CLI.
#
# lxml is imported lazily via _lxml_etree() so PyInstaller's static
# analysis can still detect the import statement. --exclude-module lxml
# (added to _STANDALONE_EXCLUDES) overrides that and prevents bundling.
_CORE_CLI: list[str] = [
    "rich.logging",
    "click",
]

_CORE_LXML: list[str] = [
    "lxml._elementpath",
    "lxml.etree",
]

_CORE_BASE: list[str] = [
    "spindoctor",
    "spindoctor.update_check",
]

# Modules to explicitly exclude from the lightweight standalone tools.
# These are not imported anywhere in the fav/recent/stats transitive graph
# but may be picked up by PyInstaller's stdlib sweep or leftover .pyc files
# in the build environment.  lxml is excluded here because database.py
# imports it lazily (PyInstaller still detects the import statement inside
# _lxml_etree()) — the exclude ensures the standalone EXEs use the stdlib
# ET fallback path instead.
_STANDALONE_EXCLUDES: list[str] = [
    "lxml",
    "click",
    "rich",
    "tkinter",
    "_tkinter",
    "PIL",
    "tkinterdnd2",
]

HIDDEN_IMPORTS: dict[str, list[str]] = {
    "spindoctor": _CORE_BASE + _CORE_CLI + _CORE_LXML + [
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
    "spindoctor-gui": _CORE_BASE + _CORE_CLI + _CORE_LXML + [
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
    "spindoctor-fav":    _CORE_BASE + ["spindoctor.favorites"],
    "spindoctor-recent": _CORE_BASE + ["spindoctor.recent"],
    "spindoctor-stats":  _CORE_BASE + ["spindoctor.playtime"],
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


_STANDALONE_NAMES = {"spindoctor-fav", "spindoctor-recent", "spindoctor-stats"}


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
    if name in _STANDALONE_NAMES:
        for ex in _STANDALONE_EXCLUDES:
            cmd += ["--exclude-module", ex]
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
