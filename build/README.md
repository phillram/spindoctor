# build/

Standalone Windows executables for SpinDoctor — for cabinets that can't (or shouldn't) install Python.

## What gets built

Five self-contained `--onefile` EXEs in `dist/`:

| Binary | Purpose |
|---|---|
| `spindoctor.exe` | Full CLI |
| `spindoctor-gui.exe` | Tkinter GUI launcher (built `--windowed`, no console) |
| `spindoctor-fav.exe` | Favorites wheel manager (boot-trigger friendly) |
| `spindoctor-recent.exe` | Recently Played rebuild |
| `spindoctor-stats.exe` | Playtime reports + Most Played wheel |

Each binary is a self-extracting archive — no installer, no shared runtime folder, no Python on the target box. Drop any of them wherever you like. `spindoctor-gui.exe` finds its sibling EXEs via `Path(sys.executable).parent`, so keep all five in the same directory for GUI use.

Hidden imports are split per-target as a hygiene measure — each EXE's explicit import list covers only what that binary directly needs. However, EXE sizes remain similar across all five because `HIDDEN_IMPORTS` only adds modules that static analysis misses; it cannot exclude modules pulled in transitively through shared spindoctor package imports. Each binary also pays the full Python 3.8 runtime cost. To meaningfully reduce standalone-tool sizes would require `--exclude-module` flags plus auditing that the shared package code doesn't transitively import GUI or CLI modules from `favorites.py`, `recent.py`, and `playtime.py`.

## Windows 7 compatibility

The release workflow builds on `windows-2022` with **Python 3.8.10** and **PyInstaller 5.13.2** because:

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

Output lands in `dist/`. Cleans `dist/` and `build/_pyinstaller/` first so each run is reproducible.

## How the build works

`build_windows.py` runs PyInstaller five times — once per target — each in `--onefile` mode. A tiny shim script per target calls the package entry point; PyInstaller wraps that shim plus all its imports into a single self-extracting EXE.

Hidden imports are defined per-target in the `HIDDEN_IMPORTS` dict. This keeps each binary lean: `spindoctor-fav.exe` only bundles core + `spindoctor.favorites`; `spindoctor.exe` bundles the full CLI surface; `spindoctor-gui.exe` adds Tkinter, Pillow, and tkinterdnd2 on top.

Generating the entry-point shims at build time (rather than committing spec files) keeps `build_windows.py` as the single source of truth for entry-points, hidden imports, and asset paths. Adding a new console script is a one-line edit to `TARGETS`.

## Release workflow

`.github/workflows/release.yml` runs on tag push (`v*`) and:

1. Spins up `windows-2022` with Python 3.8.10.
2. Installs runtime extras + PyInstaller.
3. Runs `python build/build_windows.py`.
4. Smoke-tests each CLI `.exe` (the GUI exe is `--windowed` so cmd can't observe its exit code; the workflow checks the file exists and exercises `python -m spindoctor.gui --version` against the source instead).
5. Zips all five flat EXEs from `dist/` as `spindoctor-windows-<tag>.zip`.
6. Creates a GitHub Release with the tag and attaches the zip.

### Cutting a release

1. **Update `CHANGELOG.md`** on `main`. Add a new `## [X.Y.Z] - YYYY-MM-DD` section with the changes; keep the [Keep a Changelog](https://keepachangelog.com/) categories (`Added` / `Changed` / `Fixed` / `Removed` / `Deprecated` / `Security`). Add the matching link reference at the bottom: `[X.Y.Z]: https://github.com/phillram/spindoctor/releases/tag/vX.Y.Z`.
2. **Verify the section parses**:
   ```bash
   python build/extract_changelog.py vX.Y.Z | head -20
   ```
   Non-zero exit means the workflow won't be able to build the release body — fix the heading first.
3. **Tag with an annotated message** (lightweight tags carry no metadata):
   ```bash
   git checkout main && git pull
   git tag -a vX.Y.Z -m "SpinDoctor X.Y.Z"
   git push origin vX.Y.Z
   ```
4. The `release.yml` workflow then builds the binaries, extracts the matching CHANGELOG section as the release body, and publishes a GitHub Release. GitHub's `generate_release_notes` appends a "What's Changed" PR list underneath.

The `v` prefix matters — the workflow filter is `tags: ['v*']` and `extract_changelog.py` strips it before matching the heading.
