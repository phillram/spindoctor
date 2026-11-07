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

Each release ships **four downloads**. Pick the edition (GUI or CLI) and your Windows version. Each zip contains exactly one standalone EXE.

| Edition | Windows 10/11 *(recommended)* | Windows 7 SP1+ | EXE inside |
|---|---|---|---|
| **GUI** (double-click) | `spindoctor-gui-win10.zip` | `spindoctor-gui-win7.zip` | `spindoctor.exe` |
| **CLI** (terminal) | `spindoctor-cli-win10.zip` | `spindoctor-cli-win7.zip` | `spindoctor-cli.exe` |

Both EXEs embed the runtime, every command worker and all bundled media. The GUI does not need the CLI, and the CLI does not need the GUI. Download the CLI only if you want to run commands from `cmd.exe` or scripts.

The Windows 10/11 builds use Python 3.12 + PyInstaller 6.x. The Windows 7 builds use Python 3.8 + PyInstaller 5.x. Both extract their runtime to a temporary folder when launched, which is normal for PyInstaller one-file builds.
## Compatibility

| Windows version | Windows 10/11 build | Windows 7 build |
|---|---|---|
| Windows 11 | ✓ Recommended | ✓ Works |
| Windows 10 | ✓ Recommended | ✓ Works |
| Windows 8 / 8.1 | ✓ Works | ✓ Works |
| Windows 7 SP1 (x64) | ✗ Not supported | ✓ Supported |
| Windows 7 RTM (no SP1) | ✗ Not supported | ✗ Install SP1 first |
| Windows XP / Vista | ✗ Not supported | ✗ Python 3.8 dropped them |

The Windows 7 build uses **Python 3.8.10 + PyInstaller 5.13.2** — the only pairing whose bootloader loads on Windows 7 SP1. The Windows 10/11 build uses **Python 3.12 + PyInstaller 6.x**, whose bootloader requires Windows 8.1 or newer.

## Download

