# Installation

SpinDoctor ships in three forms — pick whichever fits your cabinet:

| Route | Best for | Python required? | Includes GUI? |
|---|---|---|---|
| 🪟 [Prebuilt Windows binaries](windows-binaries.md) | Cabinets where Python isn't an option. Win 7 SP1 / 8 / 8.1 / 10 / 11. | No | Yes — `spindoctor-gui.exe` |
| 🐍 [Pip install from source](#pip-install-from-source) | Dev machines, custom builds, anyone already on Python 3.8+. Cross-platform. | Yes (≥ 3.8) | Yes — `spindoctor-gui` console script |
| 📂 [Source-on-disk, no install](#running-without-pip-install) | Locked-down boxes where Python is available but `pip install` isn't. | Yes (≥ 3.8) | Yes — `python -m spindoctor.gui` |

> Once installed, you can use SpinDoctor through the **GUI launcher** (double-click `spindoctor-gui.exe` or run `spindoctor-gui`) or the **CLI** (`spindoctor …` from `cmd.exe`). They share the same `~/.spindoctor/config.json`, so anything you do in one is visible to the other.

---

## Pip install from source

**Requirements:** Python 3.8+. Windows is the primary target (HyperSpin is a Windows app), but the CLI and GUI both run on macOS and Linux for development and testing.

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

The GUI uses Tkinter, which ships with the standard python.org Windows installer — no extra dependency. On Linux you may need `apt install python3-tk`; on macOS the official Python installer bundles it.

## Verify

```bat
spindoctor --version
spindoctor systems         :: lists configured systems (after `config init`)
spindoctor tools-audit     :: inventory of third-party arcade utilities, read-only
spindoctor-gui --version   :: confirms the GUI binary loads (without opening a window)
```

`tools-audit` is the safest first command on a cabinet — it never touches files, and the report tells you which legacy tools (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Sinden, DemulShooter, …) are now redundant with built-in spindoctor commands. See [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have).

## Console scripts installed

| Command | Purpose |
|---|---|
| `spindoctor` | Full CLI |
| `spindoctor-gui` | Tkinter GUI launcher with 15 tabs: Setup · Wheels · Main Menu · Audit & Doctor · Diagnose · Metadata & Media · Curate · Systems · LEDBlinky · Lightgun · Tools · Backup & Restore · Migrate · Logs (per-run history) · Custom Command. Every tab scrolls vertically when content overflows. File / Help menus add shortcuts to config / logs (with click-to-undo) / HyperSpin theme browser / About / Check for updates. |
| `spindoctor-fav` | Standalone Favorites wheel manager |
| `spindoctor-recent` | Standalone Recently Played rebuild |
| `spindoctor-stats` | Standalone playtime reports + Most Played wheel |

The three standalone wheel scripts are minimal `argparse` wrappers around the same library functions — useful for boot triggers and Tools menu entries because they skip the rich/click overhead. See [Standalone tools](standalone-tools.md).

`spindoctor-gui` shells out to `spindoctor` (and the wheel scripts) under the hood, so anything you can do via a button or form in the window is also available — and identical — on the command line. See [Windows binaries → GUI launcher](windows-binaries.md#gui-launcher) for a tab-by-tab tour (the layout is the same on all platforms).

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
python -m spindoctor.gui                 :: GUI launcher
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
├── spindoctor-gui.exe      ← double-clickable GUI launcher
├── spindoctor-fav.exe      ← Favorites wheel manager
├── spindoctor-recent.exe   ← Recently Played rebuild
└── spindoctor-stats.exe    ← playtime reports + Most Played wheel
```

Quick version: download → extract → either double-click `spindoctor-gui.exe` or open `cmd.exe` and run `spindoctor config init`. Runs on Windows 7 SP1 / 8 / 8.1 / 10 / 11.

Full walkthrough — including a tour of the GUI tabs, troubleshooting (SmartScreen, antivirus, missing SP1), HyperSpin Tools menu wiring, and self-build instructions — at [Windows binaries](windows-binaries.md).
