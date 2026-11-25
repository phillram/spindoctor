# Cabinet integration reference

Examples for an existing HyperSpin/RocketLauncher cabinet, not an inventory
or required folder layout. Adapt paths, versions and physical mappings.
SpinDoctor's internal design is in [architecture](architecture.md).

## Directory layout

```text
<HyperSpin>/
  HyperSpin.exe
  Databases/<System>/<System>.xml
  Databases/Main Menu/Main Menu.xml
  Settings/Settings.ini
  Settings/<System>.ini
  Media/<System>/
<RocketLauncher>/
  Settings/Global Emulators.ini
  Settings/<System>/Emulators.ini
  Modules/<Emulator>/
  Data/Statistics/<System>.ini
<ROM root>/<System>/
```

HyperSpin may itself be the cabinet root; do not add an extra `HyperSpin`
directory unless one exists. Configuration/state is separate, under
`.spindoctor`. [Paths and storage](spindoctor-files.md).

## HyperSpin settings and media

Per-wheel settings are `Settings/<System>.ini`. `[navigation] random_game`
and `use_last_game` determine first/random/last starts; manage with `wheel-start`.
Close HyperSpin before changing INIs because it rewrites them on exit.

`[video defaults] path=` redirects the **whole** wheel's video lookup.
A redirect hides local `Media/<System>/Video` files, with no per-game fallback.
Check redirects after drive moves; `doctor` reports missing/hidden videos.
Relative redirect behavior is ambiguous, so prefer deliberate absolute paths
or blank for the wheel's own folder.

Game media stems must match database names exactly. Important slots include
`Images/Wheel`, `Images/Backgrounds`, `Video`, `Themes` and `Sound`.
Main Menu assets use system names, not game names.
`wheels_only` hides games without wheel art, `parents_only` hides clones, and
HyperSpin's own `roms_only` path/extensions can hide games RocketLauncher finds.
Letter-jump art lives in `Images/Letters/<character>.png`.