1. Open the [latest release](https://github.com/phillram/spindoctor/releases/latest) on GitHub.
2. Under **Assets**, pick the GUI or CLI zip for your Windows version (see table above).

If you'd rather download from the command line:

```bat
:: Use whichever URL the release page shows, for example:
curl -L -o spindoctor-gui-win10.zip ^
    https://github.com/phillram/spindoctor/releases/latest/download/spindoctor-gui-win10.zip
```

## Install

There's no installer — just extract and optionally rename.

1. Extract the EXE to a location of your choice (e.g. `C:\spindoctor\`):

   ```
   C:\spindoctor\
   ├── spindoctor.exe        ← GUI
   └── spindoctor-cli.exe    ← CLI (optional)
   ```

   A GUI-only install is fully functional, including wheel builders and media installation.

2. **Add the folder to `PATH`** (optional, GUI users can skip) so you can run `spindoctor` from anywhere:

   ```bat
   :: One-liner — adds to your user PATH (no admin required)
   setx PATH "%PATH%;C:\spindoctor"
   ```

   Open a **new** Command Prompt afterwards (the existing one keeps the old PATH).

   Or, skip the PATH step and call by full path:

   ```bat
   C:\spindoctor\spindoctor-cli.exe systems
   ```

## First run

You have two equivalent ways to point SpinDoctor at your library — pick whichever you prefer. Both write to the same `%USERPROFILE%\.spindoctor\config.json`.

### Easy mode — the GUI

**Double-click `spindoctor.exe`**, fill in the Setup tab (ROMs / HyperSpin / Emulators / RocketLauncher paths, plus optional ScreenScraper / TheGamesDB credentials for metadata fetching), click **Save configuration**. Done. See [GUI launcher](#gui-launcher) below for a tour of every tab.

### Power mode — the CLI

> **Don't double-click `spindoctor-cli.exe` from File Explorer.** It's a command-line tool — with no arguments it prints `--help` and exits, so the cmd window opens, dumps text into itself, and closes again before you can read it. That "flash and disappear" is the program working correctly, not a crash.
>
> Open `cmd.exe` first (`Win+R` → `cmd` → Enter), then:

```bat
cd C:\spindoctor
spindoctor-cli.exe --version
:: SpinDoctor, version 3.1.0

spindoctor-cli.exe config init
```

`config init` is the same wizard the GUI's Setup tab wraps. It asks for every path with no default paths filled in: type each required path, and press Enter (or type `-`) to leave an optional one blank.

After the wizard (either route), a safe first command is `spindoctor tools-audit` — it never touches files and reports every third-party arcade utility installed alongside SpinDoctor (Tur-RemoveDupes, FatMatch, Sinden, DemulShooter, …) with the SpinDoctor command that supersedes each one. It's also one click away in the GUI's **Diagnostics** tab.

## GUI launcher

`spindoctor.exe` is a Tkinter front-end for cabinet owners who'd rather not drop into `cmd.exe`. **Double-click it** — that's the supported launch — and a single window opens with workflow-ordered tabs that cover essentially the entire CLI surface, a `File` / `View` / `Help` menubar, and a shared output panel that streams subprocess output as commands run.

The GUI runs embedded workers by relaunching itself with `--run-tool`; it needs neither another EXE nor `PATH`. Both EXEs support `--run-tool <tool> ARGS...`, where `<tool>` is `spindoctor`, `spindoctor-fav`, `spindoctor-recent`, or `spindoctor-stats`. For example:

```bat
start "" /B /WAIT "C:\spindoctor\spindoctor.exe" --run-tool spindoctor-fav rebuild --apply
spindoctor-cli.exe --run-tool spindoctor-stats build-wheel --apply
```

Worker output and exit codes are preserved through pipes and `.bat` files. Frozen installs no longer need helper-version mismatch warnings: the workers are embedded in the running EXE.

**For the full GUI walkthrough — tab tour, menubar, keyboard shortcuts, dry-run feedback, find bar, quick-filter, dark mode, and first-run wizard — see the platform-neutral [GUI walkthrough](gui.md).** The same window ships on Windows binary, pip, and source installs; the walkthrough applies to all three.

### Tab tour, menubar, shortcuts, dry-run feedback, dark mode

All moved to the platform-neutral [GUI walkthrough](gui.md). The same window ships on Windows binary, pip, and source installs; documenting it once and linking from each route is clearer than three near-duplicate copies.

## Wiring into HyperSpin

The cabinet end-user shouldn't need to launch the GUI or drop into `cmd.exe` for routine wheel refreshes — SpinDoctor offers three integration patterns:

**1. HyperSpin Tools menu (`install-tools`).** From the GUI's **Custom Wheels** tab → "Install for HyperHQ → Tools menu", or from the CLI:

```bat
spindoctor install-tools --tool refresh-favorites,refresh-recently-played,refresh-most-played,refresh-all
```

Writes a `.bat` shortcut for each helper you pick (tick them in the GUI, or name them with `--tool`; run `spindoctor install-tools` alone for the list) into `<RocketLauncher>\Modules\HyperLaunch\Tools\spindoctor\`. Register them in **HyperHQ → Tools** and they appear inside HyperSpin's in-cabinet Tools menu. On binary installs they embed the running EXE's full path plus `--run-tool`, using `start "" /B /WAIT`, so a GUI-only install works.

**2. Inside an existing wheel system (`install-tools --add-to-system`).** If you have a "Toolkit" or "Tools" wheel (a HyperSpin system whose "games" are maintenance tasks), expose the helpers as wheel entries inside it. From the GUI's **Custom Wheels** tab → "Install into an existing wheel system", or from the CLI:

```bat
spindoctor install-tools --tool refresh-all --add-to-system Toolkit --apply
```

Writes the picked bats and per-game PCLauncher INIs under `<RocketLauncher>\Modules\PCLauncher\Toolkit\`, and adds matching `<game>` entries to `<HyperSpin>\Databases\Toolkit\Toolkit.xml`. The target system must already exist and use PCLauncher as its emulator.

**3. Automatic refresh on cabinet startup.** From the GUI's **Custom Wheels** tab → "Auto-refresh on cabinet startup", click *Enable auto-run* (Windows-only — wraps `schtasks.exe`). Configurable post-log-on delay so HyperSpin / RocketLauncher settle before the rebuild kicks in. The generated bat calls the running EXE with `--run-tool` via `start /LOW /B /WAIT ""`, with a hidden VBS shim. See [manual registration](standalone-tools.md#manual-registration) if you need to register the task yourself.

## Updating

1. Download the new zip from [Releases](https://github.com/phillram/spindoctor/releases/latest).
2. Replace the `.exe` files in your install folder with the newly extracted ones.
3. Re-run `spindoctor-cli --version` (or open **Help → About SpinDoctor** in the GUI) to confirm the new build.

Your config (`%USERPROFILE%\.spindoctor\config.json`), favorites, ignore lists, and caches are untouched — they live in `%USERPROFILE%\.spindoctor\` and persist across upgrades.

### Upgrading from v2

v3 ships only `spindoctor.exe` and `spindoctor-cli.exe`; each works alone. Separate wheel-builder EXEs are no longer shipped. Update external scripts to use `--run-tool` (pip console-script names are unchanged); custom builds can use `build_windows.py --legacy-tools` for old scripts.

After upgrading to a new folder or EXE path, re-run `install-tools` (with the same `--tool` picks), click **Enable auto-run** again for wheel refresh, and re-run `introvideo install-autorun --apply` (or enable it again in the GUI) once for intro-video rotation. This rewrites saved paths; GUI/autorun status flags stale tasks, and `spindoctor doctor`'s **SpinDoctor helpers** check flags `install-tools` `.bat` files that still name the old EXE.

## Troubleshooting

### Double-clicking `spindoctor-cli.exe` flashes a window that closes instantly

Expected — the CLI binaries print `--help` and exit when run with no arguments. See [Troubleshooting → Double-clicking `spindoctor-cli.exe` flashes a window that closes instantly](troubleshooting.md#double-clicking-spindoctorexe-flashes-a-window-that-closes-instantly) for the three workarounds.

### "Windows protected your PC" SmartScreen warning

The published binaries aren't code-signed, so Windows 10 / 11 may flag them as unrecognised. Click **More info** → **Run anyway**.

If your IT policy blocks unsigned binaries entirely, fall back to a source install (`pip install -e .[all]`) or build the binary yourself with a code-signing certificate — see [Building from source](#building-from-source).

### `spindoctor.exe` opens a window but the buttons do nothing

v3 embeds every worker in `spindoctor.exe`; there are no helper EXEs to locate. Check the Output panel for the command's error. If an old install reports "Binary not found", replace the GUI with the current release EXE — copying helper files alongside it is not required.

If `spindoctor.exe` itself fails to open at all on Windows 7, you're hitting the same `api-ms-win-core-…` bootloader issue documented below — install Service Pack 1 first.

### `'spindoctor' is not recognized as an internal or external command`

The folder isn't on `PATH`. Either:

- Re-run the `setx PATH …` command from [Install](#install) and open a new `cmd.exe`, or
- Call by full path: `C:\spindoctor\spindoctor-cli.exe systems`.

### "The procedure entry point ... could not be located in api-ms-win-core-..."

Windows 7 SP1 is missing. The bundled bootloader needs SP1's API set. Install Service Pack 1 via Windows Update, then retry.

If you self-built and hit this on a Win 7 box, your build environment is too modern — see [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md#windows-7-compatibility) for the pinned Python + PyInstaller versions.

### Antivirus quarantines `spindoctor.exe` or `spindoctor-cli.exe`

PyInstaller binaries occasionally trigger heuristic detections because the bundled-runtime pattern resembles malware packers. The release zip's SHA256 is shown on the GitHub Release page — verify it matches before adding an exclusion. If you can't whitelist it, the source install (`pip install -e .[all]`) bypasses the bundled runtime entirely.

### A specific command crashes only in the `.exe` (works fine via `pip install`)

Likely a missing PyInstaller hidden import — open an issue with the full traceback. The fix is usually a one-line addition to the `HIDDEN_IMPORTS` list in [`build/build_windows.py`](https://github.com/phillram/spindoctor/blob/main/build/build_windows.py).

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
