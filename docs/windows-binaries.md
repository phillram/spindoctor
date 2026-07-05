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
- [GUI walkthrough](gui.md) (tab tour, menubar, shortcuts, dark mode)
- [Migrating from 1.x](migrating-from-1.x.md)

---

## What you get

Each release ships **two bundles** — pick whichever matches your Windows version:

| Bundle | File | Requires | Built with |
|---|---|---|---|
| **Modern** *(recommended)* | `spindoctor-win10-vX.Y.Z.zip` | Windows 10 / 11 | Python 3.12 + PyInstaller 6.x |
| **Win7** | `spindoctor-win7-vX.Y.Z.zip` | Windows 7 SP1+ | Python 3.8 + PyInstaller 5.x |

### Modern bundle (Windows 10/11)

Shared-runtime `--onedir` build. The Python 3.12 runtime lives once in `_internal/`; all the EXEs share it.

```
spindoctor-win10-vX.Y.Z.zip
└── spindoctor-win10-vX.Y.Z/
    ├── spindoctor.exe          ← full CLI (every command)
    ├── spindoctor-gui.exe      ← double-clickable GUI launcher
    ├── spindoctor-fav.exe      ← Favorites wheel manager
    ├── spindoctor-recent.exe   ← Recently Played rebuild
    ├── spindoctor-stats.exe    ← playtime reports + Most Played wheel
    └── _internal/              ← shared Python 3.12 runtime (do not delete)
```

