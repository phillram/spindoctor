# build/

Standalone Windows executables for SpinDoctor — for cabinets that can't (or shouldn't) install Python.

## What gets built

Four downloads are produced per release: GUI and CLI, each for Windows 7 and Windows 10/11. Each zip contains exactly one EXE.

### Win7 bundle — `--onefile` (Python 3.8.10 + PyInstaller 5.13.2)

Two independent single-file EXEs in `dist/`. Each embeds the runtime, every command worker, and all bundled deployment media — no shared runtime directory, helper EXEs, or media folder required. Either can be copied anywhere alone.

| Binary | Purpose |
|---|---|
| `spindoctor.exe` | Tkinter GUI (built `--windowed`, no console) |
| `spindoctor-cli.exe` | Full CLI |

The GUI runs commands by relaunching itself with `--run-tool <tool> ARGS...`, where `<tool>` is `spindoctor`, `spindoctor-fav`, `spindoctor-recent`, or `spindoctor-stats`. The console EXE supports the same dispatch, for example `spindoctor.exe --run-tool spindoctor-fav rebuild --apply`. Worker output and exit codes work through pipes and `.bat` files; generated bats use `start "" /B /WAIT` (scheduled refresh/autorun use `start /LOW /B /WAIT ""`).

### Modern bundle — `--onefile` (Python 3.12 + PyInstaller 6.x)

The same two independent EXEs in `dist/spindoctor-win10/`. Recommended for Windows 10/11; PyInstaller 6.x's bootloader requires Windows 8.1+. Both bundles extract to a temporary directory at runtime, as normal for PyInstaller one-file builds.

Separate `spindoctor-fav.exe`, `spindoctor-recent.exe`, and `spindoctor-stats.exe` are no longer shipped. Add `--legacy-tools` to either build command only for old external scripts that still need them. Pip installs continue to provide the three console scripts unchanged.

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
:: Output: dist\spindoctor.exe (GUI), dist\spindoctor-cli.exe (CLI)
```

**Modern build:**
```bat
pip install -e .[all]
pip install -r build/requirements-build-modern.txt
python build/build_windows.py --modern
:: Output: dist\spindoctor-win10\spindoctor.exe, dist\spindoctor-win10\spindoctor-cli.exe
```

Both clean `dist/` and `build/_pyinstaller/` first so each run is reproducible.

## How the build works

Both builds run PyInstaller with `--onefile` once per target. `TARGETS` defines `spindoctor-cli` (`spindoctor._runtime:cli_main`, console) and `spindoctor` (`spindoctor.gui:main`, windowed). A generated shim calls each entry point; no shared-runtime spec is generated.

`HIDDEN_IMPORTS` ensures both EXEs contain the full CLI and all three wheel builders. Both receive every top-level file in `spindoctor/assets` through `iter_bundle_assets()`; subdirectories, including deprecated originals in `assets/archive/`, are never bundled.

Generating the entry-point shims at build time (rather than committing spec files) keeps `build_windows.py` as the single source of truth for entry-points, hidden imports, and asset paths. Adding a new console script is a one-line edit to `TARGETS`.

Validate isolation after building:

```bat
python build/smoke_standalone.py dist
:: Modern: python build/smoke_standalone.py dist\spindoctor-win10
```

The smoke test copies each EXE alone into an empty folder with a stripped `PATH`, then checks version reporting, every worker, exit codes, media installation, `.bat` waiting/exit propagation, and GUI window launch.

### Toolkit wheel art

`spindoctor/assets/toolkit_<key>.png` is the wheel logo for each `install-tools` helper (`spindoctor/toolkit_helpers.py`): 400x156, pink upper-case italic Impact over a blue glow. They're committed, so the builds and SpinDoctor itself need neither Pillow nor the font. After adding a helper, draw its logo on Windows with Pillow installed (add its line break to `LINES` in the script if two balanced lines don't read well):

```bat
python build/make_toolkit_art.py --only <key>
```

`tests/test_toolkit_wheel_art.py` fails until every helper has one. `_MEDIA_PATTERNS` keeps them out of the standalone wheel-builder EXEs.

## Release workflow

`.github/workflows/release.yml` runs on tag push (`v*`) with **two parallel jobs**:

**`build-win7`** — Python 3.8 + PyInstaller 5.x:
1. Spins up `windows-2022` with Python 3.8.10.
2. Installs runtime extras + PyInstaller 5.x (`requirements-build.txt`).
3. Runs `python build/build_windows.py`.
4. Smoke-tests each binary.
5. Packages `spindoctor-gui-win7.zip` and `spindoctor-cli-win7.zip` via `build/package_windows.py` (one EXE per zip).
6. Uploads as a workflow artifact.

**`build-modern`** — Python 3.12 + PyInstaller 6.x:
1. Spins up `windows-2022` with Python 3.12.
2. Installs runtime extras + PyInstaller 6.x (`requirements-build-modern.txt`).
3. Runs `python build/build_windows.py --modern`.
4. Smoke-tests each binary from `dist\spindoctor-win10\`.
5. Packages `spindoctor-gui-win10.zip` and `spindoctor-cli-win10.zip` (one EXE per zip).
6. Uploads as a workflow artifact.

**`publish`** — runs after both builds succeed (tag push only):
1. Downloads both artifacts.
2. Merges SHA256 checksums into a single `SHA256SUMS.txt`.
3. Builds the release notes from `CHANGELOG.md`.
4. Creates the GitHub Release with all four zips + `SHA256SUMS.txt`.

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
