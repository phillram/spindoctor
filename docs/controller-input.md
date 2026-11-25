# Controller example: DS4Windows Auto Profiles

This is an adaptable PS4-pad example, not automatic SpinDoctor configuration.
Use one mapping path: keyboard output while HyperSpin is focused, virtual
Xbox/XInput output in games.

## Profiles

1. Create a normal XInput profile, `Controller`, as default.
2. Create `HyperSpin-Keys` and assign it to HyperSpin in **Auto Profiles**.
3. Match keys to your actual HyperHQ settings. Example:

| Pad | Key / menu action |
|---|---|
| D-pad/stick Up / Down | Up / Down, scroll |
| Left / Right, L1 / R1 | Left / Right, letter jump |
| Cross / Circle | Enter / Esc, select/back |
| Triangle / Square / L2 | C / A / B, main menu/favorites/genre |

For a second pad, use the configured Player-2 keys rather than duplicating P1.

## Startup and focus

Start DS4Windows once at Windows login, not again from HyperSpin. Keep it alive
when HyperSpin exits so running emulators do not lose their virtual controller.
Tick **Start Minimized** and **Close Minimizes**, untick **Minimize to Taskbar**
to keep its window in the tray rather than resurfacing after games close.

Remove redundant native joystick/menu mapper configuration only after testing
the replacement. In a HyperSpin Startup Script, keep numbered entries contiguous
and remove DS4Windows from `[Exit]` kill lists. Preserve unrelated helper entries.

## Removing a redundant mapper

Check all launch points before uninstalling Xpadder/JoyToKey/antimicro:

- RocketLauncherUI global/system/game Keymapper settings and profiles.
- Windows Startup folders, Run keys and scheduled tasks.
- HyperSpin Startup/Exit Script and RocketLauncher User Functions.

RocketLauncher's **Internal** AHK method can still read mapper profiles without
launching the mapper EXE; disabling Windows startup alone does not disable it.
Do not remove a keymapper still needed for another emulator or gun setup.

## Games that read the keyboard first

RocketLauncher's Internal AHK keymapper hooks the keyboard before the game starts.
Some games install their own keyboard hook after that, and the newest hook is called
first: the game sees the panel key before the remap can block it.
One panel button then does two things, or the remapped key does nothing.

- **Bind the panel keys in the game**, when it saves its own controls, and remap only
  the keys the game doesn't use.
- **Otherwise start the remap after the game.** Put it in a separate AutoHotkey script
  that the RocketLauncher module runs once the game window is up, so its hook is the
  newest and is called first. Limit it to the game's window with `#IfWinActive`, and
  let it exit when the game does.
- **Check with a hold, not a tap:** hold each button and see that only its own action
  happens. A hotkey on one of RocketLauncher's menu navigation keys needs a `*` prefix
  (`*w::`): `doctor`'s **Keymapper hotkeys** check lists the ones that don't.

## Emulator input

