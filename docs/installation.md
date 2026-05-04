# Installation

Two ways to install on a Windows cabinet:

1. **Prebuilt binaries** — drop a `.exe` into place, no Python required. Works on Windows 7 SP1 / 8 / 8.1 / 10 / 11. Full walkthrough at [Windows binaries](windows-binaries.md). Quick summary in the [Windows binaries](#windows-binaries-no-python-required) section below.
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

You still need Python and the runtime dependencies. From the repo root:

```bat
pip install click rich requests lxml
```

(Or run `pip install -e .` once to grab everything declared in `pyproject.toml`.)

## Windows binaries (no Python required)

For older / locked-down cabinets where installing Python isn't an option, every release attaches a zip of standalone `.exe` files to its [GitHub Release](https://github.com/phillram/spindoctor/releases).

```
spindoctor-windows-vX.Y.Z.zip
├── spindoctor.exe          ← full CLI
├── spindoctor-fav.exe      ← Favorites wheel manager
├── spindoctor-recent.exe   ← Recently Played rebuild
└── spindoctor-stats.exe    ← playtime reports + Most Played wheel
```

Quick version: download → extract → add to `PATH` → `spindoctor config init`. Runs on Windows 7 SP1 / 8 / 8.1 / 10 / 11.

Full walkthrough with screenshots, troubleshooting (SmartScreen, antivirus, missing SP1), HyperSpin Tools menu wiring, and self-build instructions: [Windows binaries](windows-binaries.md).