Extract and keep the whole `spindoctor-win10-vX.Y.Z/` folder together — the `_internal/` directory must stay next to the EXEs. Rename the folder if you like (e.g. to plain `spindoctor\`); only its contents matter.

### Win7 bundle (Windows 7 SP1 and newer)

Self-contained `--onefile` EXEs — each is a standalone self-extracting archive. Drop them wherever you like.

```
spindoctor-win7-vX.Y.Z.zip
├── spindoctor.exe          ← full CLI (every command)
├── spindoctor-gui.exe      ← double-clickable GUI launcher
├── spindoctor-fav.exe      ← Favorites wheel manager
├── spindoctor-recent.exe   ← Recently Played rebuild
└── spindoctor-stats.exe    ← playtime reports + Most Played wheel
```

Each `.exe` ships with SpinDoctor's custom icon embedded — visible in Explorer, the taskbar, Alt-Tab, and the window title bar.

## Compatibility

| Windows version | Modern bundle | Win7 bundle |
|---|---|---|
| Windows 11 | ✓ Recommended | ✓ Works |
| Windows 10 | ✓ Recommended | ✓ Works |
| Windows 8 / 8.1 | ✓ Works | ✓ Works |
| Windows 7 SP1 (x64) | ✗ Not supported | ✓ Supported |
| Windows 7 RTM (no SP1) | ✗ Not supported | ✗ Install SP1 first |
| Windows XP / Vista | ✗ Not supported | ✗ Python 3.8 dropped them |

The Win7 bundle is built with **Python 3.8.10 + PyInstaller 5.13.2** — the only pairing whose bootloader loads on Windows 7 SP1. The modern bundle uses **Python 3.12 + PyInstaller 6.x**, which raises the minimum to Windows 8.1 but enables the shared-runtime `--onedir` layout that significantly reduces download size.

## Download

1. Open the [latest release](https://github.com/phillram/spindoctor/releases/latest) on GitHub.
2. Under **Assets**, pick the bundle for your Windows version (see table above).

If you'd rather download from the command line:

```bat
:: Use whichever URL the release page shows — example for v2.4.1:
curl -L -o spindoctor-win7-v2.4.1.zip ^
    https://github.com/phillram/spindoctor/releases/download/v2.4.1/spindoctor-win7-v2.4.1.zip
```

## Install

There's no installer — just extract and optionally rename.

**Modern bundle:** Extract the zip. Move the entire `spindoctor-win10-vX.Y.Z/` folder to a location of your choice, renaming it if you like (e.g. `C:\spindoctor\`). You should end up with:

   ```
   C:\spindoctor\
   ├── spindoctor.exe
   ├── spindoctor-gui.exe
   ├── spindoctor-fav.exe
   ├── spindoctor-recent.exe
   ├── spindoctor-stats.exe
   └── _internal\        ← keep this next to the EXEs
   ```

   Do not move individual EXEs out of the folder — `_internal\` must stay alongside them.

**Win7 bundle:** Extract the zip. Move the `.exe` files to a folder of your choice (e.g. `C:\spindoctor\`). Each binary is self-contained — you can place them individually or together as you prefer.

   ```
   C:\spindoctor\
   ├── spindoctor.exe
   ├── spindoctor-gui.exe
   ├── spindoctor-fav.exe
   ├── spindoctor-recent.exe
   └── spindoctor-stats.exe
   ```

`spindoctor-gui.exe` finds its peer binaries by looking in the same directory as itself, so keeping them in one folder is recommended for GUI use (both bundles).

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

**Double-click `spindoctor-gui.exe`**, fill in the Setup tab (ROMs / HyperSpin / Emulators / RocketLauncher paths, plus optional ScreenScraper / TheGamesDB credentials for metadata fetching), click **Save configuration**. Done. See [GUI launcher](#gui-launcher) below for a tour of every tab.

### Power mode — the CLI

> **Don't double-click `spindoctor.exe` from File Explorer.** It's a command-line tool — with no arguments it prints `--help` and exits, so the cmd window opens, dumps text into itself, and closes again before you can read it. That "flash and disappear" is the program working correctly, not a crash.
>
> Open `cmd.exe` first (`Win+R` → `cmd` → Enter), then:

```bat
cd C:\spindoctor
spindoctor.exe --version
:: SpinDoctor, version 2.9.3

spindoctor.exe config init
```

`config init` is the same wizard the GUI's Setup tab wraps. It asks for every path with sensible Windows defaults pre-filled — press Enter to accept, type `-` to leave an optional path blank.

After the wizard (either route), a safe first command is `spindoctor tools-audit` — it never touches files and reports every third-party arcade utility installed alongside SpinDoctor (Tur-RemoveDupes, FatMatch, Sinden, DemulShooter, …) with the SpinDoctor command that supersedes each one. It's also one click away in the GUI's **Diagnostics** tab.

## GUI launcher

`spindoctor-gui.exe` is a Tkinter front-end for cabinet owners who'd rather not drop into `cmd.exe`. **Double-click it** — that's the supported launch — and a single window opens with workflow-ordered tabs that cover essentially the entire CLI surface, a `File` / `View` / `Help` menubar, and a shared output panel that streams subprocess output as commands run.

The GUI is a thin wrapper — it shells out to `spindoctor.exe` (and the standalone wheel binaries) sitting next to it. Keep all the EXEs in the same folder; the GUI does not require `PATH` to be configured.

**For the full GUI walkthrough — tab tour, menubar, keyboard shortcuts, dry-run feedback, find bar, quick-filter, dark mode, first-run wizard, and per-tab health badges — see the platform-neutral [GUI walkthrough](gui.md).** The same window ships on Windows binary, pip, and source installs; the walkthrough applies to all three.

### Tab tour, menubar, shortcuts, dry-run feedback, dark mode

All moved to the platform-neutral [GUI walkthrough](gui.md). The same window ships on Windows binary, pip, and source installs; documenting it once and linking from each route is clearer than three near-duplicate copies.

## Wiring into HyperSpin

The cabinet end-user shouldn't need to launch the GUI or drop into `cmd.exe` for routine wheel refreshes — SpinDoctor offers three integration patterns:

**1. HyperSpin Tools menu (`install-tools`).** From the GUI's **Toolkit** tab → "Install for HyperHQ → Tools menu", or from the CLI:

```bat
spindoctor install-tools
```

Writes four `.bat` shortcuts (Refresh Favorites / Recently Played / Most Played / Both) into `<RocketLauncher>\Modules\HyperLaunch\Tools\spindoctor\`. Register them in **HyperHQ → Tools** and they appear inside HyperSpin's in-cabinet Tools menu.

**2. Inside an existing wheel system (`install-tools --add-to-system`).** If you have a "Toolkit" or "Tools" wheel (a HyperSpin system whose "games" are maintenance tasks), expose the helpers as wheel entries inside it. From the GUI's **Toolkit** tab → "Install into an existing wheel system", or from the CLI:

```bat
spindoctor install-tools --add-to-system Toolkit
```

Writes the bats and per-game PCLauncher INIs under `<RocketLauncher>\Modules\PCLauncher\Toolkit\`, and adds matching `<game>` entries to `<HyperSpin>\Databases\Toolkit\Toolkit.xml`. The target system must already exist and use PCLauncher as its emulator.

**3. Automatic refresh on cabinet startup.** From the GUI's **Toolkit** tab → "Auto-refresh on cabinet startup", click *Schedule auto-refresh* (Windows-only — wraps `schtasks.exe`). Configurable post-log-on delay so HyperSpin / RocketLauncher settle before the rebuild kicks in. Manual equivalent:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Refresh Wheels" /rl LIMITED /f ^
  /tr "cmd.exe /c \"spindoctor-fav rebuild --apply & spindoctor-recent rebuild --apply & spindoctor-stats build-wheel --apply\""
```

## Updating

1. Download the new zip from [Releases](https://github.com/phillram/spindoctor/releases/latest).
2. Replace the `.exe` files in your install folder with the newly extracted ones.
3. Re-run `spindoctor --version` (or relaunch `spindoctor-gui.exe` and check the title bar) to confirm the new build.

Your config (`%USERPROFILE%\.spindoctor\config.json`), favorites, ignore lists, and caches are untouched — they live in `%USERPROFILE%\.spindoctor\` and persist across upgrades.

## Troubleshooting

### Double-clicking `spindoctor.exe` flashes a window that closes instantly

Expected — the CLI binaries print `--help` and exit when run with no arguments. See [Troubleshooting → Double-clicking `spindoctor.exe` flashes a window that closes instantly](troubleshooting.md#double-clicking-spindoctorexe-flashes-a-window-that-closes-instantly) for the three workarounds.

### "Windows protected your PC" SmartScreen warning

The published binaries aren't code-signed yet, so Windows 10 / 11 may flag them as unrecognised. Click **More info** → **Run anyway**.

If your IT policy blocks unsigned binaries entirely, fall back to a source install (`pip install -e .[all]`) or build the binary yourself with a code-signing certificate — see [Building from source](#building-from-source).

### `spindoctor-gui.exe` opens a window but the buttons do nothing

The GUI shells out to `spindoctor.exe` and the standalone wheel binaries sitting next to it. If those moved, got renamed, or were quarantined by antivirus, every button click pops a "Binary not found" error pointing at the missing file. Re-download or re-extract the affected EXE from the release zip — each is a self-contained binary.

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
