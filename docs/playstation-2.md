# PlayStation 2 games in PCSX2 2.x

SpinDoctor doesn't install emulators or supply games. These notes are about running
PlayStation 2 games in PCSX2 2.x, the Qt build (`pcsx2-qt.exe`), from RocketLauncher.
Checked with PCSX2 2.8.2 on Windows 10: check again after an upgrade, on a copy first.

RocketLauncher's stock PCSX2 module was written for PCSX2 1.x (wxWidgets). It waits for
`wxWindowNR` windows, reads the frame rate from the window title to tell when a game has
started, edits `PCSX2_ui.ini` and `GSdx.ini`, and passes plugin options (`--gs=`,
`--pad=`, `--cfgpath=`). PCSX2 2.x has none of these, and copies of that module patched
for one Qt version (`Qt630QWindowIcon`, `Qt670QWindowIcon`, …) break at the next one. A
short module that finds the windows by program and by the game's title works across
versions: see [Starting games from RocketLauncher](#starting-games-from-rocketlauncher).

## Settings

An empty `portable.ini` (or `portable.txt`) beside `pcsx2-qt.exe` makes PCSX2 portable:
it then keeps everything in that folder (`inis\PCSX2.ini`, `bios`, `memcards`,
`sstates`, `cache`, `logs`). Without it, it uses `Documents\PCSX2`.

- When `inis\PCSX2.ini` is missing, or its `[UI]` `SettingsVersion` isn't `1`, PCSX2
  starts its setup wizard. `pcsx2-qt.exe -testconfig` writes a complete file with the
  defaults and exits without opening a window; edit that one, with
  `SetupWizardIncomplete = false`.
- PCSX2 writes the file back when it closes (window positions, play time), so edit it
  only while PCSX2 is closed, and back it up first.
- A control bound to two inputs is two lines with the same key: PCSX2 reads repeated
  keys as a list.

What a cabinet usually wants:

| Section | Setting | Why |
|---|---|---|
| `[UI]` | `ConfirmShutdown = false` | Otherwise closing the game window first asks whether to shut down, and the exit key leaves PCSX2 waiting on that question. |
| `[UI]` | `HideMouseCursor = true` | No pointer over the game. |
| `[AutoUpdater]` | `CheckAtStartup = false` | No update window. |
| `[Hotkeys]` | remove `OpenPauseMenu = Keyboard/Escape` | When Escape is RocketLauncher's exit key, PCSX2 would open its own menu first. |
| `[EmuCore/GS]` | `OsdMessagesPos = 0` | No on-screen messages ("Controller SDL-0 connected", game fixes applied, and so on). `OsdShowIndicators = false` hides the pause and fast-forward icons, and `[EmuCore]` `WarnAboutUnsafeSettings = false` the warnings about settings. |
| `[EmuCore/GS]` | `upscale_multiplier = 3`, `AspectRatio = 4:3` | About 1080p inside; `4:3` fills a 4:3 bezel's screen exactly (the default `Auto 4:3/3:2` gives some games 3:2). The fixes PCSX2's game list applies per game stay on. |
| `[EmuCore/GS]` | `Adapter = <GPU name>` | On a PC with two GPUs. The log (`logs\emulog.txt`) lists the names it found. |
| `[Filenames]` | `BIOS = <file name>` | The BIOS in `bios\`. |
| `[MemoryCards]` | `Slot1_Filename`, `Slot2_Filename` | A file card (`.ps2`) or a folder card (a folder with a card's name). |

## Panel and pads

```ini
[InputSources]
Keyboard = true
SDL = true

[Pad1]
Type = DualShock2
Cross = Keyboard/D
Cross = SDL-0/FaceSouth
Circle = Keyboard/E
Circle = SDL-0/FaceEast
Start = Keyboard/R
Start = SDL-0/Start
LUp = Keyboard/Up
LUp = SDL-0/-LeftY
Up = SDL-0/DPadUp
LargeMotor = SDL-0/LargeMotor
SmallMotor = SDL-0/SmallMotor
```

- **Keyboard keys** are `Keyboard/<key>`: `Keyboard/A`, `Keyboard/Up`, `Keyboard/Return`.
- **SDL pads** are `SDL-<n>/<input>`, `SDL-0` being the first pad. PCSX2 2.8 writes
  `FaceSouth` (Cross), `FaceEast` (Circle), `FaceWest` (Square), `FaceNorth`
  (Triangle), `LeftShoulder`, `RightShoulder`, `+LeftTrigger`, `+RightTrigger`, `Back`
  (Share), `Start` (Options), `Guide` (PS button), `LeftStick`, `RightStick`, the
  `DPad…` buttons and the axes `-LeftY` (up), `+LeftY`, `-LeftX` (left), `+LeftX`. To see
  the names another version uses, bind one button in its Controllers settings and look
  at the file. DS4Windows' DualShock 4 copies show up as `PS4 Controller`.
- **The panel works only while PCSX2's game window has the keyboard.** PCSX2 2.x reads
  keys from its own window, while SDL pads work in the background, so a lost focus shows
  as "the pad works, the panel does nothing". PCSX2 1.x's LilyPad could read keys in the
  background, so this often turns up only after an upgrade. After a start from a
  frontend (seen with HyperSpin), the focus can drop to no window at all some seconds
  after the game appears. Have the module hand it back while the game runs: see
  [Starting games from RocketLauncher](#starting-games-from-rocketlauncher).
- **Sticks.** An arcade stick is digital. Bound to the left analog stick (`LUp`,
  `LDown`, `LLeft`, `LRight`), it moves characters in 3D games that ignore the D-pad.
  Binding the same stick to the D-pad too can make one push do two things (moving and
  scrolling a menu that uses the D-pad), so give the D-pad another stick or leave it to
  the pads.

## Starting games from RocketLauncher

The wheel's `Settings\<System>\Emulators.ini`:

```ini
[ROMS]
Default_Emulator=PCSX2 2.8
[PCSX2 2.8]
Emu_Path=..\Emulators\PCSX2 2.8\pcsx2-qt.exe
Rom_Extension=gz|7z|zip|iso|bin|cue|chd|cso
Module=..\PCSX2 Qt\PCSX2 Qt.ahk
Pause_Save_State_Keys={F1 down}{F1 up}
Pause_Load_State_Keys={F3 down}{F3 up}
```

F1 saves to the current slot and F3 loads it (PCSX2's default hotkeys).

The command line is `pcsx2-qt.exe -batch -nogui -fastboot -- "<game>"`. `-nogui`
keeps the main window hidden and implies `-batch` (PCSX2 exits when the game closes),
`-slowboot` shows the BIOS screens instead of `-fastboot`, `-fullscreen` starts full
screen, and `--` ends the options, so a name with spaces or a leading dash is read as
the game.

The parts of a module that matter:

```autohotkey
Run(executable . " -batch -nogui -fastboot -- """ . romPath . "\" . romName . romExtension . """", emuPath)

; The game window: visible, titled with the game. "PCSX2 v2.x" is the hidden main window.
gameWinID := ""
DetectHiddenWindows, Off
Loop, 240	; up to 120 s: a .gz game's first start builds its index first
{
	WinGet, pcsx2Wins, List, ahk_exe %executable%
	Loop, %pcsx2Wins%
	{
		thisWinID := pcsx2Wins%A_Index%
		WinGetTitle, thisWinTitle, ahk_id %thisWinID%
		If (thisWinTitle != "" && !RegExMatch(thisWinTitle, "^PCSX2"))
		{
			gameWinID := thisWinID
			Break
		}
	}
	If gameWinID
		Break
	Sleep, 500
}
WinActivate("ahk_id " . gameWinID)
WinWaitActive("ahk_id " . gameWinID,, 30)
BezelDraw()
FadeInExit()
SetTimer, KeepPCSX2Focus, 500
Process("WaitClose", executable)
7zCleanUp()
BezelExit()
FadeOutExit()
ExitModule()
Return

KeepPCSX2Focus:
	If !WinExist("ahk_id " . gameWinID)
		SetTimer, KeepPCSX2Focus, Off
	Else If !WinActive("ahk_id " . gameWinID) && (Pause_Active != true)
	{
		WinGet, focusExe, ProcessName, A
		If (focusExe != "RocketLauncher.exe")	; leave its Pause menu, fade and bezel alone
			WinActivate, ahk_id %gameWinID%
	}
Return

CloseProcess:
	SetTimer, KeepPCSX2Focus, Off
	FadeOutStart()
	If WinClose("ahk_exe " . executable,,10)
		Process("Close", executable)
Return
```

- **Wait for the game's window, not the program's first window.** PCSX2's main window
  (`PCSX2 v2.8.2`) exists from the start even with `-nogui`, only hidden, and
  RocketLauncher also sees hidden windows. A plain `WinWait ahk_exe pcsx2-qt.exe`
  returns that window at once, so `BezelDraw()` moves the wrong window and the game
  comes up at its default size in the middle of the screen. The game window's title is
  the game's name from PCSX2's own list.
- **Bezels.** Start in a window (no `-fullscreen`), so `BezelDraw()` can move it into the
  bezel's screen and remove its border. With bezels off, pass `-fullscreen`.
- **Keep the focus** with a timer, for the reason in [Panel and pads](#panel-and-pads).
  It hands the keyboard back only when nothing has it or another program (the
  frontend) took it, never from RocketLauncher's own Pause menu.
- **Close** with `WinClose`: with `ConfirmShutdown = false` PCSX2 exits within a second.
  Ending the process is only a fallback, because PCSX2 writes folder memory cards out
  as it closes.

## Compressed games

- **`.gz`:** the first time PCSX2 opens a `.gz` game it builds an index
  (`<game>.gz.pindex.tmp` beside the game, set by `[EmuCore]` `GzipIsoIndexTemplate`),
  about 10 seconds per GB, and the game window appears only after that. An index left by
  PCSX2 1.x is rebuilt ("Unexpected size of gzip index" in the log). It happens once per
  game, so give the module's wait (and any launch test) room for it.
- **`.zip` / `.7z`:** PCSX2 can't open them; RocketLauncher's 7z unpacks them first.
- **`.chd`, `.cso`:** opened directly.

## Moving from PCSX2 1.x

- Put 2.x in a new folder beside the old one, point the wheel's emulator entry at it, and
  keep the old folder until the games pass.
- **BIOS:** copy the `bios` folder: the `.bin` with its `.nvm` (the console's own
  settings, language among them) and `.mec` files.
- **Memory cards:** copy `memcards`. File cards and folder cards both work; name them in
  `[MemoryCards]`.
- **Not carried over:** save states (1.x states don't load), LilyPad binds, GSdx picture
  settings and per-game `--cfgpath` folders. Rebind the panel and pads and set the
  picture again.
- A PCSX2 1.6 copy kept for light-gun games (GunCon 2 through a mouse-patched build) can
  stay beside 2.x with its own emulator entry and module.
