# PS4 pads with DS4Windows and HidHide

SpinDoctor doesn't install DS4Windows or HidHide, or change their settings. These notes
are about two PS4 pads (DualShock 4) beside a keyboard-encoder panel, with DS4Windows
handing games a virtual DualShock 4 for each pad. Checked with DS4Windows 3.5,
ViGEmBus 1.22 and HidHide 1.5.230 on Windows 10, both pads on Bluetooth. The
[DS4Windows example](controller-input.md) shows the other common setup, with Xbox 360
output in games.

## Xbox 360 or DualShock 4 output

Each DS4Windows profile picks what games get (`OutputContDevice` in the profile file):

| Output | Games see | Bind emulators through |
|---|---|---|
| Xbox 360 (`X360`) | An Xbox 360 pad through XInput; DirectInput and SDL see it too, with Xbox button numbers | XInput, or the emulator's Xbox pad profile |
| DualShock 4 (`DS4`) | A PS4 pad, `054C:05C4` (the first DualShock 4 model), through DirectInput and SDL; SDL names it "PS4 Controller" | SDL or DirectInput. An emulator that reads only XInput doesn't see it: [pads as panel keys](#pads-as-panel-keys). |

- **Use one output type in every profile.** Switching between a profile on one type and a
  profile on the other unplugs the virtual pad and plugs in a new one each time.
- **A "DInput only" profile** (`<DinputOnly>True</DinputOnly>`) makes no virtual pad: it
  only sends the keys it maps. That suits the frontend's menus and
  [pads that press the panel's keys](#pads-as-panel-keys).

The rest of this page is about DualShock 4 output.

## Each pad once: HidHide

DS4Windows doesn't take the real pads away. Games see each real pad (`054C:09CC` for a
DualShock 4 v2) and DS4Windows' copy of it, so two pads show up as four, in an order that
can change from one start to the next. An emulator bound to "pad 2" then gets a copy of pad
1, or a real pad, which DS4Windows reads as well. HidHide hides chosen devices from every
program except the ones on its allow list.

With HidHide installed (it needs a restart), from its command-line client:

```powershell
$cli = 'C:\Program Files\Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe'
& $cli --dev-gaming
& $cli --app-reg 'D:\Arcade\Utilities\DS4Windows\DS4Windows.exe'
& $cli --dev-hide '<device instance path of pad 1>' --dev-hide '<device instance path of pad 2>'
& $cli --cloak-on
```

`--dev-gaming` lists the game devices with their instance paths; a Bluetooth DualShock 4
v2's starts with `HID\{00001124-0000-1000-8000-00805f9b34fb}_VID&0002054c_PID&09cc`.

