# PlayStation Vita games in Vita3K

SpinDoctor doesn't install emulators or supply games. These notes are about running
PlayStation Vita games in Vita3K from RocketLauncher. Checked with Vita3K 0.2.1
(continuous build 4445) on Windows 10: check again after an upgrade, on a copy first.

RocketLauncher has no stock Vita3K module. Vita3K runs games that are installed in its
own Vita file system, by their title ID, so a short module is enough: see
[Starting games from RocketLauncher](#starting-games-from-rocketlauncher). The wheel's game
files are only checked by RocketLauncher, never unpacked.

## Settings

Vita3K is portable when a `portable` folder sits beside `Vita3K.exe`. Everything then
stays in that folder:

| Path | What it holds |
|---|---|
| `portable\config.yml` | The settings, keys and pad binds. |
| `portable\fs` | The Vita file system: firmware in `os0`, `vs0` and `sa0`, games in `ux0\app\<title ID>`, saves in `ux0\user\00\savedata`. |
| `portable\vita3k.log` | The log of the last start. |

**Firmware.** Vita3K needs two files from Sony's update servers: the firmware
(`PSVUPDAT.PUP`) and the font package (a smaller `PSP2UPDAT.PUP`, the system fonts).
Without the fonts, text is missing in some games. Install each from the command line:

```bat
Vita3K.exe --version
Vita3K.exe --firmware "<folder>\PSVUPDAT.PUP"
Vita3K.exe --firmware "<folder>\PSP2UPDAT.PUP"
```

`--firmware` installs and quits without opening a window. Start these from Vita3K's own
folder, and run `--version` once first: it writes `portable\config.yml`. On a very first
run with no `config.yml`, `--firmware` returns before Vita3K has set its file system path,
so it may not install into `portable\fs`.

What a cabinet usually wants in `config.yml` (edit it while Vita3K is closed):

| Setting | Why |
|---|---|
| `initial-setup: true`, `show-welcome: false` | No setup wizard or welcome window at the first start. |
| `check-for-updates-mode: 0` | No update check (1 asks at every start). |
| `discord-rich-presence: false` | No Discord status. |
| `show-compile-shaders: false` | No "N pipelines compiled" notice in a corner while shaders build. |
| `pref-path: ""` | In portable mode the file system is always `portable\fs`; an absolute path here is left from a start without `-w`. |
| `log-level: 2` | Info. The default `0` (trace) writes a very large log. |

## Games

Vita3K installs `.vpk` and `.zip` app folders (decrypted, or NoNpDrm dumps with a
license), `.pkg` files with their zRIF, and `.vci` cartridge images. A folder can be
installed from the command line too: `Vita3K.exe "<app folder>"` copies it into
`ux0\app\<title ID>`, decrypts a NoNpDrm dump with its `sce_sys\package\work.bin`, and then
starts it. The title ID is the folder name, for example `PCSA00011`.

### No-Intro cartridge images (.psv)

No-Intro's Vita set holds raw cartridge images named `.psv`. They start with the card's
own partition table ("Sony Computer Entertainment Inc."), not with the header of the
PSVGameSD dumper's `.psv`, which held the cartridge key. Inside, the game partition (exFAT)
has the game in `app\<title ID>` and the card's license in `license\app\<title ID>\*.rif`,
and that license can only be opened with the cartridge key. So Vita3K can't install these
images as they are, and they can't be turned into a `.vci` either: a `.vci` keeps the
cartridge's own key data.

What works for each game, from your own console:

- A `.vci` dump of the cartridge (GcToolKit on a Vita with HENkaku or Enso). Vita3K
  installs it directly.
- The game's NoNpDrm license. NoNpDrm writes one when the game runs on such a Vita; a
  NoNpDrm dump has it as `sce_sys\package\work.bin`. It is 512 bytes, with the bytes
  `EF CD AB 89 67 45 23 01` at offset 8 (NoNpDrm's account ID), and its content ID at
  offset 0x10 must match the one in the cartridge's license. Copy the image's `app\<title ID>`
  folder out of the exFAT partition, add the license as `sce_sys\package\work.bin`, and
  install that folder. The game files are the same ones the cartridge holds; Vita3K
  decrypts them on install.

A license from the PSN release fits only when its content ID is the same as the
cartridge's, so compare them first. A whole NoNpDrm dump installs by itself either way.

## Starting games from RocketLauncher

```bat
Vita3K.exe --frontend sdl -w -r PCSA00011 -F
```

| Argument | What it does |
|---|---|
| `--frontend sdl` | A plain game window that runs the game given with `-r` and quits with it. Without it, Vita3K's library window opens too. |
| `-w` | Keeps `config.yml` as it is. Without it, every start writes the file back, with an absolute `pref-path`. |
| `-r <title ID>` | The installed game to start (its folder under `ux0\app`). |
| `-F` | Full screen. |

The game window's class is `SDL_app` and its title is `<game title> (<title ID>)`, so a
module can wait for `(<title ID>) ahk_class SDL_app ahk_exe Vita3K.exe`. Closing that window
ends the game, and Vita3K quits. Esc does nothing in the game window except close the
Vita's on-screen keyboard, so RocketLauncher's exit key needs the module to close the
window.

A module only has to map each wheel game to its title ID (an INI section per game is
enough) and check that `portable\fs\ux0\app\<title ID>\eboot.bin` is there. It must not
unpack the wheel's archive.

## Panel and pads

**Keys** are in `config.yml`, one line per Vita control, with key names such as `KeyA`,
`ArrowUp`, `Enter` and `Unbound`; each control also has a `-alt` line for a second key.
The defaults use letters a keyboard encoder sends for other buttons, so check every line:

| Line | Default |
|---|---|
| `keyboard-button-cross` / `-circle` / `-square` / `-triangle` | `KeyX`, `KeyC`, `KeyZ`, `KeyV` |
| `keyboard-button-l1` / `-r1` | `KeyQ`, `KeyE` |
| `keyboard-button-l2` / `-r2` / `-l3` / `-r3` (PlayStation TV only) | `KeyU`, `KeyO`, `KeyF`, `KeyH` |
| `keyboard-button-start` / `-select` | `Enter`, `ShiftRight` |
| `keyboard-leftstick-*` / `keyboard-rightstick-*` | `W A S D` / `I J K L` |
| `keyboard-button-psbutton`, `keyboard-gui-toggle-touch` | `KeyP`, `KeyT` |

`keyboard-button-up` and the other D-pad lines start on the arrow keys. One way on a panel
with two sticks: player 1's stick as the left stick, player 2's as the right stick, the
face buttons and L/R on player 1's buttons, and the D-pad on four of player 2's buttons.
Set the lines a panel doesn't use to `Unbound`.

**PS4 pads** are SDL game controllers. The default `controller-binds` match the Vita's
buttons (Share is Select, Options is Start), the touchpad is the front touch screen, and
the pad's gyro and accelerometer are the Vita's motion sensors. The log says
"Controller has motion support" when it finds them. This works with DS4Windows'
DualShock 4 output ([PS4 pads with HidHide](ps4-pads.md)).

**Touch with a mouse or trackball:** in the game window, the left button touches the front
screen and the right button the rear touch pad, where the pointer is. RocketLauncher's
`Hide_Cursor=true` hides that pointer. `Hide_Cursor=custom` in the wheel's
`Settings\<System>\RocketLauncher.ini` shows a cursor from
`RocketLauncher\Media\Cursors\<System>\_Default\` instead; with no cursor file there,
RocketLauncher leaves the normal pointer showing.

## Testing

A launch on a hidden Windows desktop works, but pictures of a Vulkan game window taken
there with `PrintWindow` come out black. Judge such a test by the window title and the log: "Game started"
and, after a close, "Shutting down game". Keep a test quiet with `audio-volume: 0` in a
copy's `config.yml` rather than muting `Vita3K.exe` in Windows, which remembers a
program's mute.
