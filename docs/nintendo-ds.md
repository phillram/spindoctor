# Nintendo DS games in melonDS

SpinDoctor doesn't install emulators or supply games. These notes are about running
Nintendo DS games, and DSi games, in melonDS 1.x from RocketLauncher. Checked with
melonDS 1.1 on Windows 10 (DS games; DSi mode needs the console's own files, which this
check didn't have): check again after an upgrade, on a copy first.

RocketLauncher has no stock melonDS module, and melonDS's command line has no options
for screens, keys or console type. They are all in its settings file, so the module
edits that file before each start.

## Settings

The Windows build is portable: it keeps `melonDS.toml` beside `melonDS.exe` (or in a
`portable` folder there, if one exists). melonDS reads the file as it starts and writes
all of it back when it closes:

- Edit it only while melonDS is closed, or the edit is lost. Back it up first.
- melonDS keeps your values and comments, but it may write the keys in another order.
  Find a setting by its own line (`ScreenRotation = 0`), not by its position.
- A key that isn't in the file uses melonDS's default.

| Table | Setting | What it does |
|---|---|---|
| `[Instance0.Window0]` | `ScreenLayout = 0` | Natural: the top screen above the touch screen, or beside it when the screens are turned. |
| `[Instance0.Window0]` | `ScreenRotation = 0` | `0` to `3` = 0°, 90°, 180° or 270° clockwise. `3` suits book-style games held sideways: top screen on the left, touch screen on the right. |
| `[Instance0.Window0]` | `ScreenGap = 5` | Pixels between the two screens, at the DS's own resolution. |
| `[Instance0.Window0]` | `ScreenSizing = 0` | Both screens the same size. |
| `[Instance0.Window0]` | `ScreenFilter = true` | Smooth scaling. In 1.x this is a per-window setting; `[Screen]` `Filter` no longer decides it. |
| `[3D]` | `Renderer = 2` | `0` software, `1` OpenGL, `2` OpenGL compute shader. The OpenGL ones need `[Screen]` `UseGL = true`. |
| `[3D.GL]` | `ScaleFactor = 4` | Draws 3D at 4× the DS's resolution (OpenGL renderers only). |
| `[JIT]` | `Enable = true` | Runs faster on older CPUs. |

`-f` on the command line starts melonDS in full screen. It has no "are you sure" box on
closing, and a double-click doesn't leave full screen.

The touch screen takes the mouse's left button: press on the touch screen and drag.
melonDS has no key or pad button for touching, so a trackball's left button works well.
`[Mouse]` `Hide = true` with `HideSeconds = 3` hides the pointer once it stops; with
`Hide_Cursor=custom` RocketLauncher can show a stylus cursor, as for
[3DS games](nintendo-3ds.md#screens-and-full-screen).

## Panel and pad

Keys are under `[Instance0.Keyboard]` and pad binds under `[Instance0.Joystick]`, named
after the DS buttons (`A`, `B`, `X`, `Y`, `L`, `R`, `Start`, `Select`, `Up`, `Down`,
`Left`, `Right`) and melonDS's hotkeys (`HK_Pause`, `HK_FastForward`, `HK_Mic`, `HK_Lid`
and others). `-1` binds nothing, and a new file binds nothing at all, so set every
button. Each button takes one key and one pad bind, and both work at the same time.

**Keys** are Qt key codes, as in [Azahar](nintendo-3ds.md#panel-and-pads): a letter is
its capital's character code, the arrows are 16777234 (Left), 16777235 (Up), 16777236
(Right) and 16777237 (Down), and Tab is 16777217.

**The pad** is one SDL joystick: `JoystickID` under `[Instance0]`, counted from 0. With
DS4Windows' DualShock 4 copies that is the pad turned on first. melonDS reads SDL's raw
joystick numbers, not the game-controller names other emulators show. A PS4 pad (or
DS4Windows' copy) through SDL 2.32:

- **Buttons:** Cross 0, Circle 1, Square 2, Triangle 3, Share 4, PS 5, Options 6, L3 7,
  R3 8, L1 9, R1 10, and the D-pad as buttons: Up 11, Down 12, Left 13, Right 14.
- **Axes:** the left stick 0 (across) and 1 (up is negative), the right stick 2 and 3,
  L2 4 and R2 5.

A bind is one number:

- a button: its number;
- an axis: `0x10000 + axis × 0x1000000 + direction × 0x100000 + 0xFFFF`, where the
  direction is `0` positive, `1` negative or `2` trigger (pressed past halfway);
- a button or an axis: the axis value with the button's number in place of `0xFFFF`.

With the DS's own button positions (A on Circle, B on Cross, X on Triangle, Y on Square):

| DS button | Bind | Value |
|---|---|---|
| A, B, X, Y | Circle, Cross, Triangle, Square | `1`, `0`, `3`, `2` |
| Start, Select | Options, Share | `6`, `4` |
| L | L1 or L2 | `69271561` |
| R | R1 or R2 | `86048778` |
| Up | D-pad or left stick | `17891339` |
| Down | D-pad or left stick | `16842764` |
| Left | D-pad or left stick | `1114125` |
| Right | D-pad or left stick | `65550` |

**Microphone and lid.** Some games want the player to blow into the microphone or close
the lid. `HK_Mic` blows while it is held, if `[Mic]` `InputType = 2` (melonDS's own
noise); with the default, an external microphone, it does nothing on a PC without one.
`HK_Lid` closes the lid on one press and opens it on the next.

**Button lights.** `ledblinky profiles` reads a DS wheel's keys from DeSmuME's
`desmume.ini` only. With melonDS it finds none for the wheel, so keep or edit the wheel's
LEDBlinky section by hand.

## Starting games from RocketLauncher

The wheel's `Settings\<System>\Emulators.ini`:

```ini
[ROMS]
Default_Emulator=melonDS
[melonDS]
Emu_Path=..\Emulators\melonDS\melonDS.exe
Rom_Extension=7z|zip|rar|nds
Module=melonDS.ahk
Pause_Save_State_Keys={Shift down}{F1 down}{F1 up}{Shift up}|{Shift down}{F2 down}{F2 up}{Shift up}
Pause_Load_State_Keys={F1 down}{F1 up}|{F2 down}{F2 up}
```

**Save states** are Shift+F1 to Shift+F8 (save) and F1 to F8 (load), and they work in
full screen. Shift+F9 and F9 open a file box instead, so list slots 1 to 8 at most in
the pause menu's keys.

The parts of a module that matter:

```autohotkey
MelonDSSetToml(emuPath . "\melonDS.toml", "ConsoleType", consoleType, "ScreenRotation", screenRotation)
7z(romPath, romName, romExtension, 7zExtractPath)
gameWindow := "melonDS ahk_exe " . executable
Run(executable . " -f """ . romPath . "\" . romName . romExtension . """", emuPath)
WinWait(gameWindow,, 60)
WinActivate(gameWindow)
```

- **Per-game screens and console type.** The module reads its own values (for example
  `Rotation = 270` in a `[game name]` section of the module's INI) and writes them into
  `melonDS.toml` before `Run`: `ScreenRotation` (`0` to `3`) and `ConsoleType` (`0` DS,
  `1` DSi; see [DSi mode](#dsi-mode)). Replace the number on the key's own line, for
  example with `RegExReplace(text, "m)^(\s*ConsoleType\s*=\s*)\d+", "${1}" . value)`,
  and write the file back as UTF-8 without a BOM in binary mode
  (`FileAppend, %text%, *%tmp%, UTF-8-RAW`, then `FileMove` over the original), so its
  line endings stay as they are.
- **Wait for the window by its title.** It is `melonDS 1.1` until a game runs, then
  `[60/60] melonDS 1.1` with the frame rate in front. RocketLauncher matches titles that
  contain the text and also sees hidden windows, so wait for `melonDS` with `ahk_exe`
  rather than `ahk_exe` alone. Close that window in `CloseProcess`; melonDS saves its
  settings as it closes.

## Saves

melonDS names a save after the `.nds` file, so a zipped game's save is named after the
`.nds` inside the zip: `<SaveFilePath>\<name>.sav`. With `SaveFilePath` empty the save
goes beside the file melonDS opened: beside its archive, or, when RocketLauncher's 7z
unpacked the game, into the unpacked copy, which `7zCleanUp()` then deletes. Set
`SaveFilePath` (and `SavestatePath`) under `[Instance0]` to an absolute path; a relative
one is read from the folder melonDS was started in.

melonDS takes each game's save type and size from its own game list and copies in what
the save file holds, so a save smaller or larger than the chip still loads.

### Saves from DeSmuME

DeSmuME's `.dsv` is the raw save followed by a 122-byte footer: the text
`|<--Snip above here to create a raw sav by excluding this DeSmuME savedata footer:`, six
32-bit numbers and `|-DESMUME SAVE-|`. Check that the file ends with that, cut off the
last 122 bytes and name the rest `<name>.sav`. DeSmuME names a `.dsv` after the `.nds`
too, so the names carry over unless the game file was renamed since. DeSmuME's save
states (`.ds0` to `.ds9`) can't be loaded by melonDS.

## DSi mode

`[Emu]` `ConsoleType = 1` runs a DSi. It is one setting for every game, so a module can
set it per wheel or per game before each start and one melonDS can serve both a DS and a
DSi wheel. DSi mode needs files dumped from a real DSi, named under `[DSi]`:
`BIOS9Path`, `BIOS7Path` and `NANDPath` (relative paths are read from melonDS's own
folder). `FirmwarePath` is read only when `[Emu]` `ExternalBIOSEnable = true`. DS mode
needs none of these: without `ExternalBIOSEnable` it uses melonDS's own BIOS and
firmware.
