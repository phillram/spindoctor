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

import fnmatch
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


# Maps each EXE that installs deployment media to the wheel-name suffix used
# in its asset filenames.  None means bundle all media (the full CLI handles
# every wheel).  EXEs absent from this dict get no deployment media.
#
# spindoctor-gui shells out to spindoctor.exe for all media-installing
# operations so it never reads asset files directly.  spindoctor-stats only
# reports playtime and never installs synthetic-wheel assets.
_MEDIA_WHEEL: dict[str, str | None] = {
    "spindoctor":        None,              # all wheels
    "spindoctor-fav":    "Favorites",
    "spindoctor-recent": "Recently_Played",
}

# Glob patterns that identify deployment media vs app assets (icon, etc.).
_MEDIA_PATTERNS: tuple[str, ...] = (
    "bg_*.png",
    "*.mp3",
    "video_*.mp4",
    "wheel_art_*.png",
    "theme_*.zip",
)

# Media filenames shared across all wheels — included in every media-bearing EXE
# regardless of which wheel it manages.  navigate_sound is per-system but the
# same file for all four wheels; theme_blank is used by theme-fill on any wheel.
_SHARED_MEDIA_FILES: frozenset[str] = frozenset({
    "navigate_sound.mp3",
    "theme_blank.zip",
})


def _is_deployment_media(path: Path) -> bool:
    return any(fnmatch.fnmatch(path.name, pat) for pat in _MEDIA_PATTERNS)


def _bundle_asset(path: Path, exe_name: str) -> bool:
    """Return True if *path* should be added to *exe_name*'s bundle.

    Non-media assets (icon.ico, icon.png) are always included.  Deployment
    media is filtered to only the files the EXE actually needs:

    * spindoctor        — all media (full CLI handles every wheel).
    * spindoctor-fav    — Favorites assets + shared files.
    * spindoctor-recent — Recently_Played assets + shared files.
    * spindoctor-gui / spindoctor-stats — no deployment media.
    """
    if not _is_deployment_media(path):
        return True  # icon.ico / icon.png — always bundled
    if exe_name not in _MEDIA_WHEEL:
        return False  # gui / stats: no deployment media
    wheel = _MEDIA_WHEEL[exe_name]
    if wheel is None:
        return True  # full CLI: all media
    return (
        path.name in _SHARED_MEDIA_FILES
        or fnmatch.fnmatch(path.name, f"*_{wheel}.*")
    )


_STANDALONE_NAMES = {"spindoctor-fav", "spindoctor-recent", "spindoctor-stats"}


