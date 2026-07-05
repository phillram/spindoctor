# SpinDoctor 🩺🕹️

A librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets — a full CLI plus an optional point-and-click GUI for cabinet owners who'd rather not touch `cmd.exe`.

**What it does:**

- **Audits and verifies the library** — compares ROMs against the HyperSpin databases and media, validates ROM integrity against No-Intro / Redump / TOSEC DATs, finds duplicates and misplaced files
- **Fills in metadata and artwork** — downloads game descriptions, wheel art, backgrounds, and videos, and keeps the HyperSpin XML in sync with what's on disk
- **Builds smart wheels** — cross-system Favorites, Recently Played, and Most Played, plus playtime reports
- **Wires up hardware** — Sinden / DemulShooter light guns per system, and LEDBlinky button lighting
- **Protects and moves the library** — dated backups, whole-library migration between drives or PCs, and undo for almost every destructive operation
- **Knows your cabinet** — inventories the third-party arcade tools already installed and reports which ones SpinDoctor replaces

SpinDoctor is a librarian, **not** an installer. It does not install HyperSpin, RocketLauncher, or any emulator, and it does not download ROMs or BIOS. Get those in place, then SpinDoctor automates the rest.

It's also careful by default: commands that modify files preview their plan until re-run with `--apply`, and most destructive commands write an undo manifest. See the [command reference](docs/commands.md) for the full safety model.

## Pick your install route

SpinDoctor ships in three forms — pick whichever matches your cabinet:

| | Best for | What you get | Walkthrough |
|---|---|---|---|
| 🪟 **Prebuilt Windows binaries** | Cabinets where you don't want to install Python | Two bundles: **modern** (Windows 10/11, shared runtime) and **Win7** (Windows 7 SP1 and newer, standalone `.exe` files). Both include a windowed GUI launcher and the full CLI. | [docs/windows-binaries.md](docs/windows-binaries.md) |
| 🐍 **Pip install from source** | Dev machines, custom builds, anyone already running Python 3.8+ | Same CLI plus `spindoctor-gui` console script, importable as a package. Cross-platform (Windows / macOS / Linux). | [docs/installation.md](docs/installation.md) |
| 📂 **Source-on-disk, no install** | Locked-down boxes where `pip install` isn't an option but Python is | The `.py` wrappers in [`scripts/`](scripts/) run directly from a checkout via `python scripts\spindoctor-fav.py …`. | [docs/installation.md#running-without-pip-install](docs/installation.md#running-without-pip-install) |

Then pick how you want to *use* it:

| | When to use it | How to launch |
|---|---|---|
| 🖱️ **GUI launcher** | First-time setup, refreshing wheels, casual use, anyone who'd rather not touch `cmd.exe` | Double-click **`spindoctor-gui.exe`** (binary route) or run **`spindoctor-gui`** (pip route). Full tab tour at [docs/gui.md](docs/gui.md). |
| ⌨️ **CLI** | Every command, scripts, scheduled tasks, advanced workflows | Open `cmd.exe` and run `spindoctor …` — it's a console app, so launch it from a terminal, not by double-clicking `spindoctor.exe` ([why](docs/windows-binaries.md#double-clicking-spindoctorexe-flashes-a-window-that-closes-instantly)). See the [Command reference](docs/commands.md). |

### Five-minute quick start (binaries)

