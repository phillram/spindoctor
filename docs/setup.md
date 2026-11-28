# First-time setup

## Prerequisites

Install and test HyperSpin, RocketLauncher and each emulator yourself. Supply
your own lawful ROMs and required BIOS. Confirm a game launches from
RocketLauncher before adding SpinDoctor. Hardware drivers and controller
calibration remain external.

Use [Windows binaries](windows-binaries.md), or [install from source](installation.md)
if Python is available. Python is **not** required for the binaries.

## Configure paths

Open `spindoctor.exe` (binary) or `spindoctor-gui` (source).
In **Setup**, enter your existing folders and save. **Run first-run wizard**
offers a shorter guided setup; it is opt-in.

- `roms_dir`: library root, normally containing one folder per system.
- `hyperspin_dir`: folder containing `Databases`, `Media` and `Settings`.
- `rocketlauncher_dir` and `emulators_dir`: needed for launcher integration.
- Optional: LEDBlinky, MAME executable, output, backup and intro-video paths.

CLI equivalent: `spindoctor config init`. There are no assumed cabinet paths.
Use [system overrides](configuration.md#per-system-overrides) for shared ROM
folders, unusual names or custom extensions.

## Check and add a system

Leave **Apply changes** off and run **Diagnostics**. CLI:

```text
spindoctor systems
spindoctor doctor
spindoctor audit --system MAME
spindoctor add-system "Nintendo Entertainment System"
```

Review the add-system plan, then repeat with `--apply`. Use `add-pc-system`
for installed PC games. SpinDoctor creates database/config/media scaffolding,
not the emulator or the games.

## Optional services and hardware

Save ScreenScraper credentials and/or a TheGamesDB key in Setup; test them
before scraping. `auto` uses configured sources, combining them when both are
available. LaunchBox's database needs no account, and sources can be asked in
turn: see [media sources](media-sources.md). Steam media is a separate per-game
workflow.

- [Custom wheels and helpers](standalone-tools.md)
- [LEDBlinky commands](commands.md#ledblinky) and [light guns](lightgun.md)
- [Intro videos](workflows.md#managing-intro-videos) and [idle tour](idle-tour.md)
- [Launch tests](workflows.md#launch-tests)

Back up before applying broad changes. See [workflows and recovery](workflows.md).
