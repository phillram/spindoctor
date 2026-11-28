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
| Azahar (3DS) | Portable when `user\` sits beside `azahar.exe`; `user\config\qt-config.ini` ignores any value whose `\default` line says `true`. Hidden helper windows: wait for the game window's title. Decrypted dumps only. [3DS games](nintendo-3ds.md). |
| melonDS (DS, DSi) | Portable: `melonDS.toml` beside `melonDS.exe`, written back when melonDS closes, so edit it only while it is closed. No stock module; a module sets screen rotation and DS/DSi mode in the file before each start. F9 and Shift+F9 open file boxes: pause-menu save states 1–8 only. [DS games](nintendo-ds.md). |
| Casual Games | `gamePath` override or `<Rom_Path>/<game>.exe` / `<game>/<game>.exe` must resolve. A placeholder alone is insufficient; stray text files can match the wrong title. |
| Daphne | `.txt` framefile contains real timing data; first line is the video directory. Chip ROMs live under `<homedir>/roms`. A framefile is not an empty placeholder. |
| Daphne Singe | Module expects matching `.singe` and `.txt`; script-relative assets depend on the emulator working directory. Action Max and ALG layouts differ. |
| ALG Singe | `SingePathUpdate`/`ForcePathUpdate` can perform a one-time path rewrite; inspect both loaded scripts and their `dofile` dependencies, then disable forced rewriting. Preserve writable game configs/high scores. |
| Dolphin | Use a module compatible with the installed wx/Qt generation. Verify actual window title/class, fullscreen and focus. RVZ is already compressed and must be permitted in effective `Rom_Extension`. |
| Phoenix Jaguar | The configured XML library's `<Dump>` paths and cartridge selection can remain stale even when RocketLauncher passes the new ROM path. BIOS paths are separate. |
| RetroArch | Many wheels can share one RetroArch, and each can still move on its own through its `Emulators.ini` section and `Modules\RetroArch\<wheel>.ini`. Moving wheels from a 1.7-era RetroArch to a current one changes hotkeys, picture position, save folders and core options: [moving to a current RetroArch](#moving-retroarch-wheels-to-a-current-retroarch). MSU-1 (SNES CD) packs need renaming: [MSU-1 packs](#msu-1-snes-cd-packs). |
| ScummVM | The module reads `scummvm.ini` from `CustomConfig` (module INI, relative to the RocketLauncher folder), else from `%APPDATA%\ScummVM\`; a list kept beside the exe (a portable setup) is read only through `CustomConfig`. Per-game `path=` values inside it survive a ROM drive change; update deliberately. `doctor` checks both. |
| SSF (Saturn) | Once a game has run, its own `Setting\Saturn\<product code>_<title>.ini` wins over `SSF.ini`, keys included: [SSF per-game settings](#ssf-per-game-settings). Discs come through the virtual drive. |
| Virtual-drive systems | Reinstall the correct drive type and update `Virtual_Drive_Path`/drive letter; changing the ROM root alone is insufficient. If DAEMON Tools refuses every mount after an emulator was closed by force: [a stuck virtual drive](troubleshooting.md#library-and-launch-routing). |
| Other emulators | Inspect internal ROM/save paths, module INIs, framefiles and per-game overrides after a move. |

### SSF per-game settings

SSF 0.12 (Sega Saturn) reads `SSF.ini` only for a game it has never run. After
that it keeps the game's settings in `Setting\Saturn\<product code>_<title>.ini`
beside `SSF.exe` (for example `MK-81019_ASTAL.ini`) and uses that file, so later
changes to `SSF.ini` don't reach the game. That includes the ones RocketLauncher's
SSF module writes there before each start.

- **Keys:** each game's file has its own `Pad0_0_0` (player 1) and `Pad1_0_0`
  (player 2) lines. After changing the panel layout in `SSF.ini`, copy those two
  lines into every file in `Setting\Saturn\`, with SSF closed; otherwise the games
  played before keep the old keys.
- **Module options:** the module's per-game options (a `[<game>]` section in its
  INI, such as `SH2enabled`, `ForceRegion` or `BusWait`) are written to `SSF.ini`
  only. For a game that has already run, change its own file too, or set
  `DeleteCachedSettings=true` for it: the module then deletes the game's file
  before each start, and SSF reads `SSF.ini` again. The module reads `UseBIOS`
  from `[Settings]` only, never from a game's section.
- **SH-2 cache:** a few games need SH-2 cache emulation, Astal the best known.
  Some setups keep an older SSF build just for it. One build is enough once the
  game's own file has `SH2Cache="1"` (with `SH2enabled=true` in the module INI).

### Moving RetroArch wheels to a current RetroArch

Older cabinets often run several RetroArch copies of different ages (one for most
wheels, others for a few systems). They can all move to one current RetroArch
(1.22 when this was written), wheel by wheel, beside the old copies until the last
one moves.

- **One wheel at a time:** RocketLauncher reads a wheel's own `[<emulator>]` section
  in `Settings\<wheel>\Emulators.ini` before `Global Emulators.ini`, and
  `Modules\RetroArch\<wheel>.ini` before the module's own INI. Copy the emulator's
  global section into the wheel's file and change only `Emu_Path`; set the new
  `ConfigFolder` and `LibRetro_Core` in the wheel's module INI. The module loads
  cores from the `cores` folder beside `Emu_Path`, and uses `config\<system>.cfg`,
  else `config\<core>.cfg`, else `retroarch.cfg`.
- **Build each config from the new version's own:** a config from a 1.7-era
  RetroArch lacks the hotkey lines added since, and RetroArch then uses their
  factory keys, several of which are letters a keyboard encoder sends (slow
  motion, netplay). Run the new version once with `-c <new file>` and close it
  normally, so it writes every setting; then copy over the panel binds and picture
  settings, and set the hotkeys you don't use to `nul`.
- **Start-up popup:** current versions show the game and core name as a game
  starts (`menu_show_load_content_animation`) and other notices of their own
  (`notification_show_*`). Set the ones you don't want to `"false"`.
- **Picture position:** current versions centre the custom viewport and then add
  `custom_viewport_x` / `custom_viewport_y`. A module `CustomViewportX` that
  centred the picture in a 1.7-era RetroArch now shifts it; use `0`.
- **Saves:** current versions sort saves and states into a folder per core by
  default. Set `sort_savefiles_enable` and `sort_savestates_enable` to `"false"`
  to keep the old folders. An older copy of the RetroArch module (2.4.1, kept for
  one system on some setups) passes `-s` / `-S` on the command line; a current
  RetroArch then ignores the config's save folders and keeps that system's saves
  in `saves\` and `states\` beside `retroarch.exe`.
- **Core options:** each core keeps its own `config\<core name>\<core name>.opt`.
  When a core is replaced (4DO by Opera for 3DO, for example), copy the old
  options under the new core's names. Opera boots a built-in BIOS unless
  `opera_bios` names the real one in `system\`.
- **Pads:** with DS4Windows' virtual DualShock 4 pads, the `sdl2` joypad driver and
  RetroArch's own "PS4 Controller" profile give pad 1 to player 1 and pad 2 to
  player 2. Leave the pad binds in the system config `nul`, so the profile applies,
  and keep the panel's keyboard binds beside them.
- **Bezels:** overlays named with full paths still point at the old copy's
  `overlays` folder, and so may other emulators that borrow a bezel from it. Copy
  them into the new folder and repoint the module INIs' `Overlay=` lines before
  archiving the old copy.

#### MSU-1 (SNES CD) packs

MSU-1 packs made for bsnes v0.9x load through a `.bml` manifest that names the ROM
(`program.rom`), the MSU-1 data file and every track (`track number=N
name=<file>.pcm`). Current bsnes and Snes9x cores don't read those manifests. They
load `<game>.sfc` and look beside it for `<game>.msu` and `<game>-N.pcm`.

- **Rename from the manifest:** the ROM it names becomes `<game>.sfc`, its data file
  `<game>.msu` (an empty one is fine), and each track the `-N.pcm` of its track
  number. Older `cartridge` manifests have no track lines and use `track-N.pcm`.
  Tracks a manifest lists but the pack never shipped stay missing, and the game
  plays its own music there. Copy the manifest's save file (`save.ram`) to the new
  save folder as `<game>.srm`.
- **Remove `bml` from the emulator's `Rom_Extension`**, so RocketLauncher picks the
  `.sfc`.
- **Use Snes9x:** with RetroArch 1.22's bsnes core, the packs tried streamed
  their tracks but showed a black picture, and a Cx4-chip game stayed black even
  with its `cx4.data.rom`. Snes9x showed the picture and played the tracks for
  all 39 packs checked. Check a screenshot, not only the music.
- **Checking with the sound off:** while a core streams a track it holds
  `<game>-N.pcm` open, so opening that file exclusively fails. That shows MSU-1
  working in a muted or hidden test.

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
Where an emulator's own keys can't be read (PC game launchers, Flash players),
it lights the keys each game's AHK keymapper profile remaps or binds.
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
Coin+Select sends Tab. Other Coin combinations send nothing, so an emulator hotkey
can't be a Coin chord: [hotkeys and the shift button](controller-input.md#emulator-hotkeys-and-the-encoders-shift-button).
Never infer a different cabinet's keys from this table.
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