def iter_bundle_assets(name: str) -> list[Path]:
    """Return the top-level asset files to bundle into *name*'s EXE.

    Single source of truth for both the Win7 (--onefile) and modern
    (--onedir) build paths — the directory-vs-file and per-EXE media
    filtering must apply identically to both, or one build silently
    picks up assets the other excludes (e.g. the assets/archive/
    subfolder, which is a directory and must never be recursed into).
    """
    if not ASSETS_DIR.exists():
        return []
    return [
        asset_file
        for asset_file in sorted(ASSETS_DIR.iterdir())
        if asset_file.is_file() and _bundle_asset(asset_file, name)
    ]


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
    for asset_file in iter_bundle_assets(name):
        cmd += ["--add-data", f"{asset_file}{os.pathsep}spindoctor/assets"]
    for hi in HIDDEN_IMPORTS[name]:
        cmd += ["--hidden-import", hi]
    if name in _STANDALONE_NAMES:
        for ex in _STANDALONE_EXCLUDES:
            cmd += ["--exclude-module", ex]
    cmd.append(str(shim))
    print("$", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def generate_onedir_spec(shims: dict[str, Path]) -> Path:
    """Write a PyInstaller 6.x spec for the shared-runtime --onedir modern build.

    PyInstaller 6.x produces a clean _internal/ subdirectory for the shared
    runtime, which lets COLLECT deduplicate the CPython DLLs and .pyd extensions
    across all five EXEs.  This doesn't work with PyInstaller 5.x (required for
    Win7) because 5.x puts everything flat with no _internal/ separation.

    Returns the path to the written spec file.
    """
    spec_dir = BUILD / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = ["# -*- mode: python ; coding: utf-8 -*-", ""]

    for _entry, name, windowed in TARGETS:
        safe = name.replace("-", "_")
        datas: list[tuple[str, str]] = [
            (asset_file.as_posix(), "spindoctor/assets")
            for asset_file in iter_bundle_assets(name)
        ]
        excludes = _STANDALONE_EXCLUDES if name in _STANDALONE_NAMES else []
        icon_repr = repr(ICON.as_posix()) if ICON.exists() else "None"

        lines += [
            f"a_{safe} = Analysis(",
            f"    [{shims[name].as_posix()!r}],",
            f"    pathex=[],",
            f"    binaries=[],",
            f"    datas={datas!r},",
            f"    hiddenimports={HIDDEN_IMPORTS[name]!r},",
            f"    hookspath=[],",
            f"    hooksconfig={{}},",
            f"    runtime_hooks=[],",
            f"    excludes={excludes!r},",
            f"    noarchive=False,",
            f")",
            f"pyz_{safe} = PYZ(a_{safe}.pure)",
            f"exe_{safe} = EXE(",
            f"    pyz_{safe},",
            f"    a_{safe}.scripts,",
            f"    [],",
            f"    exclude_binaries=True,",
            f"    name={name!r},",
            f"    debug=False,",
            f"    bootloader_ignore_signals=False,",
            f"    strip=False,",
            f"    upx=True,",
            f"    console={repr(not windowed)},",
            f"    disable_windowed_traceback=False,",
            f"    argv_emulation=False,",
            f"    target_arch=None,",
            f"    codesign_identity=None,",
            f"    entitlements_file=None,",
            f"    icon={icon_repr},",
            f")",
            "",
        ]

    # COLLECT merges all five EXEs + their binaries/datas into one output
    # directory.  PyInstaller 6.x deduplicates the shared runtime into _internal/.
    collect_args = []
    for _entry, name, _windowed in TARGETS:
        safe = name.replace("-", "_")
        collect_args += [f"exe_{safe}", f"a_{safe}.binaries", f"a_{safe}.datas"]

    lines += [
        "coll = COLLECT(",
        "    " + ",\n    ".join(collect_args) + ",",
        "    strip=False,",
        "    upx=True,",
        "    upx_exclude=[],",
        "    name='spindoctor-win10',",
        ")",
    ]

    spec = spec_dir / "spindoctor.spec"
    spec.write_text("\n".join(lines) + "\n")
    print(f"Generated spec: {spec}", flush=True)
    return spec


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Build SpinDoctor standalone Windows executables."
    )
    ap.add_argument(
        "--modern",
        action="store_true",
        help=(
            "Build a shared-runtime --onedir bundle for Windows 10/11 "
            "(Python 3.10+ / PyInstaller 6.x).  COLLECT deduplicates the "
            "runtime across all five EXEs into _internal/; "
            "produces dist/spindoctor-win10/."
        ),
    )
    args = ap.parse_args()

    if DIST.exists():
        shutil.rmtree(DIST)
    if BUILD.exists():
        shutil.rmtree(BUILD)
    DIST.mkdir(parents=True, exist_ok=True)

    if args.modern:
        shims = {name: write_shim(entry, name) for entry, name, _ in TARGETS}
        spec = generate_onedir_spec(shims)
        subprocess.check_call([
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--distpath", str(DIST),
            "--workpath", str(BUILD / "work"),
            str(spec),
        ])
        out_dir = DIST / "spindoctor-win10"
        suffix = ".exe" if sys.platform == "win32" else ""
        print("\nBuilt (modern --onedir):")
        for _, name, _ in TARGETS:
            exe = out_dir / f"{name}{suffix}"
            if exe.exists():
                print(f"  {exe.name}  ({exe.stat().st_size // (1024 * 1024)} MB)")
        internal = out_dir / "_internal"
        if internal.exists():
            total = sum(f.stat().st_size for f in internal.rglob("*") if f.is_file())
            print(f"  _internal/  ({total // (1024 * 1024)} MB shared runtime)")
    else:
        for entry, name, windowed in TARGETS:
            shim = write_shim(entry, name)
            run_pyinstaller(shim, name, windowed)

        suffix = ".exe" if sys.platform == "win32" else ""
        print("\nBuilt (--onefile):")
        for _, name, _ in TARGETS:
            exe = DIST / f"{name}{suffix}"
            if exe.exists():
                print(f"  {exe.name}  ({exe.stat().st_size // (1024 * 1024)} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
