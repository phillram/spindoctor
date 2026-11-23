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
Dolphin can combine keyboard-encoder and pad inputs, but GameCube keyboard
bindings need explicit device qualifiers when the selected pad is disconnected.
Per-game Dolphin profiles can overwrite global controller edits.

See [cabinet input reference](cabinet-architecture-reference.md#input) and
[gun/remap precedence](lightgun.md#two-guns-model-3-and-sinden).
