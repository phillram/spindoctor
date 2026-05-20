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
| 🖱️ **GUI launcher** | First-time setup, refreshing wheels, casual use, anyone who'd rather not touch `cmd.exe` | Double-click **`spindoctor-gui.exe`** (binary route) or run **`spindoctor-gui`** (pip route). Full tab tour at [docs/gui.md](docs/gui.md). |
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
| [CLI cheatsheet](docs/cli-cheatsheet.md) | Quick "if you want to do X, run Y" copy-paste sampler, grouped by intent |
| [Command reference](docs/commands.md) | Every command, grouped by purpose |
| [Workflows](docs/workflows.md) | First-system add, daily refresh, weekly maintenance, backup, migration, recovery |
| [Standalone tools](docs/standalone-tools.md) | Favorites / Recent / Most Played wheels — Tools menu and boot wiring; tools-audit for cataloguing other arcade utilities |
| [Light guns](docs/lightgun.md) | Sinden + DemulShooter wiring per system |
| [Troubleshooting](docs/troubleshooting.md) | FAQ + common errors |

Start at [docs/index.md](docs/index.md) for a guided table of contents, or skim [CHANGELOG.md](CHANGELOG.md) for what shipped in each release.

## Common starting points

First launch lands you on the **Setup** tab (the GUI auto-focuses it when no `config.json` exists yet). Click **Run first-run wizard…** on the Setup tab for a guided 3-step flow (Welcome → pick `roms_dir` + `hyperspin_dir` → run `doctor` and read the results). The wizard is opt-in — it does not auto-open — and is also available any time from **Help → First-run setup…**.

Each tab shows a small ⚠ or ✗ badge next to its name when the area it covers has a problem detected by `spindoctor doctor` — `Setup ⚠` means a path or scraper credential needs attention, `LEDBlinky ✗` means LEDBlinky is configured but its files are missing, and so on. Scan the tab strip on launch to see what needs work; saving the Setup tab re-runs the check so badges stay accurate.

The **Metadata & Media** tab has a "Pick subset…" button for the common cabinet workflow of "refresh metadata for *these specific* systems" (often after a scraper improves data for a handful of consoles). Ticking subsystems opens a multi-select picker; "Run on subset…" chains `fetch-meta --system X` once per pick, aborting on the first failure so you can fix the cause before continuing.

Press **Ctrl+F** (Cmd+F on macOS) any time to open a find bar above the Output panel. Useful for scanning long audit / migrate output — type a game name, hit Enter to jump between matches, Esc to close.

Cabinet owners with niche systems (homebrew consoles, PC libraries, custom MAME variants) can configure scraper IDs, ROM extensions, layout, and emulator per-system from the **Systems** tab's *Per-system overrides* form — no need to memorise `config system set` flags.

## What's in the GUI

15 dedicated tabs cover the most-used workflows directly, plus a free-form **Custom Command** tab whose dropdown ships ~70 canonical CLI invocations — anything described under [CLI cheatsheet](#cli-cheatsheet) below also works as a click from inside the GUI if you'd rather not touch `cmd.exe`.

### Tabs

- **Setup** — paths + scraper credentials (ScreenScraper / TheGamesDB), masked with a Show/Hide eyeball and a **Test credentials** button that pings both providers and reports pass/fail.
- **Wheels** — checkboxes for Favorites / Recently Played / Most Played + a *Refresh selected* button that chains only the ticked ones, with step-counter progress in the status bar; HyperSpin integration helpers below.
- **Main Menu** — interactive Treeview of the live system order; select a row, click Move Up / Move Down / Toggle Visible, then Save Order (with confirmation) to write `Main Menu.xml`.
- **Audit & Doctor** — system-by-system audit and the global `doctor` health check.
- **Diagnose** — `find-dupes`, `find-misplaced`, `find-orphan-media`, `check-discs`, `lint`, `report`, `verify` against a DAT, global search.
- **Metadata & Media** — `fetch-meta`, `fetch-media` with media-type checkboxes, `media-scan`, `update-db`, `generate-config`; *Full metadata refresh* chains all three with step-counter status.
- **Curate** — region/revision thinning with an interactive `☑/☐` per-row preview, per-category cleanup checkboxes (safe caches pre-ticked, unsafe caches unchecked), ignore lifecycle with click-to-un-ignore viewer.
- **Systems** — `add-system`, `add-pc-system`, `pc-rename`, and the per-system overrides form mentioned above.
- **LEDBlinky** — generate / audit / check / fix the LED-light configuration.
- **Lightgun** — Sinden + DemulShooter detection and per-system wiring.
- **Tools** — Tools-menu helpers and the Windows auto-refresh-on-log-on hook.
- **Backup & Restore** — *Scan* populates the restore dropdown from your configured backup folder.
- **Migrate** — multi-select systems filter, undo manifest dropdown pre-populated from `~/.spindoctor/migrations/`.
- **Logs** — per-run timeline tagging each row DRY-RUN / OK / FAIL.
- **Custom Command** — type-or-pick CLI invocations; the dropdown is a curated tour of the whole CLI surface.

### Chrome and ergonomics

- **Every tab scrolls** when content overflows the window; thumbs are clearly visible against the dark theme and brighten on hover.
- **Every text input** has a right-click Cut / Copy / Paste / Select-All menu.
- **`View` menu** — UI-scale knob (0.8×–1.5×, `Ctrl++` / `Ctrl+-` / `Ctrl+0`) and a collapsible Output panel (`Ctrl+`` `), so cabinet owners on 1280×720 can fit a full tab without scrolling.
- **`File` menu** — shortcuts to `config.json`, `~/.spindoctor`, a Logs & Manifests viewer (with one-click *Undo this run* for any apply-mode command), and a HyperSpin theme browser.
- **`Help` menu** — About dialog (with the app icon), in-app **Keyboard shortcuts** reference, and *Check for updates* that pings GitHub for newer releases.
- **Single-instance file lock** on startup so two windows can't race on the same HyperSpin XML — override with `SPINDOCTOR_DISABLE_SINGLETON=1` if you genuinely need both open.

### Diagnostics

If **Test credentials** returns a 403 from ScreenScraper or TheGamesDB, the failure dialog includes a trimmed copy of the upstream error body, and every scraper call is also recorded (with secrets redacted) to `~/.spindoctor/scraper.log`. Full diagnostic flow including the optional `screenscraper_devid` / `screenscraper_devpassword` override at [Troubleshooting → 403 from ScreenScraper or TheGamesDB](docs/troubleshooting.md#403-from-screenscraper-or-thegamesdb).

## CLI commands

A curated cheatsheet with copy-paste examples for every common workflow lives at **[docs/cli-cheatsheet.md](docs/cli-cheatsheet.md)** — grouped by intent (discover & diagnose, edit & curate, metadata & media, backup / diff / migrate, custom wheels, themes, light guns, config). For the full per-command reference with every flag, see **[docs/commands.md](docs/commands.md)**.

A few greatest hits to get oriented:

```bat
spindoctor --help                              :: every command
spindoctor doctor                              :: self-diagnose
spindoctor audit --system MAME                 :: ROMs vs HyperSpin DB
spindoctor verify --system NES --dat path\to.dat
spindoctor backup create --target E:\Backups --apply
spindoctor migrate --target E:\Cab --apply
spindoctor-fav rebuild --apply && spindoctor-recent rebuild --apply && spindoctor-stats build-wheel --apply
```

Everything above also works from the GUI's Custom Command tab — the dropdown is pre-populated with ~70 of these.

## Reporting issues

Open an issue at the [project repository](https://github.com/phillram/spindoctor).
