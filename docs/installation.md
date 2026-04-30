# Installation

Two ways to install on a Windows cabinet:

1. **Prebuilt binaries** — drop a `.exe` into place, no Python required. Works on **Windows 7 SP1 / 8 / 8.1 / 10 / 11**. See [Windows binaries](#windows-binaries-no-python-required) below.
2. **Pip install from source** — needs Python 3.8+ on the box. The route below.

**Requirements (source install):** Python 3.8+. Windows is the primary target (HyperSpin is a Windows app), but the CLI itself runs on macOS and Linux for development and testing.

## Install

```bat
git clone https://github.com/phillram/spindoctor C:\spindoctor
cd C:\spindoctor
pip install -e .[all]
```

`[all]` pulls in every optional extra. If you'd rather pick à-la-carte:

| Extra | Pulls in | What it enables |
|---|---|---|
| `[xml]` | `lxml` | Lossless XML round-trips — preserves comments and attribute order written by HyperHQ. Strongly recommended. |
| `[archives]` | `py7zr`, `rarfile` | `verify` and `find-dupes --by-content` can hash inside `.7z` / `.rar`. `.zip`, `.gz`, and `.chd` are built-in either way. |
| `[preview]` | `Pillow` | `spindoctor preview --format png` builds composited PNG contact sheets. HTML mode works without it. |
| `[all]` | All of the above | Everything in one install. |

```bat
pip install -e .[archives]
pip install -e .[preview]
```

## Verify

```bat
spindoctor --version
spindoctor systems         :: lists configured systems (after `config init`)
spindoctor tools-audit     :: inventory of third-party arcade utilities, read-only
```

`tools-audit` is the safest first command on a cabinet — it never touches files, and the report tells you which legacy tools (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Sinden, DemulShooter, …) are now redundant with built-in spindoctor commands. See [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have).

## Console scripts installed

| Command | Purpose |
|---|---|
| `spindoctor` | Full CLI |
| `spindoctor-fav` | Standalone Favorites wheel manager |
| `spindoctor-recent` | Standalone Recently Played rebuild |
| `spindoctor-stats` | Standalone playtime reports + Most Played wheel |

The three standalone scripts are minimal `argparse` wrappers around the same library functions — useful for boot triggers and Tools menu entries because they skip the rich/click overhead. See [Standalone tools](standalone-tools.md).

Other commonly-used commands that ship only inside the full `spindoctor` CLI (no separate console script):

| Command | Purpose | Read-only? |
|---|---|---|
| `spindoctor tools-audit` | Inventory installed arcade utilities; flags spindoctor replacements | yes |
| `spindoctor find-global "title"` | Search every system's HyperSpin database for a title | yes |
| `spindoctor lightgun detect / audit / configure` | Wire Sinden + DemulShooter into per-system RocketLauncher hooks | `detect`/`audit` read-only; `configure` dry-run by default |

See [Light guns](lightgun.md) for the Sinden / DemulShooter walkthrough.

## Running without `pip install`

If you can't (or don't want to) install the package, the wrappers in `scripts/` work directly from a checkout — they `sys.path.insert` the repo root so `import spindoctor` resolves:

```bat
python C:\spindoctor\scripts\spindoctor-fav.py rebuild --apply
python -m spindoctor.cli systems
```

You still need Python and the runtime dependencies (`pip install -r requirements.txt`).

## Windows binaries (no Python required)

For older / locked-down cabinets where installing Python isn't an option, every release attaches a zip of standalone `.exe` files to its [GitHub Release](https://github.com/phillram/spindoctor/releases).

```
spindoctor-windows-vX.Y.Z.zip
├── spindoctor.exe          ← full CLI
├── spindoctor-fav.exe      ← Favorites wheel manager
├── spindoctor-recent.exe   ← Recently Played rebuild
└── spindoctor-stats.exe    ← playtime reports + Most Played wheel
```

1. Download the zip from the latest release.
2. Extract anywhere — e.g. `C:\spindoctor\`.
3. Either add that folder to `PATH`, or call by full path: `C:\spindoctor\spindoctor.exe systems`.
4. Run `spindoctor config init` once to point at your library.

That's it — no Python, no `pip`, no virtualenv. The four `.bat` files in `scripts/` work unmodified once the `.exe` files are on `PATH`.

### Windows 7 compatibility

Binaries are built with **Python 3.8.10** + **PyInstaller 5.13.2** on a `windows-2019` runner. They run on:

| Windows | Status |
|---|---|
| Windows 7 SP1 (x64) | ✓ Supported |
| Windows 8 / 8.1 | ✓ Supported |
| Windows 10 / 11 | ✓ Supported (may show an unsigned-binary SmartScreen warning — click "More info" → "Run anyway") |

Windows 7 RTM (no service pack) is **not** supported — install SP1 (the standard update from Windows Update) first. Code signing for Windows 10/11 SmartScreen is on the roadmap but not yet implemented.

### Building the binaries yourself

If you want to reproduce or modify the build, see [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md). On a Windows machine with Python 3.8:

```bat
pip install -e .[all]
pip install -r build/requirements-build.txt
python build/build_windows.py
```

Output lands in `dist/`.
