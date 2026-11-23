# Pinball programs

SpinDoctor doesn't install pinball programs or supply tables or ROMs. These notes
are about starting Future Pinball and Visual Pinball X from RocketLauncher on a
control panel wired as a keyboard. Checked with Future Pinball 1.9 with BAM 1.5-412
and Visual Pinball X 10.8.0: check again after an upgrade, on a copy first.

## Keys

Both programs read the keyboard through DirectInput, so they can see a panel key
before RocketLauncher's AHK keymapper swaps it. Bind the panel's keys in the program
itself, and keep the keymapper for second buttons that do the same job.
See [controller input](controller-input.md).

## Future Pinball with BAM

BAM (Better Arcade Mode) is unpacked into Future Pinball's own folder and started
with `BAM\FPLoader.exe`. RocketLauncher's Future Pinball module supports this:
point the emulator's `Emu_Path` at `FPLoader.exe`, and don't rename it.

- **Its default keys are letters a panel may send.** In `BAM\bam.cfg`, `Cam = "C"`
  changes the camera, `Menu2 = "Q"` opens BAM's menu, and `SwitchToNextBall = "N"`
  and `SwitchToPrevBall = "P"` change the ball. Set the ones your panel sends to
  `9999`, the value BAM uses for an action with no key. Keep one menu key that isn't
  on the panel (`Menu = 192` is the key below Esc).
- **An update replaces `bam.cfg`,** so set those keys again afterwards.
- **Test a copy with care.** Once Future Pinball's type library is registered for
  your Windows user, each start of the program registers it again for the folder it
  runs from. After trying a copy, start the real one once, so table scripts don't
  depend on a folder you may delete.

## Visual Pinball X

RocketLauncher's stock Visual Pinball module is written for Visual Pinball 8 and 9:
it sends `/exit` and waits for version 9's dialogs. Visual Pinball X has no `/exit`.
Use a module that starts it like this:

```autohotkey
Run(executable . " -Minimized -Ini """ . emuPath . "\VPinballX.ini"" -Play """ . romPath . "\" . romName . romExtension . """", emuPath)
WinWait("ahk_class VPPlayer")
```

- **`-Minimized`** keeps the table editor out of sight; closing the table then closes
  the program.
- **`-Ini` is needed for a settings file beside the program.** Without it, 10.8.0
  uses `VPinballX.ini` in the user's AppData and ignores the one next to the EXE.
- **Keys are DirectInput scan codes** in `[Player]` (`LFlipKey`, `RFlipKey`,
  `PlungerKey`, `StartGameKey`, `AddCreditKey` and so on): A is 30, B 48, C 46,
  D 32, R 19, S 31, and the Left, Right and Up arrows 203, 205 and 200.
- **Move the defaults your panel sends:** Q quits, T is the mechanical tilt, D opens
  the debugger, O is a ball-debug key and P pauses. Give them keys the panel doesn't
  have, such as F5 to F9 (63 to 67).
- **Use 64-bit VPinMAME with the 64-bit program.** Tables that recreate a real machine
  need that machine's ROM; many original and electromechanical tables don't.

### RocketLauncher says it can't find the system's database

Started as its own system, RocketLauncher stops with “Cannot find”
`\Databases\Visual Pinball X\Visual Pinball X.xml` when that file doesn't exist. It doesn't
have to list any games, and the system doesn't have to be on the Main Menu. Create
one only when it is missing; never replace an existing list.

```xml
<?xml version="1.0"?>
<menu>
  <header>
    <listname>Visual Pinball X</listname>
  </header>
</menu>
```

The same applies to any system you start that has no HyperSpin game list yet.
