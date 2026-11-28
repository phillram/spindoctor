# Nokia N-Gage games in EKA2L1

SpinDoctor doesn't install emulators or supply games or system files. These notes are
about running Nokia N-Gage games from RocketLauncher in [EKA2L1](https://github.com/EKA2L1/EKA2L1),
the Symbian emulator. Checked with EKA2L1's automatic build of 2026-11-27 (commit
`c1d921a`, shown as 0.0.9) on Windows 10, with a ROM dump of a classic N-Gage (NEM-4):
check again after an upgrade, on a copy first.

## Install

EKA2L1 for Windows is portable: everything sits beside `eka2l1_qt.exe` (`config.yml` says
`data-storage: data`):

| Where | What |
|---|---|
| `config.yml` | Settings. Written back when EKA2L1 closes, so edit it only while it is closed. |
| `bindings\default.yml` | Keys and pad buttons (the profile `config.yml` names in `current-keybind-profile`). Also written back on exit. |
| `Data\devices.yml`, `Data\roms\<code>\`, `Data\drives\z\<code>\` | The installed phones: each one's ROM and Z: drive. |
| `Data\drives\c\` | The phone's C: drive, where most N-Gage games keep their saves. Keep it. |
| `cache\` | A zip card unpacked for the game being played. |

**The phone.** EKA2L1 installs an N-Gage from a ROM dump of your own phone (`SYM.ROM`,
the Z: drive), through its Install device menu. The classic N-Gage is `NEM-4`, the
N-Gage QD `RH-29`. `eka2l1_qt.exe --listdevices` lists what is installed. Nokia's service
flash files for the phone (`.3c1`/`.0C1` MCU and `.326`/`.026` PPM files) are not a ROM
dump: the start of the Symbian ROM inside them, with its header and kernel, is encrypted.

**Keep the build you tested.** The automatic builds change every few days, and the
`updater` folder replaces the program. EKA2L1 also asks GitHub for a newer build at every
start and shows "New update available" over the game when there is one. Its "Do not
automatically check for update when startup" box is a Qt setting, so a module can switch
the check off before each start: `noAutoCheckUpdate` = `true` (a string value) under
`HKCU\Software\EKA2L1\EKA2L1`.

## Game files: memory cards

N-Gage games came on MMC memory cards. A card dump is the card's root folder:
`System\Apps\<id>\` with the game (`<id>.app`, `<id>.aif`, its data), often
`System\Libs\` with the libraries it brought. EKA2L1 mounts a card as the E: drive:
`--mount <folder or zip>`.

- **A zip** (the card's `System` folder at the zip's root) is unpacked into EKA2L1's
  `cache` at every start and mounted read-only.
- **A folder** is mounted read-only too, unless the word `writeable` comes before it:
  `--mount writeable "<folder>"`.

Real cards were writable, and some games write to theirs: NCAA Football 2004 keeps its
season there ("Unable to create save game space" on a read-only card), and Flo Boarding
quits at start when it can't write its options file. So a wheel can keep one zip per game,
unpack each once into a cache folder (again only when the zip is replaced, without
deleting the files the game wrote) and mount that folder writable. That cache then holds
those games' saves: don't clean it up. Before replacing a card zip with one whose app
folder has another name, delete that game's cache folder, or the card ends up with both.

Making clean card zips from the dumps you have:

- Dumps often sit inside extra folders. The zip's root must be the folder that holds
  `System`.
- A dump with `System\App\` needs it renamed to `System\Apps\`.
- A `Libs` folder beside `System` belongs in `System\Libs`.
- Files a dump keeps at the card's root (`GAME.ID`, `Nokia.dat`, `VERSION.DAT`) stay.

### Missing system libraries

Some dumps don't include the N-Gage libraries that other games install to the phone, such
as `gamecomms.dll`, `gameutils.dll`, `ngmwext.dll` or `whichservice.dll`. The game then stops
at start with "System error", and EKA2L1's log (`EKA2L1.log` beside the exe) says
`Try loading <id>.app to apprun… failed` or names the library. Put the missing libraries
into the card's `System\Libs` (from another card that has them), without replacing ones
the card already has.

## Starting games from RocketLauncher

RocketLauncher has no stock module for EKA2L1. A module can start a game with:

```text
eka2l1_qt.exe --device NEM-4 --mount writeable "<card folder>" --runng --fullscreen
```

- **`--runng`** starts the one game on the card. A game folder and its `<id>_1` build
  count as one game (EKA2L1 runs the `_1` build when it loads; some dumps carry a stub
  `<id>` beside it). A card with other folders in `System\Apps` (a video player, a save
  folder) stops it with "Can't find the game mounted in E drive"; start that game by its
  app UID instead: `--run 0x101FF856` (`--listapp` lists the UIDs).
- **A console window.** Given command-line options, EKA2L1 opens a console for its output.
  Hide it once it appears (AutoHotkey: `WinHide, ahk_class ConsoleWindowClass ahk_pid
  <pid>`). Starting EKA2L1 hidden hides the game's window too.
- **The window** is `eka2l1_qt.exe`'s, titled "EKA2L1 … - Symbian OS emulator". Closing it
  ends EKA2L1; when the game quits through its own menu, EKA2L1 quits with it.
- **One EKA2L1 at a time.** A module that waits for the process name `eka2l1_qt.exe` to
  close also waits for any other copy, such as a test copy.
- **The border.** EKA2L1 fills the screen around the N-Gage picture with a light grey (a
  Qt setting). `background-image` in `config.yml` is drawn over the whole window under
  the game: point it at a black PNG, or a bezel picture, by a path relative to EKA2L1's
  folder (where RocketLauncher starts it).

## Panel and pads

`bindings\default.yml` is a list of binds, each a source and a target:

```yaml
- source:
    type: key
    data:
      keycode: 66
  target: 53
