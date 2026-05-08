"""Build standalone Windows executables for SpinDoctor.

Produces five one-file binaries that run on Windows 7 SP1 and newer
when built with Python 3.8 + PyInstaller 5.x:

    dist/spindoctor.exe          ← full CLI (every command)
    dist/spindoctor-gui.exe      ← Tkinter GUI launcher (--windowed)
    dist/spindoctor-fav.exe
    dist/spindoctor-recent.exe
    dist/spindoctor-stats.exe

Usage (locally, on Windows):

    pip install -e .[all]
    pip install -r build/requirements-build.txt
    python build/build_windows.py

The GitHub Actions release workflow runs this on a windows-2022 runner
(windows-2019 was retired) with Python 3.8.10 + PyInstaller 5.x — the
combination that produces a bootloader Windows 7 SP1 still loads.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "_pyinstaller"

# (entry-point module, console-script name, windowed?)
# `windowed=True` builds with `--windowed` (no console window on launch) —
# only used for the Tkinter GUI; the CLIs need `--console` so their stdout
# pipes work when invoked from cmd.exe or by the GUI's subprocess.Popen.
TARGETS = [
    ("spindoctor.cli:cli",            "spindoctor",        False),
    ("spindoctor.gui:main",           "spindoctor-gui",    True),
    ("spindoctor.favorites:main",     "spindoctor-fav",    False),
    ("spindoctor.recent:main",        "spindoctor-recent", False),
    ("spindoctor.playtime:main_cli",  "spindoctor-stats",  False),
]

# Modules PyInstaller's static analysis can miss because they're imported
# lazily or via plugin discovery. Listed here so the bundled exe still works.
HIDDEN_IMPORTS = [
    "spindoctor",
    "spindoctor.cli",
    "spindoctor.favorites",
    "spindoctor.recent",
    "spindoctor.playtime",
    "spindoctor.gui",
    "spindoctor.autostart",
    "spindoctor.update_check",
    "spindoctor.themes",
    "spindoctor.scraper",
    "spindoctor.archives",
    "spindoctor.preview",
    "spindoctor.tools_audit",
    "spindoctor.lightgun",
    "spindoctor.verify",
    "lxml._elementpath",
    "lxml.etree",
    "rich.logging",
    "click",
]


def write_shim(entry: str, name: str) -> Path:
    """Write a tiny `__main__` style shim that calls the package entry point.

    The shim filename must NOT collide with any importable top-level package
    name. The previous version wrote `spindoctor.py` for the main entry point,
    which PyInstaller registered as the bundle's top-level `spindoctor`
    module — shadowing the actual `spindoctor/` package and causing
    `from spindoctor.cli import cli` to resolve to the shim itself, with
    `ModuleNotFoundError: 'spindoctor' is not a package`. Prefixing with
    an underscore puts the shim in a distinct namespace; PyInstaller's
    `--name` argument keeps the produced exe named `spindoctor.exe`.
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
    # `--windowed` suppresses the console window on Windows for GUI binaries.
    # On the CLI binaries `--console` is required so stdout/stderr keep flowing
    # to the parent cmd window (or to the GUI's subprocess.Popen pipes).
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
    for hi in HIDDEN_IMPORTS:
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

    print("\nBuilt:")
    for _, name, _windowed in TARGETS:
        exe = DIST / (f"{name}.exe" if sys.platform == "win32" else name)
        print(f"  {exe}  ({exe.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