1. Grab the right zip from the [latest release](https://github.com/phillram/spindoctor/releases):
   - **Windows 10/11** → `spindoctor-win10-vX.Y.Z.zip` (shared runtime, recommended)
   - **Windows 7 SP1 / 8 / 8.1 or 10/11** → `spindoctor-win7-vX.Y.Z.zip` (standalone `.exe` files)
2. Extract the zip and move the folder (or EXEs) to a location of your choice (e.g. `C:\spindoctor\`). Optionally add that folder to `PATH` for CLI use. See [docs/windows-binaries.md](docs/windows-binaries.md) for the layout of each bundle.
3. **Double-click `spindoctor-gui.exe`**, fill in the Setup tab (paths + optional scraper credentials), click Save. Done. Prefer to be walked through it? Click **Run first-run wizard…** at the top of that tab ([details](docs/gui.md#first-run-wizard)).

### Five-minute quick start (pip)

```bat
git clone https://github.com/phillram/spindoctor C:\spindoctor
cd C:\spindoctor
pip install -e .[all]
spindoctor-gui                 :: GUI — fills out config.json via the Setup tab
:: ── or ──
spindoctor config init         :: CLI wizard, equivalent
spindoctor systems
spindoctor add-system "Nintendo Entertainment System" --apply
```

For a complete first-time walkthrough on a blank Windows PC (Python, HyperSpin, RocketLauncher, emulators, BIOS, ROMs), see [First-time setup](docs/setup.md).

## What's in the GUI

Dedicated tabs cover the most-used workflows directly, plus a free-form **Console** tab whose preset dropdown covers the full CLI surface — anything in the [CLI cheatsheet](docs/cli-cheatsheet.md) also works as a click from inside the GUI. Tabs appear in new-user journey order; each one links to its section of the [GUI walkthrough](docs/gui.md):

| Tab | Use it to… |
|---|---|
| [Setup](docs/gui.md#setup) | Enter cabinet paths and scraper credentials, test them, and run the first-run wizard |
| [Diagnostics](docs/gui.md#diagnostics) | Check cabinet health and scan the whole library — everything read-only |
| [Systems](docs/gui.md#systems) | Curate HyperSpin's main-menu carousel, add new arcade or PC systems, and teach SpinDoctor about niche systems |
| [Games](docs/gui.md#games) | Manage games within a system — reorder or prune the wheel, rename or clone a game, add newly installed PC games, fix one that launches the wrong program |
| [Metadata & Media](docs/gui.md#metadata--media) | Download game descriptions and artwork — the whole refresh chain in one click, or step by step |
| [Maintenance](docs/gui.md#maintenance) | Thin region/revision duplicates with a per-row preview, and clean up caches |
| [Toolkit](docs/gui.md#toolkit) | Build the Favorites / Recently Played / Most Played wheels and wire them into HyperSpin |
| [LEDBlinky](docs/gui.md#ledblinky) | Generate and tune button-lighting controls and colors |
| [Lightgun](docs/gui.md#lightgun) | Detect light-gun software and wire it up per system |
| [Backup & Restore](docs/gui.md#backup--restore) | Take dated backups of any part of the library, and restore from them |
| [Migration](docs/gui.md#migration) | Move the whole library to a new drive or PC, with undo |
| [Console](docs/gui.md#console) | Run any CLI command from categorized, editable presets |
| [History](docs/gui.md#history) | Review every run this session — dry-run, success, or failure |

The full tour — including the menubar, keyboard shortcuts, find bar, dark mode, and per-tab details — is at [docs/gui.md](docs/gui.md).

## CLI commands

A curated cheatsheet with copy-paste examples for every common workflow lives at **[docs/cli-cheatsheet.md](docs/cli-cheatsheet.md)**. For the full per-command reference with every flag, see **[docs/commands.md](docs/commands.md)**.

A few greatest hits to get oriented:

```bat
spindoctor --help                                :: every command
spindoctor doctor                                :: self-diagnose the cabinet
spindoctor audit --system MAME                   :: compare ROMs vs the HyperSpin DB
spindoctor verify --system NES --dat path\to.dat :: check ROM integrity against a DAT
spindoctor backup create --target E:\Backups --apply   :: dated backup to another drive
spindoctor migrate --target E:\Cab --apply              :: move the whole library
spindoctor fav rebuild --apply && spindoctor recent rebuild --apply && spindoctor stats-report build-wheel --apply   :: rebuild the custom wheels
```

Everything above also works from the GUI's Console tab — every one of these has a matching entry in its preset dropdown.

## Documentation

Start at [docs/index.md](docs/index.md) for a guided table of contents, or skim [CHANGELOG.md](CHANGELOG.md) for what shipped in each release.

**Install & launch**

| | |
|---|---|
| [Windows binaries](docs/windows-binaries.md) | Standalone `.exe` files — no Python required. Includes the GUI launcher. |
| [Installation (pip)](docs/installation.md) | Python install, optional extras, console scripts including `spindoctor-gui`. |
| [First-time setup](docs/setup.md) | Step-by-step from a blank Windows PC to a working cabinet. |
| [Migrating from 1.x](docs/migrating-from-1.x.md) | What changed, what didn't, and how to roll back. |

**Use**

| | |
|---|---|
| [GUI walkthrough](docs/gui.md) | Tab-by-tab tour, first-run wizard, menubar, keyboard shortcuts, dark mode |
| [Configuration](docs/configuration.md) | Config keys, per-system overrides, filesystem considerations |
| [CLI cheatsheet](docs/cli-cheatsheet.md) | Quick "if you want to do X, run Y" copy-paste sampler, grouped by intent |
| [Command reference](docs/commands.md) | Every command, grouped by purpose — including which commands are read-only, dry-run behavior, and `--undo` |
| [Workflows](docs/workflows.md) | First-system add, daily refresh, weekly maintenance, backup, migration, recovery from mistakes |
| [Standalone tools](docs/standalone-tools.md) | Favorites / Recent / Most Played wheels — Tools menu and boot wiring; tools-audit for cataloguing other arcade utilities |
| [Light guns](docs/lightgun.md) | Sinden + DemulShooter wiring per system |
| [Where SpinDoctor stores its files](docs/spindoctor-files.md) | Every file and directory it creates — config, caches, logs, undo manifests |
| [Troubleshooting](docs/troubleshooting.md) | FAQ + common errors |

## Reporting issues

Check [Troubleshooting](docs/troubleshooting.md) first — most scraper, video, and launch problems are covered there. If yours isn't, open an issue at the [project repository](https://github.com/phillram/spindoctor/issues).
