# Windows builds

Each release has four zips: GUI/CLI for Win7 and Win10. Each contains one
independent EXE with runtime, workers and deployment media:

| EXE | Entry point |
|---|---|
| `spindoctor.exe` | `spindoctor.gui:main`, windowed |
| `spindoctor-cli.exe` | `spindoctor._runtime:cli_main`, console |

Both dispatch embedded workers via `--run-tool`. No shared runtime directory
or helper EXEs are required. `--legacy-tools` optionally builds the old
Favorites/Recent/Stats EXEs for external scripts.

## Build and smoke-test

Use Windows and the matching interpreter/toolchain:

```text
python -m pip install -e ".[all]"
python -m pip install -r build/requirements-build.txt
python build/build_windows.py
python build/smoke_standalone.py dist
```

Win7: Python 3.8.10/PyInstaller 5.13.2, output `dist/`.
Modern: Python 3.12/PyInstaller 6.x, install
`build/requirements-build-modern.txt`, build with `--modern`, smoke-test
`dist/spindoctor-win10`. The modern bootloader requires Windows 8.1+.
Do not change Win7 pins without validation on Win7 SP1.

The driver generates shims and invokes one-file PyInstaller per target.
Only top-level active assets are bundled, never `assets/archive`.
Inspect `TARGETS`, `HIDDEN_IMPORTS` and `iter_bundle_assets` when adding workers
or assets. Do not assume a successful Python-source test validates bundling.

The smoke harness copies each EXE alone into an isolated folder with stripped
PATH and checks worker dispatch, exit codes, media, BAT waiting, GUI readiness
and worker cleanup using bounded waits.

## Assets

Toolkit logos are committed `assets/toolkit_<key>.png` files. On Windows with
Pillow and Impact installed, regenerate a helper logo using:

```text
python build/make_toolkit_art.py --only <key>
```

Replace `<key>` with the helper key. `tests/test_toolkit_wheel_art.py` verifies
coverage. Runtime users need neither the drawing font nor Pillow for these logos.

## Release

The tag-triggered `release.yml` builds/smokes both toolchains, packages separate
GUI/CLI zips, combines SHA-256 sums and publishes after both succeed.
`package_windows.py` and `extract_changelog.py` are the packaging/note sources.

Before tagging: update version metadata and the dated CHANGELOG section, verify
`python build/extract_changelog.py vX.Y.Z`, review CI, then follow the project's
release process. A `v`-prefixed tag publishes externally; do not use it as a
local test or bypass failing checks.
