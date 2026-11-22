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

## Emulator input

Bind emulators to the intended virtual pad, not a transient physical DS4 device.
Dolphin can combine keyboard-encoder and pad inputs, but GameCube keyboard
bindings need explicit device qualifiers when the selected pad is disconnected.
Per-game Dolphin profiles can overwrite global controller edits.

See [cabinet input reference](cabinet-architecture-reference.md#input) and
[gun/remap precedence](lightgun.md#two-guns-model-3-and-sinden).
