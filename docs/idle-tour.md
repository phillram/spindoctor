# Idle tour

Windows-only `toolkit idle-tour` changes consoles while HyperSpin's own idle
mode spins games. Defaults: leave a console after five games or five minutes;
open a console after five main-menu selections or five minutes. Skipped wheels
count but are never opened. Items with no video advance after eight seconds.

## What it needs

In HyperSpin `Settings/Settings.ini`:

- `[Main] Menu_Mode=multi`
- `[AttractMode] Active=true` (and preferably `Wait_For_Video=true`)
- `[LEDBlinky] Active=true`, so selection/spin calls appear in live `log.txt`
- A configured HyperSpin Startup Script as the Startup Program for auto-install

Close HyperSpin before editing settings; it writes them on exit.

## Installing it

```text
spindoctor install-tools --tool idle-tour
spindoctor install-tools --tool idle-tour --apply
spindoctor toolkit idle-tour --self-test
spindoctor doctor
```

The first command writes `Idle Tour.bat` and a missing `Idle Tour settings.ini`;
Apply adds it to the Startup Script's numbered `[Startup]` list after a backup.
Existing settings survive reinstall. Number entries contiguously: the script
stops at the first gap, and installation refuses to reactivate hidden later
entries accidentally. `--add-to-system` is not supported for idle tour.

No `[Exit]` kill entry is needed: the tour exits with HyperSpin. Killing the
shared SpinDoctor EXE could also kill the GUI or another active helper.
Remove via `uninstall-tools --tool idle-tour --apply`.

## Settings

Section `[IdleTour]` in the helper's settings INI, read at tour startup:

| Key | Default | Meaning |
|---|---|---|
| `Enabled` | `1` | `0` disables |
| `GamesPerConsole` / `ConsoleMinutes` | `5` / `5` | First limit reached leaves a console; `0` disables that limit |
| `ConsolesOnMainMenu` / `MainMenuMinutes` | `5` / `5` | First limit reached opens an eligible console |
| `TourMaxMinutes` | `0` | Unlimited; set a limit to let Windows eventually blank the display |
| `Skip` | `Toolkit\|Favorites\|Most Played\|Recently Played` | Pipe-separated main-menu names; missing databases also skipped |
| `PauseWhile` | Empty | Pipe-separated EXE names that suspend key presses |
| `NoVideoSeconds` | `8` | Advance video-less items; `0` disables, otherwise at least 2 |
| `KeyHoldMs` | `80` | Hold each synthetic key |
| `QuietMs` | `1500` | Quiet-log wait after idle-spin landing |
| `EndMarginMs` | `1500` | Change just before the video's end |

Edit supported counts/limits/skip settings through **Custom Wheels → Idle Tour
settings** or `toolkit idle-tour-settings --help`; preview before Apply.
Other keys are edited in the INI. Restart the tour/HyperSpin to reload.

## Timing and safety

The tour reads HyperSpin's live wheel/LEDBlinky log events and MP4/FLV durations,
honoring video-path redirects. Unknown timing falls back to a quiet idle-spin
landing. It reads Start/Exit/Down from `[P1 Controls]` and verifies transitions.

It sends no input during games, spins, popups, lost focus or detected real input.
Exit is sent only inside a console. With native joystick input enabled, it
uses landing-only transitions and sends no Down: Windows cannot see that
joystick input reliably enough to rule out an open exit menu.

The tour's keys count as input to **Windows**, keeping the display awake, but
do not reset HyperSpin's own idle timer. Set `TourMaxMinutes` if display sleep is
wanted. Human input resets the tour for the next idle session.

## Log and self-test

`toolkit idle-tour --self-test` reports settings, keys, log state, video lookup
and reasons not to act; it sends no keys. Tour events go to
`.spindoctor/toolkit.log`. Use this and `doctor` before changing safety timings.

When scripting HyperSpin yourself, hold keys long enough, send one at a time,
and confirm the log transition. Never blindly send Esc then Enter:
HyperSpin's exit menu is unlogged and can default to Yes.
