# Nintendo 3DS games in Azahar

SpinDoctor doesn't install emulators or supply games. These notes are about running
Nintendo 3DS games in Azahar, Citra's successor, from RocketLauncher. Checked with
Azahar 2127.0 on Windows 10: check again after an upgrade, on a copy first.

Azahar is portable when a `user` folder sits beside `azahar.exe`: it then keeps its
settings, saves and system files there instead of in AppData. The settings are in
`user\config\qt-config.ini`. Close Azahar and back the file up before editing it.

## A setting that doesn't take

Each setting in `qt-config.ini` has two lines:

```ini
screen_gap\default=false
screen_gap=5
```

While its `\default` line says `true`, Azahar uses its own default and ignores the value
under it, so editing the value alone changes nothing. Set both lines.

Azahar writes `\default=true` back whenever it saves a value equal to its default. So a
module that sets something before each start, such as the input profile, writes both
lines every time.

## Screens and full screen

| Section | Setting | What it does |
|---|---|---|
| `[Layout]` | `layout_option=0` | The top screen above the touch screen, like the console. `2` shows one screen large and the other small. |
| `[Layout]` | `screen_gap=5` | Pixels between the two screens. |
| `[Renderer]` | `resolution_factor=3` | Draws at 3× the console's resolution. |
| `[UI]` | `fullscreen=true` | Starts in full screen; the `-f` argument does too. |
| `[UI]` | `confirmClose=false` | No "are you sure" box when RocketLauncher closes it. |

Esc leaves full screen by default. If Esc is on the panel, clear that shortcut:
`Shortcuts\Main%20Window\Exit%20Fullscreen\KeySeq=` (empty).

The touch screen takes the mouse. `Hide_Cursor=true` in the wheel's
`Settings\<System>\RocketLauncher.ini` hides the pointer the player needs there;
`Hide_Cursor=custom` shows a cursor from `RocketLauncher\Media\Cursors\<System>\`
instead, such as a stylus.

## Panel and pads

Input profiles are under `[Controls]`: `profiles\size`, then `profiles\1\name`,
`profiles\1\button_a` and so on, counted from 1. `profile=` picks the one in use and
counts from 0, so `profile=0` is `profiles\1`.

**Keys** are Qt key codes. A letter is its capital's character code, and the arrows are
16777234 (Left), 16777235 (Up), 16777236 (Right) and 16777237 (Down). `code:0` binds
nothing.

```ini
profiles\1\button_a\default=false
profiles\1\button_a="code:69,engine:keyboard"
```

Azahar's default keys include letters a panel often sends: `button_home` (B),
`button_power` (V), `button_debug` (O), `button_gpio14` (P), the C-stick (I, J, K, L)
and the circle pad's half-tilt modifier (D). Clear the ones your panel uses. Inside the
circle pad's value, `$0` stands for `:` and `$1` for `,`:

```ini
profiles\1\circle_pad="down:code$016777237$1engine$0keyboard,engine:analog_from_button,left:code$016777234$1engine$0keyboard,modifier:code$00$1engine$0keyboard,modifier_scale:0.500000,right:code$016777236$1engine$0keyboard,up:code$016777235$1engine$0keyboard"
```

**PS4 pads** work through SDL's game-controller numbering. With `maptype:all`, the pad on
`port:0` answers whatever its GUID, so the profile needs no pad ID:

```ini
profiles\2\button_a="api:controller,button:1,engine:sdl,guid:0,maptype:all,port:0"
profiles\2\button_zl="api:controller,axis:4,direction:+,engine:sdl,guid:0,maptype:all,port:0,threshold:0.500000"
profiles\2\circle_pad="api:controller,axis_x:0,axis_y:1,deadzone:0.100000,engine:sdl,guid:0,maptype:all,port:0"
```

The buttons are Cross 0, Circle 1, Square 2, Triangle 3, Share 4, Options 6, L1 9, R1 10
and the D-pad 11 to 14 (Up, Down, Left, Right). The axes are the left stick 0 and 1, the
right stick 2 and 3, L2 4 and R2 5. For the 3DS's own button positions: A on Circle,
B on Cross, X on Triangle, Y on Square.

**One source per button.** Each 3DS button takes one binding, so a profile is either the
panel or the pad. The module can pick before each start, when it knows whether a pad is
on (`padOn`, found as in [Xbox games](xbox.md#ps4-pads)):

```autohotkey
IniWrite("false", azaharIni, "Controls", "profile\default")
IniWrite(padOn ? "1" : "0", azaharIni, "Controls", "profile")
```

The pad has to be on before the game starts.

## Starting games from RocketLauncher

The wheel's `Settings\<System>\Emulators.ini`:

```ini
[ROMS]
Default_Emulator=Azahar
[Azahar]
Emu_Path=..\Emulators\Azahar\azahar.exe
Rom_Extension=3ds|cci|zip
Module=Azahar.ahk
```

The parts of the module that matter:

```autohotkey
7z(romPath, romName, romExtension, 7zExtractPath,,,keepUnpacked = "true")
gameWindow := "| ahk_exe " . executable
Run(executable . " -f """ . romPath . "\" . romName . romExtension . """", emuPath)
WinWait(gameWindow,, 60, "Secondary Window")
WinActivate(gameWindow,, "Secondary Window")
```

**Wait for the game's own window.** Azahar keeps hidden helper windows, one titled just
`Azahar` and another ending in `| Secondary Window`. RocketLauncher's window commands see
hidden windows, so waiting for `ahk_exe azahar.exe` alone finds a helper straight away.
The game's window is titled `Azahar 2127.0 | <game>`: wait for the `|` and leave out
`Secondary Window`. Close that window the same way in `CloseProcess`. If there is no game
window (an error box instead), close the process.

## Games

- **Decrypted dumps only.** Azahar runs decrypted `.3ds` and `.cci` files. An encrypted
  one stops at a message that the application is encrypted.
- **`.cia` files are installers.** Azahar installs them into its own system storage and
  runs them from its game list; RocketLauncher can't start one by its path.
- **Keep the games unpacked.** 3DS games run to several GB, so unpacking a zip takes a
  while at every start. Point the wheel's `7z_Extract_Path` (under `[7z]` in its
  `RocketLauncher.ini`) at a big drive, and keep what is unpacked there:
  - `7z()`'s seventh argument, `AllowLargerFolders`, reuses a kept folder even if it has
    grown since.
  - Don't call `7zCleanUp()` after the game: it deletes all but the last few
    (`7z_Games_to_Keep`; see [unpacked games](xbox.md#unpacked-games)).

  A kept game starts in seconds. A whole wheel of about 160 games took about 190 GB.