- source:
    type: controller
    data:
      controller_id: 0
      button_id: 0
  target: 53
```

- **Key sources** are Qt key codes: a letter is its upper-case ASCII code (`B` = 66); the
  arrows are 16777234 to 16777237 (left, up, right, down); Return is 16777220.
- **Pad sources:** `controller_id` is the SDL joystick number; `button_id` is EKA2L1's
  button code: A (Cross) 0, B (Circle) 1, X (Square) 2, Y (Triangle) 3, LB 4, RB 5,
  Back (Share) 6, Start (Options) 7, D-pad up 11, right 12, down 13, left 14, left stick
  right 300, left 301, down 302, up 303, L2 308, R2 309.
- **Targets** are the phone's key codes: `0` to `9` are 48 to 57, `*` 42, `#` 127, the
  D-pad up 16, down 17, left 14, right 15, its centre (OK) 167, left soft key 164, right
  soft key 165, green (call) key 180.

N-Gage games use 5 and 7 as their main buttons, then 1, 3, 9, 0, `*` and `#`; the soft
keys open and close menus. Leave the Menu key and the red key unbound: both leave the
game. One layout that works on a two-row panel: 7, 5, 1, 3 on the top row; `*`, 0, `#`,
9 on the bottom row; Start the left soft key, Coin the right soft key.

**PS4 pads.** The `SDL2.dll` that comes with EKA2L1 (SDL 2.0.20, built with XInput and
HIDAPI only) listed none of DS4Windows' DualShock 4 copies; SDL 2.30's lists them, so
an `SDL2.dll` from SDL 2.30 beside `eka2l1_qt.exe` lets the pads work (SDL2 keeps its
interface between versions). See [PS4 pads](ps4-pads.md).

## Testing

`--debug-control-port <port>` opens a loopback HTTP API, useful on a test copy: `GET
/v1/apps` lists the card's apps, `POST /v1/apps/<uid>/launch` starts one, `POST
/v1/input/key` with `{"keys":["5"],"action":"tap"}` presses a phone key, and `GET
/v1/screenshot` returns the emulated screen as a PNG (only for an app started through the
API). That can boot every card on a wheel and save a picture of each, also on a hidden
desktop, where a window capture can't see EKA2L1's OpenGL picture. Keep the port off on
the cabinet itself.
