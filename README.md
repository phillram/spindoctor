# SpinDoctor 🩺🕹️

A librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets — full CLI plus an optional Tkinter GUI launcher for cabinet owners who'd rather not touch `cmd.exe`. Audits ROMs, syncs HyperSpin XML, fetches metadata and media, validates ROM integrity against No-Intro / Redump / TOSEC DATs, manages cross-system Favorites / Recently Played / Most Played wheels, reports on playtime, wires Sinden / DemulShooter for light-gun systems, inventories the third-party tools already installed on your cabinet, and migrates the whole library between drives or PCs.

SpinDoctor is a librarian, **not** an installer. It does not install HyperSpin, RocketLauncher, or any emulator, and it does not download ROMs or BIOS. Get those in place, then SpinDoctor automates the rest.

> **Dry-run by default.** Commands that modify files preview their plan unless invoked with `--apply`. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `verify`, `check-discs`, `stats`, `doctor`, `tools-audit`, `find-global`, `lightgun detect`, `lightgun audit`, `theme-scan`) need no flag. Most destructive commands also write a manifest under `~/.spindoctor/` and accept `--undo` to roll back.

## Pick your install route

SpinDoctor ships in three forms — pick whichever matches your cabinet:

| | Best for | What you get | Walkthrough |
|---|---|---|---|
| 🪟 **Prebuilt Windows binaries** | Cabinets where you don't want to install Python | Five `.exe` files including a windowed GUI launcher and the full CLI. Runs on Windows 7 SP1 / 8 / 8.1 / 10 / 11. | [docs/windows-binaries.md](docs/windows-binaries.md) |
| 🐍 **Pip install from source** | Dev machines, custom builds, anyone already running Python 3.8+ | Same CLI plus `spindoctor-gui` console script, importable as a package. Cross-platform (Windows / macOS / Linux). | [docs/installation.md](docs/installation.md) |
| 📂 **Source-on-disk, no install** | Locked-down boxes where `pip install` isn't an option but Python is | The `.py` wrappers in [`scripts/`](scripts/) run directly from a checkout via `python scripts\spindoctor-fav.py …`. | [docs/installation.md#running-without-pip-install](docs/installation.md#running-without-pip-install) |

Then pick how you want to *use* it:

| | When to use it | How to launch |
|---|---|---|
| 🖱️ **GUI launcher** | First-time setup, refreshing wheels, casual use, anyone who'd rather not touch `cmd.exe` | Double-click **`spindoctor-gui.exe`** (binary route) or run **`spindoctor-gui`** (pip route). See [docs/windows-binaries.md#gui-launcher](docs/windows-binaries.md#gui-launcher). |
| ⌨️ **CLI** | Every command, scripts, scheduled tasks, advanced workflows | Open `cmd.exe` and run `spindoctor …`. See the [Command reference](docs/commands.md). |

