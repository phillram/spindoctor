# build/

Standalone Windows executables for SpinDoctor — for cabinets that can't (or shouldn't) install Python.

## What gets built

Two bundles are produced per release:

### Win7 bundle — `--onefile` (Python 3.8 + PyInstaller 5.x)

Five self-contained EXEs in `dist/`. Each is a standalone self-extracting archive — no shared runtime, no sibling files required. Drop them wherever you like.

| Binary | Purpose |
|---|---|
| `spindoctor.exe` | Full CLI |
| `spindoctor-gui.exe` | Tkinter GUI launcher (built `--windowed`, no console) |
| `spindoctor-fav.exe` | Favorites wheel manager (boot-trigger friendly) |
| `spindoctor-recent.exe` | Recently Played rebuild |
| `spindoctor-stats.exe` | Playtime reports + Most Played wheel |

`spindoctor-gui.exe` finds its sibling EXEs via `Path(sys.executable).parent`, so keep all five in the same directory for GUI use.

### Modern bundle — `--onedir` COLLECT (Python 3.12 + PyInstaller 6.x)

One `spindoctor-win10/` folder in `dist/`. The Python 3.12 runtime lives once in `_internal/`; PyInstaller's COLLECT deduplicates it across all five EXEs — significantly smaller than five separate `--onefile` EXEs each embedding their own copy. Windows 10/11 only; PyInstaller 6.x bootloader requires Windows 8.1+.

Hidden imports are split per-target so each EXE only bundles what it actually uses:

- `_CORE_BASE` — shared by all five binaries: the spindoctor package itself and `update_check`.
- `_CORE_CLI` — `click` and `rich`, used only by the full CLI and GUI binaries.
- `_CORE_LXML` — `lxml` C extensions, used only by the full CLI and GUI binaries. The standalone tools use `database.py`'s stdlib `xml.etree.ElementTree` fallback when lxml is absent — `lxml` is imported lazily via `_lxml_etree()` and `--exclude-module lxml` (in `_STANDALONE_EXCLUDES`) prevents bundling even though the import statement is visible to static analysis.

`_STANDALONE_EXCLUDES` passes `--exclude-module` for `lxml`, `click`, `rich`, `tkinter`, and `PIL` so PyInstaller's stdlib sweep and any `.pyc` files in the build environment can't pull them back in.

The tradeoff for the standalone tools: XML comment round-tripping is not preserved (lxml preserves comments and attribute order; the stdlib fallback does not). HyperSpin XML files written by the standalone tools are valid and HyperSpin reads them correctly — comments are not present in those files in practice.

## Windows 7 compatibility

The Win7 build uses **Python 3.8.10** and **PyInstaller 5.13.2** (pinned in `requirements-build.txt`) because:

- Python 3.8 was the last release to officially support Windows 7 SP1.
- PyInstaller 5.x bootloaders link against the older Windows SDK and load on Win 7. PyInstaller 6.x raised its minimum target to 8.1 and the bootloader fails to load on Win 7 with `api-ms-win-core-path-l1-1-0.dll missing`.

Don't bump these without re-testing on a Win 7 SP1 VM.

The modern build (`requirements-build-modern.txt`) uses **Python 3.12 + PyInstaller ≥ 6.0**. Its bootloader requires Windows 8.1+ — it will not run on Windows 7 regardless of SP level.

## Building locally (Windows only)

**Win7 build:**
```bat
pip install -e .[all]
pip install -r build/requirements-build.txt
python build/build_windows.py
:: Output: dist\spindoctor.exe, dist\spindoctor-gui.exe, ...
```

**Modern build:**
```bat
pip install -e .[all]
pip install -r build/requirements-build-modern.txt
python build/build_windows.py --modern
:: Output: dist\spindoctor-win10\spindoctor.exe, ..., dist\spindoctor-win10\_internal\
```

Both clean `dist/` and `build/_pyinstaller/` first so each run is reproducible.

## How the build works

**Win7 (`--onefile`):** `build_windows.py` runs PyInstaller five times — once per target. A tiny shim script per target calls the package entry point; PyInstaller wraps that shim plus all its imports into a single self-extracting EXE.

**Modern (`--onedir` via `--modern`):** `build_windows.py` generates a PyInstaller 6.x spec file with five `Analysis` + `EXE` objects and one `COLLECT`. PyInstaller runs once; the COLLECT deduplicates the shared runtime into `_internal/`.

Hidden imports and asset routing are defined per-target in `HIDDEN_IMPORTS` and `_MEDIA_WHEEL`. Both build paths list assets to bundle through the same `iter_bundle_assets()` — it excludes subdirectories (`spindoctor/assets/archive/` is ~129 MB of deprecated originals that must never be bundled) and then filters deployment media per-EXE via `_bundle_asset()`:

- `spindoctor` — all four wheels' media (full CLI handles every wheel).
- `spindoctor-fav` — Favorites assets only (`*_Favorites.*`) + shared files (`navigate_sound.mp3`, `theme_blank.zip`).
- `spindoctor-recent` — Recently Played assets only (`*_Recently_Played.*`) + shared files.
- `spindoctor-gui` / `spindoctor-stats` — no deployment media. The GUI never reads asset files directly — it delegates every operation to a sibling binary (`spindoctor.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, or `spindoctor-stats.exe`), which carry the media they need. `spindoctor-stats` rebuilds the Most Played wheel XML but never installs synthetic-wheel media.

Generating the entry-point shims at build time (rather than committing spec files) keeps `build_windows.py` as the single source of truth for entry-points, hidden imports, and asset paths. Adding a new console script is a one-line edit to `TARGETS`.

## Release workflow

`.github/workflows/release.yml` runs on tag push (`v*`) with **two parallel jobs**:

**`build-win7`** — Python 3.8 + PyInstaller 5.x:
1. Spins up `windows-2022` with Python 3.8.10.
2. Installs runtime extras + PyInstaller 5.x (`requirements-build.txt`).
3. Runs `python build/build_windows.py`.
4. Smoke-tests each binary.
5. Packages as `spindoctor-win7-<tag>.zip` (five flat EXEs).
6. Uploads as a workflow artifact.

**`build-modern`** — Python 3.12 + PyInstaller 6.x:
1. Spins up `windows-2022` with Python 3.12.
2. Installs runtime extras + PyInstaller 6.x (`requirements-build-modern.txt`).
3. Runs `python build/build_windows.py --modern`.
4. Smoke-tests each binary from `dist\spindoctor-win10\`.
5. Packages as `spindoctor-win10-<tag>.zip` (the whole `spindoctor-win10/` folder).
6. Uploads as a workflow artifact.

**`publish`** — runs after both builds succeed (tag push only):
1. Downloads both artifacts.
2. Merges SHA256 checksums into a single `SHA256SUMS.txt`.
3. Builds the release notes from `CHANGELOG.md`.
4. Creates the GitHub Release with both zips + `SHA256SUMS.txt`.

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