[Bundled synthetic-wheel media](synthetic-wheel-media.md) and
[intro rotation](workflows.md#managing-intro-videos) are separate features.

## RocketLauncher settings and ROM lookup

Folder layout uses `Settings/<System>/Emulators.ini`, section `[ROMS]`;
flat layout uses `Settings/<System>.ini`, section `[Settings]`.
A minimal folder-layout routing entry:

```ini
[ROMS]
Default_Emulator=MAME
Rom_Path=J:\Games\MAME
```

`Rom_Path` can contain `|`-separated folders. Relative paths resolve from
RocketLauncher. Lookup includes `<name>.<ext>` and `<name>/<name>.<ext>`;
extension and game-specific emulator choices matter. Shared MAME ROM folders
need not be duplicated for every sub-wheel.

`Settings/Global Emulators.ini` supplies emulator definitions such as:

```ini
[MAME]
Emu_Path=..\Emulators\MAME\mame64.exe
Rom_Extension=zip|7z|txt
Module=MAME.ahk
```

System emulator definitions and `Games.ini` overrides can supersede defaults.
Check the effective selection, not just the global entry. `audit` uses
RocketLauncher ROM paths where configured; `check-archive-ext` compares archive
contents with effective allowed extensions.

### PCLauncher

PCLauncher ROM placeholders use `Rom_Extension=ini`. Distinguish:
- `Modules/PCLauncher/<System>/<game>.ini`: placeholder/launch configuration.
- `Modules/PCLauncher/<System>.ini`: module settings with game-named sections.
- `Modules/PCLauncher/PCLauncher.ini`: fallback module settings.

PC game settings can be shadowed by stale system-level entries; inspect all
levels. Filename sanitization does not change the game name expected in a
module section. `pc-fix-exe`, `pc-rename` and `add-pc-system` serve different
purposes; see [PC workflows](workflows.md#managing-pc-games).

Synthetic wheels launch a source game through another RocketLauncher invocation.
Generated launchers handle a distinct launcher EXE, frontend IPC, `AppWaitExe`
and `FadeTitle`; do not replace them with a generic PC-game template.
Rebuild with the current version before hand-editing a stuck fade.
A pre-existing PCLauncher directory is not proof a wheel belongs to SpinDoctor.

Toolkit helpers also need module-level routing, not just a database game and
placeholder file. `install-tools --add-to-system` writes the matching pieces
and honors a system's configured ROM folder.

### Play statistics

`Data/Statistics/<System>.ini` contains per-game launch count, last-played
timestamp and accumulated time. Recent/Most Played read these.
Failed or recursive launches can leave records too; launching successfully is
not evidence every statistic is meaningful. Launch tests back statistics up
and restore them, with a journal for interrupted runs.

## Emulator-specific integration

These are manual integration checks, not promises that migration rewrites them.

| Emulator/module | Important boundary |
|---|---|
| MAME/HBMAME | Effective `mame.ini`/`hbmame.ini` controls `cfg_directory`, `ctrlr`, `ctrlrpath`. Empty/crash-truncated `default.cfg` can silently reset the panel. Preserve a working map. |
| Cxbx-Reloaded | `settings.ini` beside `cxbx.exe` (else the user's AppData) holds the core setting, pads and profiles; the module can set them per game. A second build needs its own emulator entry. [Xbox games](xbox.md). |
| Casual Games | `gamePath` override or `<Rom_Path>/<game>.exe` / `<game>/<game>.exe` must resolve. A placeholder alone is insufficient; stray text files can match the wrong title. |
| Daphne | `.txt` framefile contains real timing data; first line is the video directory. Chip ROMs live under `<homedir>/roms`. A framefile is not an empty placeholder. |
| Daphne Singe | Module expects matching `.singe` and `.txt`; script-relative assets depend on the emulator working directory. Action Max and ALG layouts differ. |
| ALG Singe | `SingePathUpdate`/`ForcePathUpdate` can perform a one-time path rewrite; inspect both loaded scripts and their `dofile` dependencies, then disable forced rewriting. Preserve writable game configs/high scores. |
| Dolphin | Use a module compatible with the installed wx/Qt generation. Verify actual window title/class, fullscreen and focus. RVZ is already compressed and must be permitted in effective `Rom_Extension`. |
| Phoenix Jaguar | The configured XML library's `<Dump>` paths and cartridge selection can remain stale even when RocketLauncher passes the new ROM path. BIOS paths are separate. |
| ScummVM | The module reads `scummvm.ini` from `CustomConfig` (module INI, relative to the RocketLauncher folder), else from `%APPDATA%\ScummVM\`; a list kept beside the exe (a portable setup) is read only through `CustomConfig`. Per-game `path=` values inside it survive a ROM drive change; update deliberately. `doctor` checks both. |
| Virtual-drive systems | Reinstall the correct drive type and update `Virtual_Drive_Path`/drive letter; changing the ROM root alone is insufficient. |
| Other emulators | Inspect internal ROM/save paths, module INIs, framefiles and per-game overrides after a move. |

## Input

Keyboard encoders, virtual pads and keymappers are independent layers. Keep one
intentional menu-mapping path and inspect RocketLauncher User Functions for
extra mapper launches. [DS4Windows example](controller-input.md).

RetroArch can accept keyboard and controller bindings together. Explicit `nul`
entries disable a binding rather than restoring autodetect; system configs and
game overrides can replace global hotkeys.
Other emulators read one source and drop the panel while a controller is on:
[panel and controller together](controller-input.md#panel-and-controller-together).

Dolphin's selected device and per-game profile matter. A GameCube mapping needs
explicit keyboard device qualifiers if the selected gamepad is disconnected;
Wii profiles may behave differently. RocketLauncher custom controller profiles
can overwrite global edits on launch.

For raw-input Supermodel, use distinct numbered mice and real keyboard keys.
AHK profile precedence and gun details are in [light guns](lightgun.md).

## LEDBlinky

| File | Purpose |
|---|---|
| `controls.ini` | Per-emulator/per-ROM control assignments |
| `Colors.ini` | Per-ROM button/admin color names |
| `Color-RGB.ini` | Named RGB intensities, each channel 0–48 |
| `LEDBlinkyControls.xml` | Runtime control map, grouped by emulator |
| `LEDBlinkyInputMap.xml` | Physical controller/port labels and input codes |
| `Settings.ini` | Frontend/game animation, input and speech behavior |

Respect file casing in source/tests even though Windows is case-insensitive.
Generation preserves existing entries unless overwrite is requested and restores
missing saved library entries before synthesizing MAME data.
`ledblinky prune` preserves removed sections in `.spindoctor/ledblinky_library`;
do not delete that library as a cache.

`ledblinky profiles` can derive emulator/ROM controls and AHK-remapped admin
keys; inspect coverage rather than assuming every emulator has a MAME schema.
Color brightness commands normalize/scale named colors, not Windows display
brightness.

`GamePlayLWAFile=<Random>` animates unused game buttons;
`FELWAFile=<Random>` selects frontend animations. `LightFEControls=1` can hold
active menu controls at fixed colors over the animation. Use
`ledblinky patch-settings --help` rather than guessing unrelated settings.

Persistent blinking on one PAC-LED64 can be onboard flash mode, not an animation.
`toolkit reset-button-lights` clears board flash speeds through the compatible
32-bit DLL; it is a live hardware operation.

## LEDBlinky animation files (.lwax)

LWAX is XML: frames have millisecond durations and controller-addressed intensity
(0–48) and state (0/1) data; omitted values persist between frames.
Generated files are **unsigned**. Open them in LEDBlinky's Animation Editor and
use **Animation → Save As** to obtain a valid signature. Renaming/editing XML
does not sign it.

`ledblinky lwax` offers fade, batch, cute, calibration and flash-check commands.
The cute set has **20 smooth patterns and 100 built-in themes**, with
`--color/--color2/--color3` and `--seed` for variants. It uses the example panel's
physical coordinates and rejects unknown controls. Batch includes the cute
themes plus flash-free soft fill/drain alternatives; use its generated index
rather than a fixed total that changes with the library.
Batch replaces its previous output; keep signed/custom files elsewhere.

`flash-check` replays raw/signed files including the loop seam and classifies
Smooth, Fast motion, Borderline, Fast blink or Strobe. Scores are not a
photosensitivity certification. Existing batch patterns can intentionally flash.

### Physical button layout

Example panel coordinates, not universal hardware wiring. Position is distinct
from port numbering; the cute generator places the trackball at tier 2.4.

| Tier | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Admin** | | | | | | [Left Click](#ctl-left-click) | [Right Click](#ctl-right-click) | [Select](#ctl-select) (`Enter`) | | [Exit](#ctl-exit) (`Escape`) | [Search](#ctl-search) (`/`) | [Pause](#ctl-pause) (`P`) | | | | | |
| **Coin / Start** | [P1 Start](#ctl-p1-start) (`R`) | [P1 Coin](#ctl-p1-coin) (`S`) | | | | | | | | | | | | | [P2 Start](#ctl-p2-start) (`T`) | [P2 Coin](#ctl-p2-coin) (`U`) | |
| **Top** (joystick, B1–4, trackball) | P1 Joystick (`↑↓←→`) | [P1 B1](#ctl-p1-button-1) (`A`) | [P1 B2](#ctl-p1-button-2) (`B`) | [P1 B3](#ctl-p1-button-3) (`C`) | [P1 B4](#ctl-p1-button-4) (`V`) | | | | [Trackball](#ctl-trackball) | | | | P2 Joystick (`N`/`Q`/`M`/`O`) | [P2 B1](#ctl-p2-button-1) (`G`) | [P2 B2](#ctl-p2-button-2) (`H`) | [P2 B3](#ctl-p2-button-3) (`I`) | [P2 B4](#ctl-p2-button-4) (`Y`) |
| **Bottom** (B5–8) | | [P1 B5](#ctl-p1-button-5) (`D`) | [P1 B6](#ctl-p1-button-6) (`E`) | [P1 B7](#ctl-p1-button-7) (`F`) | [P1 B8](#ctl-p1-button-8) (`W`) | | | | | | | | | [P2 B5](#ctl-p2-button-5) (`J`) | [P2 B6](#ctl-p2-button-6) (`K`) | [P2 B7](#ctl-p2-button-7) (`L`) | [P2 B8](#ctl-p2-button-8) (`X`) |

P1 Start/Coin are columns 1/2; P2 Start/Coin are 15/16, not a mirror image.
Joysticks have no LEDs. Verify any new hardware against direct calibration.

### Master control reference

Example pin/key/port assignments below retain the confirmed reference mapping.
`LEDBlinkyInputMap.xml` is the runtime routing source; calibrate before trusting
a label. Earlier maps had a four-way B4–B7 label rotation on both boards,
corrected by one-control-at-a-time calibration. Colors vary by game.

| Physical control | LedBlinky label | Mini-PAC pin | Key sent | PAC-LED64 board:ports | RetroArch action |
|---|---|---|---|---|---|
| <a id="ctl-select"></a>Select | `SELECT` | pin02 | `Enter` | 1 : 4-6 | — |
| <a id="ctl-exit"></a>Exit | `EXIT` | pin03 | `Escape` | 2 : 1-3 | — |
| <a id="ctl-search"></a>Search | `SEARCH` | pin04 | `/` | 2 : 4-6 | — |
| <a id="ctl-pause"></a>Pause | `PAUSE` | pin05 | `P` | 2 : 7-9 | — |
| <a id="ctl-left-click"></a>Left Click | `LMOUSE` | pin43 | Left Click | 1 : 10-12 | — |
| <a id="ctl-right-click"></a>Right Click | `RMOUSE` | pin42 | Right Click | 1 : 7-9 | — |
| <a id="ctl-trackball"></a>Trackball (ball movement) | `TRACKBALL` | — (analog axes) | moves mouse cursor | 1 : 1-3 | — |
| <a id="ctl-p1-joystick-up"></a>P1 Joystick Up | *(no LED)* | pin37 | `↑` | — | `input_player1_up` |
| <a id="ctl-p1-joystick-down"></a>P1 Joystick Down | *(no LED)* | pin36 | `↓` | — | `input_player1_down` |
| <a id="ctl-p1-joystick-left"></a>P1 Joystick Left | *(no LED)* | pin38 | `←` | — | `input_player1_left` |
| <a id="ctl-p1-joystick-right"></a>P1 Joystick Right | *(no LED)* | pin39 | `→` | — | `input_player1_right` |
| <a id="ctl-p1-start"></a>P1 Start | `P1START` | pin25 | `R` | 1 : 16-18 | `input_player1_start` |
| <a id="ctl-p1-coin"></a>P1 Coin | `P1COIN` | pin23 | `S` *(swop key)* | 1 : 13-15 | `input_player1_select` |
| <a id="ctl-p1-button-1"></a>P1 Button 1 | `P1B1` | pin35 | `A` | 1 : 28-30 | `input_player1_b` |
| <a id="ctl-p1-button-2"></a>P1 Button 2 | `P1B2` | pin34 | `B` | 1 : 25-27 | `input_player1_a` |
| <a id="ctl-p1-button-3"></a>P1 Button 3 | `P1B3` | pin33 | `C` | 1 : 22-24 | `input_player1_y` |
| <a id="ctl-p1-button-4"></a>P1 Button 4 | `P1B4` | pin32 | `V` | 1 : 19-21 | — |
| <a id="ctl-p1-button-5"></a>P1 Button 5 | `P1B5` | pin29 | `D` | 1 : 40-42 | `input_player1_x` |
| <a id="ctl-p1-button-6"></a>P1 Button 6 | `P1B6` | pin28 | `E` | 1 : 37-39 | `input_player1_l` |
| <a id="ctl-p1-button-7"></a>P1 Button 7 | `P1B7` | pin27 | `F` | 1 : 34-36 | `input_player1_r` |
| <a id="ctl-p1-button-8"></a>P1 Button 8 | `P1B8` | pin26 | `W` | 1 : 31-33 | — |
| <a id="ctl-p2-joystick-up"></a>P2 Joystick Up | *(no LED)* | pin17 | `N` | — | `input_player2_up` |
| <a id="ctl-p2-joystick-down"></a>P2 Joystick Down | *(no LED)* | pin16 | `Q` | — | `input_player2_down` |
| <a id="ctl-p2-joystick-left"></a>P2 Joystick Left | *(no LED)* | pin18 | `M` | — | `input_player2_left` |
| <a id="ctl-p2-joystick-right"></a>P2 Joystick Right | *(no LED)* | pin19 | `O` | — | `input_player2_right` |
| <a id="ctl-p2-start"></a>P2 Start | `P2START` | pin24 | `T` | 2 : 10-12 | `input_player2_start` |
| <a id="ctl-p2-coin"></a>P2 Coin | `P2COIN` | pin22 | `U` | 2 : 13-15 | `input_player2_select` |
| <a id="ctl-p2-button-1"></a>P2 Button 1 | `P2B1` | pin15 | `G` | 2 : 16-18 | `input_player2_b` |
| <a id="ctl-p2-button-2"></a>P2 Button 2 | `P2B2` | pin14 | `H` | 2 : 19-21 | `input_player2_a` |
| <a id="ctl-p2-button-3"></a>P2 Button 3 | `P2B3` | pin13 | `I` | 2 : 22-24 | `input_player2_y` |
| <a id="ctl-p2-button-4"></a>P2 Button 4 | `P2B4` | pin12 | `Y` | 2 : 25-27 | — |
| <a id="ctl-p2-button-5"></a>P2 Button 5 | `P2B5` | pin09 | `J` | 2 : 28-30 | `input_player2_x` |
| <a id="ctl-p2-button-6"></a>P2 Button 6 | `P2B6` | pin08 | `K` | 2 : 31-33 | `input_player2_l` |
| <a id="ctl-p2-button-7"></a>P2 Button 7 | `P2B7` | pin07 | `L` | 2 : 34-36 | `input_player2_r` |
| <a id="ctl-p2-button-8"></a>P2 Button 8 | `P2B8` | pin06 | `X` | 2 : 37-39 | — |

P1 Coin is the example shift key: Coin+Up/Down controls Windows volume;
Coin+Select sends Tab. Never infer a different cabinet's keys from this table.
The reference XML files in `docs/reference/` are examples, not auto-installed maps.

## HyperSpin startup/exit orchestration

HyperSpin can run one Startup Program and one Exit Program. Cabinets often use
a Startup Script INI to manage numbered helper lists; keep numbering contiguous.
Its `[Exit] Process_Name_To_Close_N` entries kill helpers, which can leave dead
tray icons. Prefer graceful supported exits where possible. Do not kill the
shared SpinDoctor EXE when other workers may still be active.

The common Startup Script is 32-bit; a batch needing 64-bit PowerShell may need
`%SystemRoot%/Sysnative/WindowsPowerShell/v1.0/powershell.exe` when called by it.
DS4Windows should normally start once at Windows login and survive frontend
exit. Idle tour instead starts with HyperSpin and stops itself.

See [helpers](standalone-tools.md), [idle tour](idle-tour.md) and
[troubleshooting](troubleshooting.md).
