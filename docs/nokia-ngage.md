# Nokia N-Gage games in EKA2L1

SpinDoctor doesn't install emulators or supply games or system files. These notes are
about running Nokia N-Gage games from RocketLauncher in [EKA2L1](https://github.com/EKA2L1/EKA2L1),
the Symbian emulator. Checked with EKA2L1's automatic build of 2026-11-27 (commit
`c1d921a`, shown as 0.0.9) on Windows 10, with a ROM dump of a classic N-Gage (NEM-4)
and, for [N-Gage 2.0 games](#n-gage-20-games), a dump of a Nokia N85 (RM-333): check
again after an upgrade, on a copy first.

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

## N-Gage 2.0 games

N-Gage 2.0 (2008-2009) was an app for Symbian S60 3rd Edition phones: its games came
as `.n-gage` files from the app's shop, and the app installed and started them. In
EKA2L1 it needs one of those phones, installed from a dump of the phone (its `SYM.ROM`
and Z: drive); this section was checked with a Nokia N85 (`RM-333`, S60 3rd Edition
Feature Pack 2).

**The app can't run them now.** The N-Gage app (v1.40) installs and opens, then stops on
"There was an error validating your certificate. Please make sure that date and time are
set correctly in your device": its certificate ran out in 2009. EKA2L1 sets the phone's
clock from the PC's at every start. Started with a date in June 2009, the app lists the
games but calls each `.n-gage` file "File is corrupted. Delete Now?": EKA2L1 doesn't open
the protected (DRM) content the app installs a game from.

**The game package runs on its own.** A `.n-gage` file is a MIME multipart bundle of
three parts, each with a `Content-ID` header: the shop's details (`RetailerInfo`, XML), a
metadata package (`Metadata`, `.sis`) and the game package (`Game`, `.sis`). Installed
straight onto the phone, the game package puts the game's program in `E:\sys\bin\` and its
data in `E:\private\<UID>\`, and `--run` starts that program without the app, at today's
date:

```text
eka2l1_qt.exe --device RM-333 --run E:\sys\bin\<program>.exe --fullscreen
```

- **Splitting the file.** The parts are separated by boundary lines (`--KBoundary` in
  the files tried). A part's headers end at its first blank line; its body runs to the
  line break before the next boundary. For example, in Python:

  ```python
  import re
  from pathlib import Path

  data = Path("Game Name.n-gage").read_bytes()
  for part in data.split(b"--KBoundary")[1:]:
      head, blank, body = part.partition(b"\r\n\r\n")
      name = re.search(rb"Content-ID:\s*<([^>]+)>", head)
      if blank and name:
          if body.endswith(b"\r\n"):
              body = body[:-2]
          ext = ".sis" if b"sis" in head.lower() else ".xml"
          Path(name.group(1).decode() + ext).write_bytes(body)
  ```

- **Installing the game package** (`Game.sis`): like any `.sis` package in EKA2L1, or on
  a test copy through the [test API](#testing) (`POST /v1/apps` with `{"path": "<file>"}`;
  give it a path without accented letters, which it reads wrongly). EKA2L1 may install
  every option block of a package, because it doesn't evaluate some of their conditions.
- **The program** is the `.exe` the package puts in `sys\bin`, other than its small
  `AS_<UID>.exe` helper. A module needs one name per game, for example from its own INI.
- **Keep the N-Gage app installed.** The games load its libraries (`ngi*.dll`, `NAF*.dll`,
  `playclient*.dll`, `ArenaEnv.dll` and more). On a phone without them, `EKA2L1.log` says
  `Can't load <program>.exe: imported DLL ArenaEnv.dll not found`, and EKA2L1 shows its
  phone menu in a window instead of the game.
- **Not every game runs.** Of 26 games tried this way, 23 played (two of them close right
  after starting in some runs: start them again), and 3 didn't (a scrambled screen,
  garbled text, a crash at start). A few games that play show some of their text
  garbled.
- **Keys.** These games confirm with OK (the phone's centre key, a tick on screen), where
  the classic N-Gage games use 5: Block Breaker Deluxe ignores 5 in its menus and on
  "Press ✓ to start". Put OK (167) on the main panel button and the pad's Cross.
- **A separate EKA2L1 for this wheel.** The phones in one EKA2L1 share its C: and E:
  drives (`devices.yml`: `isolated-drives: false`), and every phone uses the same key
  file. A second portable copy of EKA2L1 for the N-Gage 2.0 wheel keeps the N85, its
  installed games and its keys apart from the classic N-Gage's.

## Testing

`--debug-control-port <port>` opens a loopback HTTP API, useful on a test copy: `GET
/v1/apps` lists the card's apps, `POST /v1/apps/<uid>/launch` starts one, `POST
/v1/input/key` with `{"keys":["5"],"action":"tap"}` presses a phone key, and `GET
/v1/screenshot` returns the emulated screen as a PNG (only for an app started through the
API). That can boot every card on a wheel and save a picture of each, also on a hidden
desktop, where a window capture can't see EKA2L1's OpenGL picture. Keep the port off on
the cabinet itself.

A game started with `--run` has no API session, so `GET /v1/screenshot` refuses it. Starting
a phone app that shows no window through the API afterwards (on the N85, `AcControl`,
`POST /v1/apps/0x2000A2AA/launch`) opens one, and the screenshots then show the game, which
stays in front.
