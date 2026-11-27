# Nintendo DSi games in RetroArch's melonDS DS core

SpinDoctor doesn't install emulators or supply games or system files. These notes are
about running Nintendo DSi games, DSiWare and DSi-enhanced cartridges, from
RocketLauncher. Checked with the melonDS DS core 1.4.0 in RetroArch 1.22.2 on Windows 10,
with files dumped from a real DSi: check again after an upgrade, on a copy first.

## Why the core, not melonDS

The standalone melonDS 1.x runs a DSi (see [DSi mode](nintendo-ds.md#dsi-mode)), and a DS
game runs fine in it. A DSiWare game doesn't: opened like a cartridge, it sits on a white
screen. melonDS runs DSiWare only once it is installed into the DSi's NAND image with its
title manager and started from the DSi menu. The NAND's main partition holds about
200 MB, and there is no way to start one title from the command line, so that doesn't
work for a wheel of DSiWare.

The [melonDS DS](https://github.com/JesseTG/melonds-ds) libretro core installs the game
into the NAND image when it starts and removes it again on exit, and keeps the game's save
outside the NAND. DSi-enhanced cartridges (often `.dsi`) run without touching the NAND.

## System files

All from a DSi of your own. Put them in RetroArch's `system` folder (or a
`system\melonDS DS` folder; the core looks there first):

| File | What it is |
|---|---|
| `dsi_bios7.bin`, `dsi_bios9.bin` | The DSi's ARM7 and ARM9 BIOS, 64 KB each. These names are fixed. |
| `dsi_nand.bin` | The NAND dump with no$gba's footer: 251,658,304 bytes (240 MB plus 64 bytes that start `DSi eMMC CID/CPU` and hold the console ID the core needs to decrypt it). The name is free; the core lists every file that looks like a NAND. |
| `dsi_firmware.bin` | The DSi's own firmware, 128 KB. The name is free; pick it in the core options. |
| `bios7.bin`, `bios9.bin` | The DS BIOS. Optional; the core has its own. |

The core writes to the NAND image with every DSiWare game it runs (the install and the
removal), so keep an untouched copy elsewhere.

The first time a DSiWare game needs its title metadata (TMD), the core downloads it from
Nintendo's update server (`nus.cdn.t.shop.nintendowifi.net`) and keeps it in
`system\melonDS DS\tmd\<content name>.tmd`. A cabinet that is often offline should start
each game once while online.

## Core options

In `config\melonDS DS\melonDS DS.opt` (RetroArch writes the file back when it closes, so
edit it while RetroArch is closed):

| Option | Value | Why |
|---|---|---|
| `melonds_console_mode` | `"dsi"` | DSi mode. |
| `melonds_boot_mode` | `"direct"` | Straight into the game, without the DSi menu or a button press. |
| `melonds_sysfile_mode` | `"native"` | Use the dumped files. |
| `melonds_dsi_nand_path` | `"/auto"` | Picks a NAND whose region matches the game. |
| `melonds_firmware_dsi_path` | the firmware's file name | |
| `melonds_number_of_screen_layouts`, `melonds_screen_layout1` | `"1"`, `"top-bottom"` | One fixed layout: top screen above the touch screen. |
| `melonds_show_current_layout` | `"disabled"` | No layout pop-up at each start. |
| `melonds_show_cursor` | `"disabled"` | See [the stylus pointer](#the-stylus-pointer). The core's own cursor is a plain square. |
| `melonds_mic_input`, `melonds_mic_input_active` | `"noise"`, `"hold"` | The microphone button blows while held; a PC without a microphone hears nothing otherwise. |

DSi mode has no save states (so no rewind or run-ahead either).

## Game files

DSiWare often comes as one zip per game holding the decrypted content file named after
its content index, with no extension: `00000000`, `00000001` and so on, sometimes beside
a `cetk` and a `tmd`. Neither RocketLauncher's 7z nor RetroArch can pick that file up
(RetroArch: "Could not read content file"). Rename it inside the zip to the zip's own
name with `.nds`:

```bat
7z rn "Some Game (USA).zip" 00000001 "Some Game (USA).nds"
```

`7z rn` rewrites the archive without recompressing it, so the game data stays the same
(check with `7z l -slt`: same CRC and size). Name the file after the zip: RocketLauncher
finds it by name and extension, and the core names the game's save and TMD after it.

## Starting games from RocketLauncher

The wheel's `Settings\<System>\Emulators.ini`:

```ini
[ROMS]
Default_Emulator=RetroArch
[RetroArch]
Emu_Path=..\Emulators\RetroArch\retroarch.exe
Rom_Extension=7z|zip|nds|dsi
Module=RetroArch.ahk
Pause_Save_State_Keys=
Pause_Load_State_Keys=
```

RocketLauncher's stock RetroArch module (2.4.3) needs two changes:

- **It has no "Nintendo DSi" system.** It stops with "not one of the known supported
  systems". Add a line to its system table, next to `Nintendo DS|LibRetro_DS|...`, and
  the name to `MSystem`:

  ```text
  Nintendo DSi|LibRetro_DSi|melondsds_libretro
  ```

  It then uses `config\<System>.cfg` as the wheel's RetroArch config.
- **It never brings RetroArch's window forward.** It runs `Wait()` and then
  `WaitActive()`. If RetroArch's window opens a little late, the frontend can keep the
  front: the game plays behind it, and after 30 s the module stops with "There was an
  error waiting for the window RetroArch ahk_class RetroArch to become active". Bring the
  window forward between the two, for example for this system only:

  ```autohotkey
  emuPrimaryWindow.Wait()
  If (systemName = "Nintendo DSi") {
      Loop, 240 {    ; up to 60 s
          If emuPrimaryWindow.Active(0)
              Break
          emuPrimaryWindow.Activate(0)
          Sleep, 250
      }
  }
  emuPrimaryWindow.WaitActive()
  ```

  A second loop after `FadeInExit()` that activates the window again for a few seconds
  keeps it in front if the frontend takes the front back once more.

## The stylus pointer

The touch screen takes the mouse, so a trackball's left button is the stylus. In full
screen RetroArch hides the Windows pointer, so RocketLauncher's custom cursor
(`Hide_Cursor=custom`, as for [3DS games](nintendo-3ds.md#screens-and-full-screen)) never
shows, and the core's own cursor is only a plain square. To show a stylus, run this
wheel's RetroArch as a borderless window that covers the screen:

- the module's per-system INI, `Modules\RetroArch\<System>.ini`:

  ```ini
  [Settings]
  Fullscreen=false
  ```

  (otherwise the module adds `-f`);
- in the wheel's RetroArch config: `video_fullscreen = "false"`,
  `video_window_show_decorations = "false"`, `video_window_save_positions = "true"`,
  `video_windowed_position_x` / `_y` = `0` and `_width` / `_height` = the screen size;
- `ui_menubar_enable = "false"`: with it on, RetroArch makes the window taller by the
  menu bar's height even without decorations, and the bottom of the touch screen hangs
  below the screen;
- `melonds_show_cursor = "disabled"`, and `Hide_Cursor=custom` in the wheel's
  `RocketLauncher.ini` with the cursor in `RocketLauncher\Media\Cursors\<System>\_Default\`.

## Panel and pad

The core's RetroPad buttons, from its source (`src/libretro/input/joypad.cpp`; the
libretro docs page lists other buttons for these):

| RetroPad | DS / DSi |
|---|---|
| A, B, X, Y, L, R, Start, Select, D-pad | the same buttons |
| L3 (held) | microphone |
| Y while L2 is held | close / open the lid (one press each) |
| L2 | also speeds up the joystick cursor |
| R2 (held) + right stick | touch with a joystick cursor |
| R3 | next screen layout |

So on a keyboard panel, bind the microphone to `input_player1_l3`; the lid is a two-key
press (L2 held, then the key bound to Y). Bind R3 to nothing if the layout should never
change. PS4 pads work as in RetroArch's other cores ([PS4 pads](ps4-pads.md)).

## Saves

A DSiWare game's save is exported when the core closes and read back at the next start:
`<save folder>\<content name>.public.sav` (and `.private.sav`, `.banner.sav` when the
game has them). A DSi-enhanced cartridge saves as `<content name>.srm`.

## Sideways games

Some DSiWare is held like a book (Brain Age Express, for example) and shows up turned
90°. RetroArch's own rotation would turn the picture but not the touch input, so use the
core's layout instead, per game: with `game_specific_options = "true"`, RetroArch reads
`config\melonDS DS\<content name>.opt` instead of `melonDS DS.opt` for that game. Make it
a full copy of `melonDS DS.opt` with `melonds_screen_layout1 = "rotate-left"` (top
screen on the left, touch screen on the right; `"rotate-right"` is the other way round).
A later change to `melonDS DS.opt` has to go into these files too.

## Testing

On a hidden desktop, RetroArch can save its own picture of a run:
`--max-frames=1800 --max-frames-ss --max-frames-ss-path=<file>.png` (the core in
`"software"` render mode). An ordinary screen copy of the borderless window comes back
black; Windows' desktop duplication captures it.
