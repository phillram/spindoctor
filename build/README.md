# build/

Standalone Windows executables for SpinDoctor — for cabinets that can't (or shouldn't) install Python.

## What gets built

| Binary | Purpose |
|---|---|
| `spindoctor.exe` | Full CLI |
| `spindoctor-fav.exe` | Favorites wheel manager (boot-trigger friendly) |
| `spindoctor-recent.exe` | Recently Played rebuild |
| `spindoctor-stats.exe` | Playtime reports + Most Played wheel |

Each is a single-file executable produced by [PyInstaller](https://pyinstaller.org/). No installer, no Python on the target box — copy the `.exe` somewhere on `PATH` (or call by full path) and run.

## Windows 7 compatibility

The release workflow builds on `windows-2019` with **Python 3.8.10** and **PyInstaller 5.13.2** because:

- Python 3.8 was the last release to officially support Windows 7 SP1.
- PyInstaller 5.x bootloaders link against the older Windows SDK and load on Win 7. PyInstaller 6.x raised its minimum target to 8.1 and the bootloader fails to load on Win 7 with `api-ms-win-core-path-l1-1-0.dll missing`.

These versions are pinned in `requirements-build.txt` and `.github/workflows/release.yml`. Don't bump them without re-testing on a Win 7 SP1 VM.

The published binaries should run unmodified on Windows 7 SP1 / 8 / 8.1 / 10 / 11. Newer Windows 10/11 builds may issue a SmartScreen warning for unsigned exes — code-signing the release is on the roadmap.

## Building locally (Windows only)

```bat
pip install -e .[all]
pip install -r build/requirements-build.txt
python build/build_windows.py
```

Outputs land in `dist/`. Cleans `dist/` and `build/_pyinstaller/` first so each run is reproducible.

## Why a build script instead of `.spec` files

PyInstaller's `.spec` files are Python scripts evaluated at build time — committing four near-identical specs is more code than the `build_windows.py` driver, and the driver writes one tiny shim per entry-point so the same approach scales to new console scripts in `setup.py` by editing one list.

## Release workflow

`.github/workflows/release.yml` runs on tag push (`v*`) and:

1. Spins up `windows-2019` with Python 3.8.10.
2. Installs runtime extras + PyInstaller.
3. Runs `python build/build_windows.py`.
4. Smoke-tests each `.exe --version`.
5. Zips `dist/` as `spindoctor-windows-<tag>.zip`.
6. Creates a GitHub Release with the tag and attaches the zip.

To cut a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The `v` prefix matters — the workflow filter is `tags: ['v*']`.
