"""Build independent one-file Windows GUI and CLI executables.

Both Windows targets embed their runtime, workers and deployment media.
--modern selects the Python 3.12/PyInstaller 6 output directory, not an
external shared runtime. The default toolchain remains Python 3.8/PyInstaller
5 for Windows 7 SP1. No output-directory cleanup is performed here.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "_pyinstaller"
ICON = ROOT / "spindoctor" / "assets" / "icon.ico"
ASSETS_DIR = ROOT / "spindoctor" / "assets"

# (entry point, executable name, windowed?)
TARGETS = [
    ("spindoctor._runtime:cli_main", "spindoctor-cli", False),
    ("spindoctor.gui:main", "spindoctor", True),
]
# Optional compatibility outputs for existing external scripts. Neither the
# GUI nor CLI requires these. New generated tasks invoke embedded workers.
LEGACY_TARGETS = [
    ("spindoctor.favorites:main", "spindoctor-fav", False),
    ("spindoctor.recent:main", "spindoctor-recent", False),
    ("spindoctor.playtime:main", "spindoctor-stats", False),
]

_CORE_BASE = ["spindoctor", "spindoctor.update_check"]
_CORE_CLI = _CORE_BASE + [
    "spindoctor._runtime", "spindoctor.cli", "spindoctor.favorites",
    "spindoctor.recent", "spindoctor.playtime", "rich.logging",
    "lxml._elementpath", "lxml.etree", "PIL.Image", "py7zr", "rarfile",
]
HIDDEN_IMPORTS = {
    "spindoctor-cli": _CORE_CLI,
    "spindoctor": _CORE_CLI + ["spindoctor.gui", "tkinterdnd2"],
    "spindoctor-fav": _CORE_BASE + ["spindoctor.favorites"],
    "spindoctor-recent": _CORE_BASE + ["spindoctor.recent"],
    "spindoctor-stats": _CORE_BASE + ["spindoctor.playtime"],
}
_STANDALONE_NAMES = {name for _, name, _ in LEGACY_TARGETS}
_STANDALONE_EXCLUDES = ["lxml", "click", "rich", "tkinter", "_tkinter", "PIL", "tkinterdnd2"]

_MEDIA_WHEEL = {
    "spindoctor-cli": None,
    "spindoctor": None,
    "spindoctor-fav": "Favorites",
    "spindoctor-recent": "Recently_Played",
    "spindoctor-stats": "Most_Played",
}
_MEDIA_PATTERNS = ("bg_*.png", "*.mp3", "video_*.mp4", "wheel_art_*.png", "theme_*.zip")
_SHARED_MEDIA_FILES = frozenset({"navigate_sound.mp3", "theme_blank.zip"})


def write_shim(entry: str, name: str) -> Path:
    """Use a distinct shim filename so it cannot shadow the package."""
    module, attr = entry.split(":")
    shim_dir = BUILD / "shims"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / f"_{name.replace('-', '_')}_entry.py"
    shim.write_text(
        "import sys\n"
        f"from {module} import {attr}\n"
        "if __name__ == '__main__':\n"
        f"    sys.exit({attr}() or 0)\n",
        encoding="utf-8",
    )
    return shim


def _is_deployment_media(path: Path) -> bool:
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in _MEDIA_PATTERNS)


def _bundle_asset(path: Path, exe_name: str) -> bool:
    if not _is_deployment_media(path):
        return True
    if exe_name not in _MEDIA_WHEEL:
        return False
    wheel = _MEDIA_WHEEL[exe_name]
    return wheel is None or path.name in _SHARED_MEDIA_FILES or fnmatch.fnmatch(path.name, f"*_{wheel}.*")


def iter_bundle_assets(name: str) -> list[Path]:
    """Only top-level files: never recurse into deprecated assets/archive/."""
    if not ASSETS_DIR.exists():
        return []
    return [
        path for path in sorted(ASSETS_DIR.iterdir())
        if path.is_file() and _bundle_asset(path, name)
    ]


def run_pyinstaller(shim: Path, name: str, windowed: bool, *, out_dir: Path = None) -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--windowed" if windowed else "--console", "--name", name,
        "--paths", str(ROOT), "--distpath", str(out_dir or DIST),
        "--workpath", str(BUILD / "work"), "--specpath", str(BUILD / "specs"),
    ]
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    for asset in iter_bundle_assets(name):
        cmd += ["--add-data", f"{asset}{os.pathsep}spindoctor/assets"]
    for module in HIDDEN_IMPORTS[name]:
        cmd += ["--hidden-import", module]
    if name in _STANDALONE_NAMES:
        for module in _STANDALONE_EXCLUDES:
            cmd += ["--exclude-module", module]
    cmd.append(str(shim))
    print("$", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build independent one-file SpinDoctor GUI and CLI executables.")
    parser.add_argument(
        "--modern", action="store_true",
        help="Use the modern output directory (dist/spindoctor-win10/); still builds one-file EXEs.",
    )
    parser.add_argument(
        "--legacy-tools", action="store_true",
        help="Also build the optional fav/recent/stats compatibility EXEs. The GUI and CLI do not need them.",
    )
    args = parser.parse_args()
    out_dir = DIST / "spindoctor-win10" if args.modern else DIST
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = TARGETS + LEGACY_TARGETS if args.legacy_tools else TARGETS
    for entry, name, windowed in targets:
        run_pyinstaller(write_shim(entry, name), name, windowed, out_dir=out_dir)
    print("\nBuilt independent one-file executables:")
    suffix = ".exe" if sys.platform == "win32" else ""
    for _, name, _ in targets:
        exe = out_dir / f"{name}{suffix}"
        if exe.exists():
            print(f"  {exe} ({exe.stat().st_size / (1024 * 1024):.1f} MiB)")
    print("Each EXE works alone. No sibling executables, runtime or media folders are required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
