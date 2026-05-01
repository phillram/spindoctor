# Windows binaries

Standalone `.exe` files for cabinets that can't (or shouldn't) install Python. Drop them onto disk, run from `cmd` or the HyperSpin Tools menu, done.

## Contents

- [What you get](#what-you-get)
- [Compatibility](#compatibility)
- [Download](#download)
- [Install](#install)
- [First run](#first-run)
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
├── spindoctor-fav.exe      ← Favorites wheel manager
├── spindoctor-recent.exe   ← Recently Played rebuild
└── spindoctor-stats.exe    ← playtime reports + Most Played wheel
```

All four are **single-file** PyInstaller binaries — no installer, no setup wizard, no DLL hell. Each is roughly 30–50 MB because it bundles its own Python runtime and all dependencies (lxml, Pillow, py7zr, rarfile).

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

> ![GitHub release page with the spindoctor-windows zip highlighted under Assets](images/windows-binaries-release-page.png)
>
> *Screenshot: GitHub Release page showing the `spindoctor-windows-vX.Y.Z.zip` asset.*

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
   ├── spindoctor-fav.exe
   ├── spindoctor-recent.exe
   └── spindoctor-stats.exe
   ```

   > ![File Explorer showing the four .exe files in C:\spindoctor](images/windows-binaries-extract.png)
   >
   > *Screenshot: extracted contents of `spindoctor-windows-vX.Y.Z.zip`.*

2. **Add the folder to `PATH`** so you can run `spindoctor` from anywhere:

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

```bat
spindoctor --version
:: SpinDoctor, version 1.0.0

spindoctor config init
```

`config init` is the wizard that points SpinDoctor at your library. It asks for every path with sensible Windows defaults pre-filled — press Enter to accept, type `-` to leave an optional path blank.

> ![cmd.exe window running spindoctor config init showing the path prompts](images/windows-binaries-cmd.png)
>
> *Screenshot: `spindoctor config init` running in `cmd.exe`.*

After the wizard, settings live at `%USERPROFILE%\.spindoctor\config.json`. Re-run `config init` later to refine — it uses your current values as defaults.

A safe first command after install is `spindoctor tools-audit` — it never touches files and reports every third-party arcade utility installed alongside SpinDoctor (Tur-RemoveDupes, FatMatch, Sinden, DemulShooter, …) with the SpinDoctor command that supersedes each one.

## Wiring into HyperSpin

The cabinet end-user shouldn't need to drop into `cmd.exe` — SpinDoctor wires into the HyperSpin Tools menu so wheel refreshes are one click:

```bat
spindoctor install-tools
```

Writes four `.bat` shortcuts (Refresh Favorites / Refresh Recently Played / Refresh Most Played / Refresh Both) into `<RocketLauncher>\Modules\HyperLaunch\Tools\spindoctor\`. Register them in **HyperHQ → Tools** and they appear inside HyperSpin's UI.

> ![HyperSpin Tools menu showing the four spindoctor refresh entries](images/windows-binaries-tools-menu.png)
>
> *Screenshot: HyperSpin Tools menu after `spindoctor install-tools`.*

For automatic boot-time refresh:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Wheels" ^
  /tr "cmd /c spindoctor-fav rebuild --apply && spindoctor-recent rebuild --apply && spindoctor-stats build-wheel --apply"
```

## Updating

1. Download the new zip from [Releases](https://github.com/phillram/spindoctor/releases/latest).
2. Replace the four `.exe` files in `C:\spindoctor\` (or wherever you extracted them).
3. Re-run `spindoctor --version` to confirm the new build.

Your config (`%USERPROFILE%\.spindoctor\config.json`), favorites, ignore lists, and caches are untouched — they live in `%USERPROFILE%\.spindoctor\` and persist across upgrades.

## Troubleshooting

### "Windows protected your PC" SmartScreen warning

The published binaries aren't code-signed yet, so Windows 10 / 11 may flag them as unrecognised. Click **More info** → **Run anyway**.

> ![SmartScreen warning dialog with the More info link circled](images/windows-binaries-smartscreen.png)
>
> *Screenshot: SmartScreen "Windows protected your PC" dialog.*

If your IT policy blocks unsigned binaries entirely, fall back to a source install (`pip install -e .[all]`) or build the binary yourself with a code-signing certificate — see [Building from source](#building-from-source).

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
