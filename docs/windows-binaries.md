# Windows binaries

Standalone `.exe` files for cabinets that can't (or shouldn't) install Python. Drop them onto disk, double-click the GUI launcher or run the CLI from `cmd`, done.

> **Already on Python 3.8+?** You don't need this — `pip install -e .` ships the same CLI plus a `spindoctor-gui` console-script equivalent of the GUI launcher. See [Installation](installation.md). The binaries below exist specifically for boxes where installing Python isn't an option.

## Contents

- [What you get](#what-you-get)
- [Compatibility](#compatibility)
- [Download](#download)
- [Install](#install)
- [First run](#first-run)
- [GUI launcher](#gui-launcher)
- [Wiring into HyperSpin](#wiring-into-hyperspin)
- [Updating](#updating)
- [Troubleshooting](#troubleshooting)
- [Building from source](#building-from-source)

---

## What you get

Each release at [github.com/phillram/spindoctor/releases](https://github.com/phillram/spindoctor/releases) attaches a single zip:

```
spindoctor-windows-vX.Y.Z.zip
├── spindoctor.exe          ← full CLI (every command)
├── spindoctor-gui.exe      ← double-clickable GUI launcher
├── spindoctor-fav.exe      ← Favorites wheel manager
├── spindoctor-recent.exe   ← Recently Played rebuild
└── spindoctor-stats.exe    ← playtime reports + Most Played wheel
```

All five are single-file PyInstaller binaries — no installer, no setup wizard, no DLL hell. The CLI exes are roughly 30–50 MB each because they bundle their own Python runtime plus dependencies (lxml, Pillow, py7zr, rarfile); `spindoctor-gui.exe` is smaller (~15–20 MB) because it just bundles Tkinter and shells out to the others.

## Compatibility

| Windows version | Status |
|---|---|
| Windows 7 SP1 (x64) | ✓ Supported |
| Windows 8 / 8.1 | ✓ Supported |
| Windows 10 | ✓ Supported (SmartScreen warning — see [Troubleshooting](#troubleshooting)) |
| Windows 11 | ✓ Supported (SmartScreen warning — see [Troubleshooting](#troubleshooting)) |
| Windows 7 RTM (no SP1) | ✗ Not supported — install SP1 from Windows Update first |
| Windows XP / Vista | ✗ Not supported — Python 3.8 dropped them |

Built with **Python 3.8.10 + PyInstaller 5.13.2** on a `windows-2022` GitHub Actions runner. The Win 7 SP1 compatibility comes from the CPython 3.8 + PyInstaller 5.x pairing — these pins are deliberate, see [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md#windows-7-compatibility) for the rationale.

## Download

1. Open the [latest release](https://github.com/phillram/spindoctor/releases/latest) on GitHub.
2. Under **Assets**, click `spindoctor-windows-vX.Y.Z.zip`.

If you'd rather download from the command line:

```bat
:: Use whichever URL the release page shows — example for v1.0.0:
curl -L -o spindoctor-windows.zip ^
    https://github.com/phillram/spindoctor/releases/download/v1.0.0/spindoctor-windows-v1.0.0.zip
```

## Install

There's no installer — just extract.

1. Make a folder (e.g. `C:\spindoctor\`) and extract the zip into it. You should end up with:

   ```
   C:\spindoctor\
   ├── spindoctor.exe
   ├── spindoctor-gui.exe
   ├── spindoctor-fav.exe
   ├── spindoctor-recent.exe
   └── spindoctor-stats.exe
   ```

   Keep all five together — `spindoctor-gui.exe` finds the other binaries by looking next to itself.

2. **Add the folder to `PATH`** (optional, GUI users can skip) so you can run `spindoctor` from anywhere:

   ```bat
   :: One-liner — adds to your user PATH (no admin required)
   setx PATH "%PATH%;C:\spindoctor"
   ```

   Open a **new** Command Prompt afterwards (the existing one keeps the old PATH).

   Or, skip the PATH step and call by full path:

   ```bat
   C:\spindoctor\spindoctor.exe systems
   ```

## First run

You have two equivalent ways to point SpinDoctor at your library — pick whichever you prefer. Both write to the same `%USERPROFILE%\.spindoctor\config.json`.

### Easy mode — the GUI

**Double-click `spindoctor-gui.exe`**, fill in the Setup tab (ROMs / HyperSpin / Emulators / RocketLauncher paths), click **Save configuration**. Done. See [GUI launcher](#gui-launcher) below for a tour of every tab.

### Power mode — the CLI

> **Don't double-click `spindoctor.exe` from File Explorer.** It's a command-line tool — with no arguments it prints `--help` and exits, so the cmd window opens, dumps text into itself, and closes again before you can read it. That "flash and disappear" is the program working correctly, not a crash.
>
> Open `cmd.exe` first (`Win+R` → `cmd` → Enter), then:

```bat
cd C:\spindoctor
spindoctor.exe --version
:: SpinDoctor, version 1.2.0

spindoctor.exe config init
```

`config init` is the same wizard the GUI's Setup tab wraps. It asks for every path with sensible Windows defaults pre-filled — press Enter to accept, type `-` to leave an optional path blank.

After the wizard (either route), a safe first command is `spindoctor tools-audit` — it never touches files and reports every third-party arcade utility installed alongside SpinDoctor (Tur-RemoveDupes, FatMatch, Sinden, DemulShooter, …) with the SpinDoctor command that supersedes each one. It's also one click away in the GUI's **Audit & Doctor** tab.

## GUI launcher

`spindoctor-gui.exe` is a Tkinter front-end for cabinet owners who'd rather not drop into `cmd.exe`. **Double-click it** — that's the supported launch — and a single window opens with 11 tabs that cover essentially the entire CLI surface, plus a shared output panel that streams subprocess output as commands run.

> ![SpinDoctor GUI showing the Setup tab and the output panel](images/gui-launcher-overview.png)
>
> *Screenshot: `spindoctor-gui.exe` after launch, with the output panel showing a completed `doctor` run.*

The GUI is a thin wrapper — it shells out to `spindoctor.exe` (and the standalone wheel binaries) sitting next to it. Keep all five files in the same folder; the GUI does not require `PATH` to be configured.

### Tab tour

**Setup** — every path-based config key in a single form, pre-populated with your current `config.json` values (or sensible Windows defaults on first run). Each row has a Browse button that opens a native folder picker, and Save validates the configuration once it lands on disk. Equivalent to `spindoctor config init`.

> ![Setup tab populated with cabinet paths](images/gui-launcher-setup-tab.png)

**Wheels** — Refresh Favorites / Recently Played / Most Played, plus a Refresh All Three that chains them. Below the refresh buttons is a HyperSpin integration explainer (Most Played auto-registers in the Main Menu, Favorites and Recently Played do not, none auto-fire on cabinet startup) plus two helpers: **Add wheels to Main Menu** (chains `mainmenu add Favorites/Recently Played/Most Played --apply`) and **Install Tools-menu helpers** (a shortcut into the Tools tab's `install-tools` action). Equivalent to `spindoctor-fav rebuild --apply` / `spindoctor-recent rebuild --apply` / `spindoctor-stats build-wheel --apply`.

> ![Wheels tab with the four refresh buttons](images/gui-launcher-wheels-tab.png)

**Main Menu** — reorder, hide, sort, add, or remove the systems on HyperSpin's top-level wheel (`Main Menu.xml`). Show renders the current order in the output panel; pick a system, type a position if needed, then click Move up / Move down / Reorder / Hide / Show / Add / Remove. Sort rewrites the whole wheel alphabetically, by manufacturer, or by year. One Apply checkbox shared by every action — dry-run by default. Equivalent to the `spindoctor mainmenu *` subcommand group.

**Audit & Doctor** — pick a system from the dropdown to run a per-system audit, or click Run doctor / Tools audit / Audit all systems for library-wide checks. None of these write to disk. Equivalent to `spindoctor audit`, `spindoctor doctor`, `spindoctor tools-audit`.

> ![Audit & Doctor tab with the system dropdown expanded](images/gui-launcher-audit-tab.png)

**Diagnose** — one-click read-only inspectors that don't change anything on disk: Find duplicate ROMs, Find misplaced ROMs, Find orphan media, Check disc-set consistency, Lint, Generate report, Preview HyperSpin XML, Stats. Plus a Global Search box (`spindoctor find-global`) and a Verify-against-DAT mini-form (`spindoctor verify --system X --dat …`).

**LEDBlinky** — Generate (controls.ini + colors.ini), Audit coverage, Check, and Fix. Per-system field defaults to MAME, plus an Overwrite toggle for community-maintained entries. Dry-run by default. Equivalent to `spindoctor ledblinky generate / audit / check / fix`.

**Lightgun** — Detect installed Sinden / DemulShooter gear (with optional `--apply` to persist the discovered systems into config), Audit per-system wiring, and Configure one system's RocketLauncher INI with optional `-target` / extra-args overrides. Equivalent to `spindoctor lightgun detect / audit / configure`.

**Tools** — three sections that cover the HyperSpin-integration surface:

1. **Install for HyperHQ → Tools menu** — writes the four `Refresh *.bat` helpers into `<RocketLauncher>\Modules\HyperLaunch\Tools\spindoctor\` (or a custom output dir). Then register them in HyperHQ → Tools to expose them in the in-cabinet Tools menu.
2. **Install into an existing wheel system** — adds the four helpers as `<game>` entries inside an existing HyperSpin wheel (e.g. a `Toolkit` wheel where the "games" are maintenance tasks), with per-game PCLauncher INIs alongside the bats. The target system must already exist and use PCLauncher as its emulator. Equivalent to `spindoctor install-tools --add-to-system <NAME>`.
3. **Auto-refresh on cabinet startup** (Windows-only) — Schedule auto-refresh registers a Task Scheduler `ONLOGON` task with a configurable post-log-on delay (default 2 min). Remove scheduled task and Check task status round out the lifecycle. Off-Windows, this section shows launchd / crontab equivalents inline.
4. **Manual setup** — inline instructions for HyperHQ → Tools and `taskschd.msc` if you'd rather configure them by hand.

**Backup & Restore** — Per-component checkboxes (default: all seven — roms, databases, media, emulators, rocketlauncher, ledblinky, settings), shared target-folder picker for create/list, separate backup-folder picker for info/restore, optional label, dry-run by default. Restore-time toggles for `--use-current-paths` (drive letters changed since backup) and `--overwrite`. Equivalent to `spindoctor backup create / list / info / restore`.

**Migrate** — Per-component checkboxes (default: all five — roms, hyperspin, emulators, rocketlauncher, ledblinky), target-root picker, optional comma-separated systems filter for partial roms migrations, toggles for `--keep-source` / `--verify` / `--no-update-config` / `--preserve-names`, and a separate Undo panel that pre-fills `latest` and exposes `--list-manifests`. Dry-run by default. Equivalent to `spindoctor migrate`.

**Custom Command** — anything the dedicated tabs don't cover. The entry field is now an editable Combobox seeded with ~70 canonical commands grouped by family (discovery, audit, curate, fetch, wheels, main menu, LEDBlinky, lightgun, backup, migrate, config). Default value is `--help`. Pick a preset, edit `<PLACEHOLDER>` tokens (`<SYSTEM>`, `<PATH>`, …), press Enter or click Run. Unfilled placeholders trigger a warning instead of silently shelling out.

> ![Custom Command tab with `audit --all` typed into the entry](images/gui-launcher-custom-tab.png)

### Stopping a long-running command

The Stop button in the bottom-right of the window terminates the current subprocess (sends `SIGTERM` / Windows `TerminateProcess`). The GUI re-enables the Run buttons once the child exits.

## Wiring into HyperSpin

The cabinet end-user shouldn't need to launch the GUI or drop into `cmd.exe` for routine wheel refreshes — SpinDoctor offers three integration patterns:

**1. HyperSpin Tools menu (`install-tools`).** From the GUI's **Tools** tab → "Install for HyperHQ → Tools menu", or from the CLI:

```bat
spindoctor install-tools
```

Writes four `.bat` shortcuts (Refresh Favorites / Recently Played / Most Played / Both) into `<RocketLauncher>\Modules\HyperLaunch\Tools\spindoctor\`. Register them in **HyperHQ → Tools** and they appear inside HyperSpin's in-cabinet Tools menu.

**2. Inside an existing wheel system (`install-tools --add-to-system`).** If you have a "Toolkit" or "Tools" wheel (a HyperSpin system whose "games" are maintenance tasks), expose the helpers as wheel entries inside it. From the GUI's **Tools** tab → "Install into an existing wheel system", or from the CLI:

```bat
spindoctor install-tools --add-to-system Toolkit
```

Writes the bats and per-game PCLauncher INIs under `<RocketLauncher>\Modules\PCLauncher\Toolkit\`, and adds matching `<game>` entries to `<HyperSpin>\Databases\Toolkit\Toolkit.xml`. The target system must already exist and use PCLauncher as its emulator.

**3. Automatic refresh on cabinet startup.** From the GUI's **Tools** tab → "Auto-refresh on cabinet startup", click *Schedule auto-refresh* (Windows-only — wraps `schtasks.exe`). Configurable post-log-on delay so HyperSpin / RocketLauncher settle before the rebuild kicks in. Manual equivalent:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Refresh Wheels" /rl LIMITED /f ^
  /tr "cmd.exe /c \"spindoctor-fav rebuild --apply & spindoctor-recent rebuild --apply & spindoctor-stats build-wheel --apply\""
```

## Updating

1. Download the new zip from [Releases](https://github.com/phillram/spindoctor/releases/latest).
2. Replace the five `.exe` files in `C:\spindoctor\` (or wherever you extracted them).
3. Re-run `spindoctor --version` (or relaunch `spindoctor-gui.exe` and check the title bar) to confirm the new build.

Your config (`%USERPROFILE%\.spindoctor\config.json`), favorites, ignore lists, and caches are untouched — they live in `%USERPROFILE%\.spindoctor\` and persist across upgrades.

## Troubleshooting

### Double-clicking `spindoctor.exe` flashes a window that closes instantly

Expected. SpinDoctor's CLI binaries (`spindoctor.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, `spindoctor-stats.exe`) are command-line tools — with no arguments they print `--help` and exit, and Windows tears down the cmd window the moment they exit. Use one of:

- Double-click `spindoctor-gui.exe` instead (see [GUI launcher](#gui-launcher)).
- Open `cmd.exe` first (`Win+R` → `cmd` → Enter), `cd` into the install folder, then run the binary with arguments.
- Use the bundled `.bat` wrappers under [`scripts/`](https://github.com/phillram/spindoctor/tree/main/scripts) — they `pause` on error so the window stays open.

### "Windows protected your PC" SmartScreen warning

The published binaries aren't code-signed yet, so Windows 10 / 11 may flag them as unrecognised. Click **More info** → **Run anyway**.

If your IT policy blocks unsigned binaries entirely, fall back to a source install (`pip install -e .[all]`) or build the binary yourself with a code-signing certificate — see [Building from source](#building-from-source).

### `spindoctor-gui.exe` opens a window but the buttons do nothing

The GUI shells out to `spindoctor.exe` and the standalone wheel binaries sitting next to it. If those moved, got renamed, or were quarantined by antivirus, every button click pops a "Binary not found" error pointing at the missing file. Restore the missing exe (or re-extract the release zip) so all five files share a folder again.

If `spindoctor-gui.exe` itself fails to open at all on Windows 7, you're hitting the same `api-ms-win-core-…` bootloader issue documented below — install Service Pack 1 first.

### `'spindoctor' is not recognized as an internal or external command`

The folder isn't on `PATH`. Either:

- Re-run the `setx PATH …` command from [Install](#install) and open a new `cmd.exe`, or
- Call by full path: `C:\spindoctor\spindoctor.exe systems`.

### "The procedure entry point ... could not be located in api-ms-win-core-..."

Windows 7 SP1 is missing. The bundled bootloader needs SP1's API set. Install Service Pack 1 via Windows Update, then retry.

If you self-built and hit this on a Win 7 box, your build environment is too modern — see [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md#windows-7-compatibility) for the pinned Python + PyInstaller versions.

### Antivirus quarantines `spindoctor.exe`

PyInstaller binaries occasionally trigger heuristic detections because the bundled-runtime pattern resembles malware packers. The release zip's SHA256 is shown on the GitHub Release page — verify it matches before adding an exclusion. If you can't whitelist it, the source install (`pip install -e .[all]`) bypasses the bundled runtime entirely.

### A specific command crashes only in the `.exe` (works fine via `pip install`)

Likely a missing hidden import in the PyInstaller spec — open an issue with the full traceback. The fix is usually a one-line addition to the `HIDDEN_IMPORTS` list in [`build/build_windows.py`](https://github.com/phillram/spindoctor/blob/main/build/build_windows.py).

For everything else, see the general [Troubleshooting guide](troubleshooting.md).

## Building from source

If you'd rather build the binaries yourself (custom code-signing, internal mirror, modified source), on a Windows machine with Python 3.8:

```bat
git clone https://github.com/phillram/spindoctor C:\spindoctor-src
cd C:\spindoctor-src
pip install -e .[all]
pip install -r build\requirements-build.txt
python build\build_windows.py
```

Output lands in `dist\`. The full build matrix and CI workflow lives in [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md).