Bind emulators to the intended virtual pad, not a transient physical DS4 device.
Cxbx-Reloaded is an exception: it misses a virtual pad that appears as it starts,
so bind its [real pads through SDL](xbox.md#ps4-pads).
Azahar (Nintendo 3DS) binds each button to one source, so a profile is either the
panel or the pad; its module can [pick one per start](nintendo-3ds.md#panel-and-pads).
Dolphin can combine keyboard-encoder and pad inputs, but GameCube keyboard
bindings need explicit device qualifiers when the selected pad is disconnected.
Per-game Dolphin profiles can overwrite global controller edits.

See [cabinet input reference](cabinet-architecture-reference.md#input) and
[gun/remap precedence](lightgun.md#two-guns-model-3-and-sinden).

## Panel and controller together

Some emulators read one input source per player. A keyboard-encoder panel then works
until somebody turns a controller on, and stops for the whole game. Try each emulator
both ways: start a game with the controllers off, then again with one on.

| Emulator | What takes the panel's place | Keep the panel working |
|---|---|---|
| ActiveGS | `joystickMode:joystick1` in `Documents\ActiveGSLocalData\activegs.conf` uses the first controller, and the numpad only when there is none | `joystickMode:keypad` |
| AppleWin | Joystick 1 on **PC Joystick #1** does the same | **Keyboard (numpad)** in its input settings (`Joystick0 Emu Type v3` = `3` in its registry key) |
| Project64 with N-Rage | `xInput=1` in a `[Controller n]` section of `NRage.ini` reads only an Xbox-type pad | `xInput=0`, and bind the panel's keys |

Close the emulator and back up the file first. A numpad joystick needs numpad keys,
which a panel rarely sends, so remap them in the wheel's RocketLauncher key file.

### Let the controller press the panel's keys

Once an emulator reads only the keyboard, the same key file can make a controller
press those keys, and then both work at once. With `Keymapper_AHK_Method=Internal`,
RocketLauncher adds `Profiles\AHK\<System>.ahk` to the end of the module's script and
runs it in its own `AutoHotkey.dll` (AutoHotkey_H 1.1.13, ANSI, 32-bit on the cabinet
checked). Plain lines in the key file don't run there, only hotkeys, functions and
labels, so a `static` variable starts the timer:

```autohotkey
Up::Numpad8
Down::Numpad2
Left::Numpad4
Right::Numpad6
a::Numpad0

PadKeys_Init() {
	static started := PadKeys_Init()	; runs once, when the script loads
	SetTimer, PadKeys_Poll, 20
	Return 1
}

PadKeys_Poll:
	PadKeys_Update()
Return

PadKeys_Update() {
	static ids := "", nextScan := 0, held := "|"
	static keys := "Numpad8|Numpad2|Numpad4|Numpad6|Numpad0"
	SetKeyDelay, -1, -1
	want := "|"
	If WinActive("ahk_class AfxFrameOrView90s") {	; the emulator's window (ActiveGS)
		If (A_TickCount >= nextScan) {
			ids := PadKeys_Find()
			nextScan := A_TickCount + 10000
		}
		Loop, Parse, ids, |
			want .= PadKeys_Read(A_LoopField)
	}
	Loop, Parse, keys, |
	{
		key := "|" . A_LoopField . "|"
		If (InStr(want, key) && !InStr(held, key)) {
			held .= A_LoopField . "|"
			Send, {Blind}{%A_LoopField% Down}
		} Else If (!InStr(want, key) && InStr(held, key)) {
			StringReplace, held, held, %key%, |
			Send, {Blind}{%A_LoopField% Up}
		}
	}
}

PadKeys_Find() {	; connected Sony controllers (vendor 054C), "0|1|..."
	VarSetCapacity(caps, 404, 0)
	found := ""
	Loop, 16
	{
		id := A_Index - 1
		If (DllCall("winmm\joyGetDevCapsA", "UInt", id, "Ptr", &caps, "UInt", 404) = 0 && NumGet(caps, 0, "UShort") = 0x54C)
			found .= (found = "" ? "" : "|") . id
	}
	Return found
}

PadKeys_Read(id) {
	VarSetCapacity(info, 52, 0)
	NumPut(52, info, 0, "UInt")
	NumPut(0xFF, info, 4, "UInt")
	If (id = "" || DllCall("winmm\joyGetPosEx", "UInt", id, "Ptr", &info) != 0)
		Return ""
	Return PadKeys_Keys(NumGet(info, 8, "UInt"), NumGet(info, 12, "UInt"), NumGet(info, 32, "UInt"), NumGet(info, 40, "UInt"))
}

PadKeys_Keys(x, y, b, pov) {	; stick 0-65535, button bits, D-pad in hundredths of a degree
	dpad := (pov < 36000)
	k := ""
	If (y < 16000 || (dpad && (pov >= 31500 || pov <= 4500)))
		k .= "Numpad8|"
	If (y > 49500 || (dpad && pov >= 13500 && pov <= 22500))
		k .= "Numpad2|"
	If (x < 16000 || (dpad && pov >= 22500 && pov <= 31500))
		k .= "Numpad4|"
	If (x > 49500 || (dpad && pov >= 4500 && pov <= 13500))
		k .= "Numpad6|"
	If (b & 2)	; Cross (Circle 4, Share 256, Options 512)
		k .= "Numpad0|"
	Return k
}
```

- **Change the window class** and the keys to the emulator's. Without the `WinActive`
  test the timer also types into HyperSpin and the Pause menu.
- **Filter by vendor.** Encoders and guns can show up as joysticks that don't rest in
  the middle, and would hold a direction down.
- **Turn the controller on before the game.** One turned on later may not be seen.
- **Keep the names unique.** The functions and the label share the module's script with
  RocketLauncher's own.

Checked in ActiveGS and AppleWin with DualShock 4 controllers (DS4Windows running): the
panel and a controller both worked in play, with this file plus three more buttons
(AppleWin's window class is `APPLE2FRAME`). For N-Rage, `xInput=0` was also tried on
the cabinet.

## Emulator hotkeys and the encoder's shift button

Encoders with a shift function (Ultimarc's I-PAC and Mini-PAC, for example) give one
button, often Coin, a second layer. While it is held, every other input sends its
shifted code instead of its own, or nothing when no shifted code is set, and the shift
button's own key isn't sent. An emulator hotkey that is a chord of that button and
another, such as Coin + Right for "next disc", then never fires from the panel. It still
works from a keyboard, from a controller, or when a test sends the two keys itself,
so it can look fine until someone tries it on the panel.

- **See what a combination really sends** before binding it: a window with a low-level
  keyboard hook that lists key codes shows it. A combination that shows nothing has no
  shifted code. The mapping lives on the encoder board, so a saved WinIPAC file may not
  match it.
- **Bind hotkeys to keys the panel sends on their own**: spare buttons, or shifted codes
  that exist. Leave out keys RocketLauncher uses in games (exit, Pause menu).
- **Controllers are not affected.** A pad's Share + D-pad chord reaches the emulator, so
  the pad can keep the chord while the panel gets a single key.
- **Keep a chord's keys off one-key hotkeys** that act on the game. In DuckStation, a
  restart bound to Pause + Select, with Pause alone as "next disc", restarted the game
  and then switched disc as well: the key still held after the restart fired again.

DuckStation's `[Hotkeys]` in `settings.ini` takes one binding per line, and ` & ` makes a
chord. The panel's Pause (`P`) and Select (`Enter`) buttons change disc here, and the
first controller keeps Share + D-pad:

```ini
[Hotkeys]
SwitchToNextDisc = Keyboard/P
SwitchToNextDisc = SDL-0/Back & SDL-0/DPadRight
SwitchToPreviousDisc = Keyboard/Enter
SwitchToPreviousDisc = SDL-0/Back & SDL-0/DPadLeft
```
