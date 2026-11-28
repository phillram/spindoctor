# Atari Jaguar games in BigPEmu

SpinDoctor doesn't install emulators or supply games. These notes are about running
Atari Jaguar cartridge games in BigPEmu from RocketLauncher. Checked with BigPEmu 1.221
on Windows 10: check again after an upgrade, on a copy first.

RocketLauncher has no stock BigPEmu module. Its Phoenix module powers a game on by
typing menu keys into Phoenix's window, and needs every game listed in Phoenix's own
library file (`phoenix.config.xml`). BigPEmu takes the game on its command line, so a
short module is enough: see [Starting games from RocketLauncher](#starting-games-from-rocketlauncher).

## Settings

With `-localdata` on the command line, BigPEmu keeps everything in a `UserData` folder
beside `BigPEmu.exe`: its settings (`BigPEmuConfig.bigpcfg`), cartridge saves
(`game<hash>_eeprom.bigpeep`) and save states. Without it, it uses `%APPDATA%\BigPEmu`.

- `BigPEmu.exe *null -localdata` opens BigPEmu with no game, which writes a settings file
  with the defaults; close it and edit that one. BigPEmu needs no Jaguar BIOS.
- The settings file is JSON. BigPEmu writes it back every time it closes (the recent
  files list, for one), so edit it only while BigPEmu is closed, and back it up first.
- A game started from the command line skips BigPEmu's intro.

What a cabinet usually wants:

| Section | Setting | Why |
|---|---|---|
| `Video` | `DisplayMode: 1` | A window (0 is a borderless window over the whole display, 2 full screen). The module then gives the window its place and size, for a bezel or the whole screen. |
| `Video` | `ScreenScaling: 0`, `ScreenFilter: 0` | The defaults: the picture fills the window and keeps the Jaguar's shape, with sharp pixels (filter 1 is bilinear). |
| `Input` | clear the default keyboard keys | They are letters a keyboard encoder sends for other buttons: see [Panel and pads](#panel-and-pads). |
| `Audio` | `VolumeAtten: 100` | Decibels of attenuation: silent. Only for a test copy run in the background. |

## Panel and pads

`Input` holds `Device0` to `Device7`, Jaguar controllers 1 to 8. Each has a `Bindings`
list of 51 entries in a fixed order, and each entry a list of `Triggers`, any of which
presses that input:

| Entries | Jaguar input |
|---|---|
| 0, 1, 2 | C, B, A |
| 3, 4 | Pause, Option |
| 5, 6, 7, 8 | Up, Down, Left, Right |
| 9–18 | Keypad 0–9 |
| 19, 20 | `*`, `#` |
| 21–36 | Analog and extra inputs (other device types) |
| 37–50 | Menu, Fast Forward, Rewind, Save State, Load State, Screenshot, Overlay, Pad Wheel, Chat, Reload Image, Pause/Resume, Step Frame, Exit, Fullscreen |

```json
"Device0": {
    "DeviceType": 0,
    "Bindings": [
        {"Triggers": [{"B_KB": true, "B_ID": 30, "B_AH": 0.0},
                      {"B_KB": false, "B_ID": 0, "B_AH": 0.0, "B_DevID": "<pad GUID>"}]},
        ...
        {"Triggers": [{"B_KB": true, "B_ID": 32, "B_AH": 0.0},
                      {"B_KB": false, "B_ID": 0, "B_AH": 0.0, "B_DevID": "<pad GUID>",
                       "M_KB": false, "M_ID": 131, "M_AH": 0.0, "M_DevID": "<pad GUID>"}]},
        ...
    ]
}
```

- **Keys** are `"B_KB": true` with the DirectInput scan code in `B_ID`: `30` A, `48` B,
  `46` C, `19` R, `31` S, `2`–`11` the number row's 1–0, `200` / `208` / `203` / `205` the
  arrows, `82` and `71`–`77` the number pad's 0 and 4–9.
- **Pad inputs** (the stock DirectInput plugin) are `"B_KB": false`, the device in
  `B_DevID`, and in `B_ID` a button number (from 0), an axis (`128` X, `129` Y, `130` Z,
  `131` Rx, `132` Ry, `133` Rz; `B_AH` `-1.0` or `1.0` for the direction) or the hat
  (`134`; `B_AH` `0.0` up, `0.25` right, `0.5` down, `0.75` left).
- **A hold** (`M_…`) is a second button held first: the trigger fires only with it. A
  button used as a hold can't also be a plain input, but the same button can appear with
  and without a hold.
- **`B_DevID`** is the pad's DirectInput instance GUID, as 32 hex digits in the byte
  order Windows stores it: the `GUID` value under
  `HKCU\System\CurrentControlSet\Control\MediaProperties\PrivateProperties\DirectInput\VID_<vid>&PID_<pid>\Calibration\<n>`.
  Slot 0 is the first pad of that kind. BigPEmu binds the pads it knows on its first
  start (controller 1 to slot 0, controller 2 to slot 1). A pad that later gets a new
  slot (re-paired, another PC) needs binding again, in BigPEmu's Input menu or in the file.
- **BigPEmu's default keys** are `A` `S` `D` (C B A), `Q` `W` (Pause, Option), the arrows,
  the number row (keypad), `O` `P` (`*` `#`), `Esc` (Menu), `F2` (Fast Forward) and `T`
  (network Chat). On a keyboard encoder those letters are other buttons: a coin button
  that sends `S` presses B, and a start button that sends `T` opens the chat box. Remove
  every default key trigger and bind the panel's keys.
- **The keypad doesn't fit a panel:** A, B, C, Pause, Option and 12 keypad keys. On a
  panel with two rows of four, the real pad's C B A plus `*` can take the top row and
  keypad 1, 2, 3 plus `#` the bottom row (many games use `*` + `#` together, often as a
  reset). Put the rest on number keys and on the pads.
- **A DualShock 4** (DS4Windows' DualShock 4 copy, `054C:05C4`) under DirectInput:
  buttons 0 Square, 1 Cross, 2 Circle, 3 Triangle, 4 L1, 5 R1, 8 Share, 9 Options, 10 L3,
  11 R3; L2 and R2 as the axes Rx (`131`) and Ry (`132`), which makes them good holds.
  BigPEmu's own layout for it: Square, Cross, Circle are C, B, A (the Jaguar pad's order,
  left to right), Share Pause, Options Option, L1 4, Triangle 5, R1 6, L3 `*`, R3 `#`;
  hold L2 for 1 2 3 (Square, Triangle, Circle), 7 8 9 (L1, Cross, R1) and 0 (R3); hold R2
  for the menu (Options), fast forward (Triangle) and the controls overlay (L3). Swapping
  Pause and Option puts Pause on Options, like Start elsewhere. Add the left stick
  (`129` / `128`, `-1.0` / `1.0`) to the D-pad entries so it moves too.
- **Pause and Option are game buttons.** Option opens a game's options, and some games
  go back to their start with it, so a pad's Share or a panel's coin button bound to it
  can look like a reset.

## Starting games from RocketLauncher

`Settings\Global Emulators.ini` (or the wheel's own `Emulators.ini`), and the wheel's
`Default_Emulator=BigPEmu`:

```ini
[BigPEmu]
Emu_Path=..\Emulators\BigPEmu\BigPEmu.exe
Rom_Extension=j64|jag|rom|abs|cof|zip|cue|cdi|bigpimg
Module=BigPEmu.ahk
```

The command line is `BigPEmu.exe "<game>" -localdata`, with the game first: other options
must come after it. For a window in a bezel's screen add `-noborder -windowx <x> -windowy
<y> -forcewidth <w> -forceheight <h>`, and for the whole screen the same with the screen's
size.

- **`-setcfgprop` / `-setcfgpropcat` don't suit per-start display choices.** They set a
  value for that run, but the display mode is applied after the window opens (it opened in
  the old mode), and the value is saved into the settings file when BigPEmu closes. Keep
  `DisplayMode: 1` in the file and pass the window's place and size each time.
- The game window's class is `BIGPEMU`. BigPEmu closes cleanly on `WinClose`.

The parts of a module that matter:

```autohotkey
BezelStart()	; with a bezel image: sets Fullscreen to false and works out the bezel's screen area
7z(romPath, romName, romExtension, 7zExtractPath)

If (bezelPath)
	geometry := " -noborder -windowx " . bezelScreenX . " -windowy " . bezelScreenY . " -forcewidth " . bezelScreenWidth . " -forceheight " . bezelScreenHeight
Else If (Fullscreen = "true")
	geometry := " -noborder -windowx 0 -windowy 0 -forcewidth " . A_ScreenWidth . " -forceheight " . A_ScreenHeight

gameWindow := "ahk_class BIGPEMU ahk_exe " . executable
Run(executable . " """ . romPath . "\" . romName . romExtension . """ -localdata" . geometry, emuPath)
WinWait(gameWindow)
WinActivate(gameWindow)
WinWaitActive(gameWindow)
BezelDraw()
FadeInExit()
Process("WaitClose", executable)
7zCleanUp()
BezelExit()
FadeOutExit()
ExitModule()

CloseProcess:
	FadeOutStart()
	WinClose(gameWindow)
Return
```

- RocketLauncher's log may show "ToggleMenu - Timed out trying to restore MenuBar" after
  `BezelDraw()`: BigPEmu's window has no menu bar, and nothing is wrong.
- **Jaguar CD:** BigPEmu also loads `.cue`, `.cdi` and its own `.bigpimg` disc images, but
  not `.chd`. Not checked here with RocketLauncher.

## Moving from Phoenix

- Put BigPEmu in its own folder, point the wheel at it, and keep Phoenix until the games
  pass.
- **Not carried over:** Phoenix's save states (BigPEmu can't load them) and its key
  setup. Bind the panel and pads again (see [Panel and pads](#panel-and-pads)).
- Phoenix's game library and the `<Dump>` paths its module rewrites aren't needed any more.
