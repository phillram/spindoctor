# Sega Dreamcast, Naomi and Atomiswave games in Flycast

SpinDoctor doesn't install emulators or supply games. These notes are about running
Dreamcast, Naomi and Atomiswave games in Flycast from RocketLauncher. Checked with
Flycast 2.7 on Windows 10: check again after an upgrade, on a copy first.

RocketLauncher has no stock Flycast module. Its NullDC, Redream and Demul modules don't
fit: Flycast takes the game on its command line and has no options window to drive, so a
short module is enough: see [Starting games from RocketLauncher](#starting-games-from-rocketlauncher).
Sega Hikaru games don't run in Flycast; see [Hikaru in Demul](#hikaru-in-demul).

## Settings

The Windows build is portable: `emu.cfg` and the `mappings` folder sit beside
`flycast.exe`, and a `data` folder there holds the Dreamcast BIOS (`dc_boot.bin`,
`dc_flash.bin`), VMU saves, Naomi NVRAM and the shader cache.

- Flycast writes `emu.cfg` back when it closes (window place, size and full-screen state
  among other things), keeping keys it doesn't know. Edit it only while Flycast is closed.
- `-config section:key=value,...` on the command line sets values for that run only; they
  are not saved. A value may hold spaces and colons, but not a comma. Options with no
  section of their own are in `[config]`.
- Flycast picks each Dreamcast game's region itself (a Japanese disc boots as Japan).

What a cabinet usually wants:

| Section | Setting | Why |
|---|---|---|
| `config` | `UploadCrashLogs = no`, `DiscordPresence = no`, `FetchBoxart = no` | No network calls from the cabinet. |
| `network` | `Enable = no`, `DCNet = no` | The same, for online play. |
| `config` | `rend.TextureFiltering = 0`, `rend.TextureUpscale2 = 1` | The defaults: sharp textures. An inherited texture upscaler smears text. |
| `config` | `rend.Resolution = 1440` | 3× the Dreamcast's 480 lines; 960 is 2×. |
| `input` | `maple_sdl_keyboard = 4` | The keyboard on all ports, for two players on one panel: see [Panel and pads](#panel-and-pads). |
| `input` | `device2 = 0`, `device2.1 = 1` | A controller (and a VMU) in port B; by default only port A has one. |
| `config` | `HideCdromDrives = yes` | Keeps the PC's CD drives out of the disc list: see [Multi-disc games](#multi-disc-games). |
| `config` | `Dreamcast.BiosPath = <folder>` | Where the Naomi and Atomiswave BIOS zips are: see [Naomi and Atomiswave sets](#naomi-and-atomiswave-sets). |
| `log` | `LogToFile = yes` | `flycast.log` in the working folder: the game ID, the controllers it opened, errors. |

Arcade games run in free play by default (`ForceFreePlay`).

## Starting games from RocketLauncher

```text
flycast.exe -config "window:fullscreen=yes,window:maximized=no" "<game>"
```

- **Dreamcast:** Flycast reads `.gdi`, `.chd`, `.cdi` and `.cue`, not a disc inside a
  `.rar`, `.7z` or `.zip`. Let RocketLauncher's 7z unpack the archive and pass the image.
- **Naomi and Atomiswave:** pass the set's `.zip` as it is (7z off for those systems).
  Flycast knows the game by the zip's name, so the file must have the set name Flycast uses.
- **Bezels:** start with `window:fullscreen=no` and let `BezelDraw()` fit the window.
- The window class is `SDL_app` and the title `Flycast - <game title>`; wait for
  `ahk_exe flycast.exe`. Close it with `WinClose`: Flycast then writes the VMU and NVRAM.

## Panel and pads

Key maps are files in `mappings`:

| File | Used for |
|---|---|
| `SDL_Keyboard.cfg` | Every Dreamcast game |
| `SDL_Keyboard_arcade.cfg` | Every Naomi and Atomiswave game |
| `SDL_Keyboard_<game ID>.cfg` | One Dreamcast game, instead of the general file |
| `SDL_Keyboard_<game ID>_arcade.cfg` | One arcade game, instead of the general file |

A Dreamcast game's ID is its disc's product number (the IP.BIN at the start of the first
data track, for example `MK-51035`); an arcade game's is the title in its ROM header (for
example `INITIAL D Ver.2`). Both are in `flycast.log` ("Game ID is" / "NAOMI GAME ID"). `/`,
`\` and `:` in an ID become `-` in the file name; leading spaces stay.

```ini
[digital]
bind0 = 4:btn_x
bind1 = 82:btn_analog_up
bind2 = 10:btn_x1
bind3 = 58:btn_menu

[emulator]
mapping_name = Keyboard
version = 3
```

- Each bind is an SDL scancode (`4`–`29` A–Z, `79`–`82` Right, Left, Down, Up, `58` F1)
  and an action. An action ending in `1`, `2` or `3` is for port B, C or D. With the
  keyboard on all ports (`maple_sdl_keyboard = 4`) one file holds both players.
- Flycast's own default keys put buttons, the analog stick and the coin on letters a
  keyboard encoder sends for other buttons (S, D, F, I–L, Q), Start on Return, the menu
  on Tab and fast-forward on Space. Write the whole file.
- **One key drives one action per port.** The stick can't press the D-pad and move the
  analog stick together. Keys move the analog stick over about 0.1 s rather than at once,
  which fighting games feel: put the stick on the analog stick in the general file and on
  the D-pad in per-game files for 2D games.
- **Arcade actions:** buttons 1–6 are `btn_a`, `btn_b`, `btn_c`, `btn_x`, `btn_y`,
  `btn_z`, buttons 7–8 `btn_dpad2_left` / `btn_dpad2_right`, coin `btn_d`, service
  `btn_dpad2_up`, test `btn_dpad2_down`. For driving games `btn_analog_left` / `_right`
  steer, `btn_trigger_right` and `btn_trigger_left` are the pedals (Flycast's input list
  for each game says which axis is gas and which brake). A second stick (some flight
  games' rudder) can't come from keys.
- **PS4 pads** (also DS4Windows' DualShock 4 copies) use SDL's game-controller layout with
  no setup: Cross A, Circle B, Square X, Triangle Y, L2 / R2 the triggers, Options Start;
  in arcade games R2 / L2 are gas and brake. The first pad found is port A, the next B.

## Multi-disc games

Flycast has no playlist and no disc hotkey. A disc is changed in its menu: **Eject Disk**,
then **Insert Disk**, which lists the discs in the content folders
(`Dreamcast.ContentPath`, plus the PC's CD drives unless `HideCdromDrives = yes`), sorted by
name. The game itself asks for the next disc, as on the console, and opening the lid at
any other time drops the console back to its main menu.

A module can do the change for a button press:

- Unpack the game's other discs next to the first one when it starts, and set
  `config:Dreamcast.ContentPath=<that folder>` on the command line.
- Drive the menu with keys sent to the window: the menu key (not Tab), then Tab to step
  and Space to press. Posted mouse clicks don't work, because SDL checks the real mouse
  button state.
- The menu can open with nothing or its first button selected, so don't count Tabs:
  read the window's pixels (`PrintWindow`) and press Space only when the wanted button or
  disc shows the selection colour (66, 150, 250). The title changes to the new disc's name.

## Naomi and Atomiswave sets

Flycast carries its own list of sets, with names from a recent MAME. For each file it
looks in the game's zip by CRC, then in its parent zip in the same folder, then by name.

- Sets dumped for older Demul builds often don't load: GD-ROM games as one decrypted
  `.bin`, and some cartridges in an older revision. MAME sets do.
- GD-ROM games need their disc image as `<folder>\<set>\<disc>.chd` (MAME's layout), or in
  the parent set's folder.
- The BIOS zips (`naomi`, `naomi2`, `awbios`, and `airlbios`, `f355bios`, `f355dlx` for some
  games) are read from `Dreamcast.BiosPath`, then `data`, then the content folders.
- A few sets have other names in Flycast than in older MAME releases (Capcom Vs. SNK 2
  Millionaire Fighting is `cvs2mf`), and the zip's name decides.

## Moving from NullDC, Demul and Redream

- **BIOS:** copy `dc_boot.bin` and `dc_flash.bin` into `data`.
- **VMU saves** are raw 128 KB images in all three. With per-game VMUs on (the default),
  Flycast reads `data\<product number>_vmu_save_A1.bin`: rename each game's file.
- **Demul's per-game control styles** (button orders, driving layouts) become per-game key
  files.

## Hikaru in Demul

Demul 0.7a runs Sega Hikaru games (Demul 0.5.7 doesn't), with `-run=hikaru -rom=<set>`.
Its RocketLauncher module sends Alt+Enter for full screen after the game loads. Sent while
the frontend is in front, it misses Demul; sent while Demul is already full screen, it
switches it back to a small window. Send it only while Demul's window is smaller than the
screen, after activating that window.