> **Don't double-click `spindoctor.exe` from File Explorer.** It's a command-line tool — with no arguments it prints `--help` and exits, so the cmd window flashes open and closes again before you can read it. Use `spindoctor-gui.exe` for double-click launching, or open `cmd.exe` first and run `spindoctor` from there. ([more](docs/windows-binaries.md#double-clicking-spindoctorexe-flashes-a-window-that-closes-instantly))

### Five-minute quick start (binaries)

1. Grab `spindoctor-windows-vX.Y.Z.zip` from the [latest release](https://github.com/phillram/spindoctor/releases).
2. Extract to e.g. `C:\spindoctor\`. Optionally add the folder to `PATH` for CLI use.
3. **Double-click `spindoctor-gui.exe`**, fill in the Setup tab (paths + optional scraper credentials), click Save. Done.

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

For a complete first-time walkthrough on a blank Windows PC (Python, HyperSpin, RocketLauncher, emulators, BIOS, ROMs), see [docs/setup.md](docs/setup.md).

## Documentation

**Install & launch**

| | |
|---|---|
| [Windows binaries](docs/windows-binaries.md) | Standalone `.exe` files — no Python required. Includes the GUI launcher. |
| [Installation (pip)](docs/installation.md) | Python install, optional extras, console scripts including `spindoctor-gui`. |
| [First-time setup](docs/setup.md) | Step-by-step from a blank Windows PC to a working cabinet. |

**Use**

| | |
|---|---|
| [Configuration](docs/configuration.md) | Config keys, per-system overrides, filesystem considerations |
| [Command reference](docs/commands.md) | Every command, grouped by purpose |
| [Workflows](docs/workflows.md) | First-system add, daily refresh, weekly maintenance, backup, migration, recovery |
| [Standalone tools](docs/standalone-tools.md) | Favorites / Recent / Most Played wheels — Tools menu and boot wiring; tools-audit for cataloguing other arcade utilities |
| [Light guns](docs/lightgun.md) | Sinden + DemulShooter wiring per system |
| [Troubleshooting](docs/troubleshooting.md) | FAQ + common errors |

Start at [docs/index.md](docs/index.md) for a guided table of contents, or skim [CHANGELOG.md](CHANGELOG.md) for what shipped in each release.

## Common starting points

First-time launch opens a guided 3-step wizard (Welcome → pick `roms_dir` + `hyperspin_dir` → run `doctor` and read the results) so a brand-new cabinet owner has something to click instead of staring at 15 tabs full of "setup incomplete" status bars. The wizard self-dismisses for existing installs whose config is already valid; you can re-open it any time via **Help → First-run setup…**.

The CLI commands below — `tools-audit`, `doctor`, `audit`, the wheel refreshes, and any other `spindoctor …` invocation — also work from the GUI's Custom Command tab (whose dropdown ships ~70 canonical commands) if you'd rather click than type. The 15 dedicated GUI tabs cover the most-used workflows directly: **Setup** (paths + scraper credentials — ScreenScraper and TheGamesDB keys, masked with a Show/Hide eyeball toggle and a "Test credentials" button that pings both providers and reports pass/fail), **Wheels** (checkboxes for Favorites / Recently Played / Most Played + a "Refresh selected" button that chains only the ticked ones, with step-counter progress in the status bar; HyperSpin integration helpers below), **Main Menu** (interactive Treeview showing the live system order — select a row, click Move Up / Move Down / Toggle Visible, then Save Order with a confirmation dialog before writing `Main Menu.xml`), **Audit & Doctor**, **Diagnose** (find-dupes, find-misplaced, find-orphan-media, check-discs, lint, report, verify-against-DAT, global search), **Metadata & Media** (fetch-meta, fetch-media with media-type checkboxes, media-scan, update-db, generate-config; "Full metadata refresh" chains all three with step-counter status), **Curate** (region/revision thinning with an interactive `☑/☐` per-row preview, per-category cleanup checkboxes with safe caches pre-ticked and unsafe caches unchecked, ignore lifecycle with click-to-un-ignore viewer), **Systems** (add-system, add-pc-system, pc-rename), **LEDBlinky**, **Lightgun**, **Tools** (Tools-menu helpers + Windows auto-refresh on log-on), **Backup & Restore** (Scan button populates restore dropdown from configured backup folder), **Migrate** (multi-select Listbox for systems filter, undo manifest dropdown pre-populated from `~/.spindoctor/migrations/`), **Logs** (per-run timeline tagging each row DRY-RUN / OK / FAIL), **Custom Command**. Every tab scrolls when content overflows the window. Every text input has a right-click Cut / Copy / Paste / Select-All menu. `View` exposes a UI-scale knob (0.8×–1.5×, plus `Ctrl++` / `Ctrl+-` / `Ctrl+0`) and a collapsible Output panel (`Ctrl+`` `), so cabinet owners on 1280×720 can fit a full tab on screen without scrolling. A `File` menu adds shortcuts to `config.json` / `~/.spindoctor` / a Logs & Manifests viewer (with one-click "Undo this run" for any apply-mode command) / a HyperSpin theme browser; a `Help` menu surfaces an About dialog and a "Check for updates" action that pings GitHub for newer releases.

| If you want to… | Run |
|---|---|
| See every command and what it does | `spindoctor --help` |
| Inventory the tools already on this cabinet | `spindoctor tools-audit` |
| Self-diagnose paths, binaries, and DB integrity | `spindoctor doctor` |
| Audit one system's ROMs vs. the HyperSpin DB | `spindoctor audit --system MAME` |
| Verify ROM integrity against a No-Intro / Redump DAT | `spindoctor verify --system NES --dat path\to.dat` |
| Find a game across every system | `spindoctor find-global "house of the dead"` |
| Edit metadata across many games at once | `spindoctor batch-edit --system MAME --filter genre=Action --set rating=5 --apply` |
| Wire a Sinden lightgun for a system | `spindoctor lightgun configure --system "Sega Naomi" --apply` |
| Refresh Favorites / Recently Played / Most Played | `spindoctor-fav rebuild --apply && spindoctor-recent rebuild --apply && spindoctor-stats build-wheel --apply` |
| Snapshot the library before risky work | `spindoctor backup create --target E:\Backups --apply` |
| See what changed since a backup | `spindoctor diff E:\Backups\spindoctor-backup-20260101_120000` |
| Migrate to a new drive | `spindoctor migrate --target E:\Cab --apply` |
| Inventory frontend controller-glyph art | `spindoctor theme-scan --keyword xbox` |
| Replace controller glyphs with a community pack | `spindoctor theme-apply C:\Packs\PS-Buttons --apply` |

## Reporting issues

Open an issue at the [project repository](https://github.com/phillram/spindoctor).