- **DS4Windows goes on the allow list,** or it loses the pads it reads.
- **So does any program that needs the real pads,** by its full path. Cxbx-Reloaded binds
  the real pads through SDL ([Xbox games](xbox.md#ps4-pads)): `cxbx.exe` and
  `cxbxr-ldr.exe` in each Cxbx-R folder. A RocketLauncher module that counts the real pads
  before a start needs `RocketLauncher.exe` and `RocketLauncherGame.exe` on it too. A
  program moved to another folder needs adding again (`--app-list` shows the list).
- **A new or re-paired pad** needs hiding again (`--dev-list` shows the hidden ones).
- **Check what a game sees** with a program that isn't on the list. Through Windows'
  joystick API (`joyGetDevCaps`) it should find one `054C:05C4` per pad that is on, and no
  `054C:09CC`.
- **Undo:** `--cloak-off` shows the real pads again and changes nothing else.

## Pad numbers

- **Pad 1 is the pad turned on first** (DS4Windows' slot 1), pad 2 the next.
- **SDL** lists both copies as "PS4 Controller", index 0 for pad 1: Dolphin's
  `SDL/0/PS4 Controller` and `SDL/1/PS4 Controller`, DuckStation's and PCSX2's `SDL-0`
  and `SDL-1`.
- **DirectInput** numbers a copy's buttons 0 Square, 1 Cross, 2 Circle, 3 Triangle, 4 L1,
  5 R1, 6 L2, 7 R2, 8 Share, 9 Options, 10 L3, 11 R3 (L2 and R2 are axes too). An Xbox 360
  pad's are 0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB, 6 Back, 7 Start, so binds made for one are
  wrong on the other: Start on button 7 is R2 on a DualShock 4.
- **Check the numbers again after hiding the real pads.** Binds made while games saw four
  pads can point too high: on the cabinet checked, Dolphin's GameCube player 2 had to go
  from `SDL/2` to `SDL/1` and its Wii Remote 1 from `SDL/1` to `SDL/0`. Dolphin's saved
  controller profiles keep their own device lines, so change those too.

## The frontend's menus with both pads

HyperSpin reads keys. Give `HyperSpin.exe` an Auto Profiles rule with a DInput-only profile
of menu keys on Controller 1 and on Controller 2 (the [DS4Windows example](controller-input.md#profiles)
has a key table). The same profile on both lets either pad drive the menus; a profile with
HyperSpin's player 2 keys works too.

- **Leave neither controller at `(none)`.** That pad then keeps its default profile in the
  menus: it drives nothing there, and its game copy stays plugged in.
- **The copies come back as a game starts.** While HyperSpin is in front, neither pad has a
  game copy. When it leaves the front, DS4Windows switches each pad back to its default
  profile (DualShock 4 output) and plugs both copies in again, slot 1 first; on the cabinet
  checked that was about 2 s before RetroArch looked for pads. An emulator that looks
  only at the moment it starts can miss them: [Cxbx-Reloaded](xbox.md#ps4-pads).

## Emulators and the DualShock 4 copies

| Emulator | Reads the copies through | Notes |
|---|---|---|
| RetroArch 1.22 | `input_joypad_driver = "dinput"` and its `autoconfig\dinput\DUALSHOCK_4.cfg` profile | Its `sdl2` driver (SDL 2.0.14 in the Windows build checked) listed no DS4Windows copies, even with `SDL_JOYSTICK_HIDAPI=0`, while `dinput` found both. Leave the pad binds `nul` so the profile applies, and keep the panel's keys beside them. |
| Dolphin | SDL | See [pad numbers](#pad-numbers). |
| DuckStation | SDL (`SDL-0`, `SDL-1`) | Panel keys and pad binds side by side in `settings.ini`. |
| PCSX2 2.x | SDL (`SDL-0`, `SDL-1`) | [PS2 panel and pads](playstation-2.md#panel-and-pads). |
| PPSSPP 1.20 | Its own DualShock 4 reader (device `10` in `controls.ini`), the first pad it finds | Its DirectInput list leaves `054C:05C4` out. One pad, all a PSP needs. |
| WinUAE 6.x | Raw HID, by each copy's device name | WinUAE 3.x drops the binds when RocketLauncher starts it: [Amiga CD32 controls](troubleshooting.md#amiga-cd32-controls-do-nothing-winuae). |
| melonDS 1.x | SDL's raw joystick numbers | [DS panel and pad](nintendo-ds.md#panel-and-pad). |
| Flycast 2.x | SDL | [Flycast panel and pads](sega-dreamcast-naomi.md#panel-and-pads). |
| BigPEmu | DirectInput, by instance GUID | [Jaguar panel and pads](atari-jaguar.md#panel-and-pads). |
| Azahar | SDL; a profile is the panel or the pad | [3DS panel and pads](nintendo-3ds.md#panel-and-pads). |
| Vita3K | SDL; the touchpad is the front touch screen, the gyro the motion sensor | [Vita panel and pads](playstation-vita.md#panel-and-pads). |
| Cxbx-Reloaded | The real pads, through SDL (on HidHide's allow list) | [Xbox games](xbox.md#ps4-pads). |
| Read only Xbox pads, or one input per control | Keys | [Pads as panel keys](#pads-as-panel-keys). |

## Pads as panel keys

Some emulators hold one input per control, or read only Xbox pads, and already have the
panel's keys. Instead of binding every control again for a pad, and losing the panel key
the pad bind replaces, let DS4Windows make each pad press its player's panel keys while
that emulator is in front. A key changed on the panel side then reaches the pads by itself.

Checked this way:

| Emulator | Why keys rather than pad binds |
|---|---|
| Sega Model 2 1.1a | One input per control, and its pad support was set to Xbox pads (`XInput=1`). |
| Project64 2.3 with N-Rage | One input per N64 button, so each player is the panel or a pad. |
| MAME 0.214 and 0.237, HBMAME 0.214 | The panel remaps in `cfg\default.cfg` replace MAME's own pad defaults; the other way is adding `OR JOYCODE_…` to every remap and per-game cfg. |
| Supermodel r458 (Sega Model 3) | Bound to Xbox pads with Xbox button numbers (`-input-system=xinput`, the module's `InputSystem=xinput`), which still takes keys a program sends. Gun setups on `rawinput` don't. |

Two DInput-only profiles, "Panel P1" and "Panel P2", each with its player's keys:

| Pad | Panel |
|---|---|
| Left stick, D-pad | Joystick |
| Square, Triangle, R1, L1 | Top row, buttons 1–4 |
| Cross, Circle, R2, L2 | Bottom row, buttons 5–8 |
| Options | Start |
| Share | Coin |

In the profile file (`Profiles\Panel P1.xml` beside DS4Windows) each control names a
Windows virtual-key code: `37`–`40` the arrows, `65` A, `82` R, `83` S (the example
panel's keys in the [cabinet reference](cabinet-architecture-reference.md#physical-button-layout)).
Parts of one:

```xml
<DinputOnly>True</DinputOnly>
<OutputContDevice>DS4</OutputContDevice>
<Control>
  <Key>
    <LXNeg>37</LXNeg>
    <DpadLeft>37</DpadLeft>
    <Square>65</Square>
    <Options>82</Options>
    <Share>83</Share>
  </Key>
</Control>
```

Each emulator then gets a rule in `Auto Profiles.xml` beside DS4Windows, by the full path
of its program (or in DS4Windows' Auto Profiles tab). Close DS4Windows and back the file
up before editing it:

```xml
<Program path="D:\Arcade\Emulators\Sega Model 2\emulator_multicpu.exe" title="">
  <Controller1>Panel P1</Controller1>
  <Controller2>Panel P2</Controller2>
  <Controller3>(none)</Controller3>
  <Controller4>(none)</Controller4>
  <Controller5>(none)</Controller5>
  <Controller6>(none)</Controller6>
  <Controller7>(none)</Controller7>
  <Controller8>(none)</Controller8>
  <TurnOff>False</TurnOff>
</Program>
```

- **Don't also bind the pads inside the emulator.** With one input per control, a pad bind
  replaces the panel key.
- **The emulator has to take keys a program sends.** Check with one pad press before
  relying on it: [builds that ignore them](#builds-that-ignore-keys-a-program-sends).
- **Four players:** a MAME copy set up for four players can have the pads as players 3 and
  4 beside a two-player panel, with "Panel P3" and "Panel P4" profiles that press those
  players' keys. On the cabinet checked: stick and D-pad move, Square, Triangle, R1 are
  buttons 1–3, Cross, Circle, R2 buttons 4–6, Options Start and Share Coin.
- **Numpad Enter:** DS4Windows sends the main Enter for it (Windows gives both Enter keys one
  key code). Give such a MAME control a second key, `KEYCODE_ENTERPAD OR KEYCODE_PLUSPAD`,
  and put numpad + in the profile. MAME's number-pad names have no underscore before
  `PAD`: `ENTERPAD`, `PLUSPAD`, `MINUSPAD`, `SLASHPAD`.
- **A MAME copy that keeps MAME's own defaults** already has the pads (the defaults include
  the first pads) and needs no rule.
- **Driving and gun copies** of the same emulators can keep rules of their own.

### Builds that ignore keys a program sends

MAME added the `keyboardprovider` option in 0.172. On Windows its default, `auto`, reads the
keyboard through raw input, which doesn't see keys that DS4Windows, AutoHotkey or another
program sends. Set `keyboardprovider dinput` in the copy's `mame.ini` (`hbmame.ini`,
`mess.ini`), and the Panel rule works. A MESS 0.179 `mess.ini` checked had the option but
didn't set it.

Older builds read the keyboard through raw input, with no option to change it. On the
cabinet checked those were HBMAME 0.160, MESS 0.160,
MAME 0.168 and a Golden Tee build of MAME 0.165: their wheels stay on the panel alone, or
move to a newer build.

- **Don't leave a Panel rule on for them.** In HBMAME 0.160 a pad press with one stopped all
  input, the panel's too.
- **Don't bind the pads in them either.** MAME 0.145 to 0.179 crash at exit when
  `default.cfg` names a pad input they can't place, and leave the file at 0 bytes, with every
  panel key gone. On the cabinet checked, a `JOYCODE_…` for a pad that was off came back as
  `UNKNOWN` after one exit and crashed the next; a D-pad code crashed the first.
  `doctor`'s **MAME key maps** check finds maps like that.
- **A newer build beside the old one:** HBMAME 0.214 (the oldest HBMAME with the option is
  0.173) took the sets that pass its `-verifyroms`; the rest stay on 0.160, game by game in
  the wheel's `Games.ini`.
