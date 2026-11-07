# Idle tour: HyperSpin's idle mode visits the consoles

HyperSpin's own idle mode (attract mode) starts after a few idle minutes, spins the wheel you're on at random and lets each video play to its end. It never changes wheels, and HyperSpin usually starts on the main menu, so a cabinet left alone only ever shows the console videos.

The idle tour, `spindoctor toolkit idle-tour`, runs beside HyperSpin and changes wheels while HyperSpin's idle mode runs. HyperSpin keeps doing the spinning and the video timing in each wheel the tour opens.

- **In a console:** after 5 games or 5 minutes, whichever comes first, it presses HyperSpin's Exit key, back to the main menu.
- **On the main menu:** after 5 consoles or 5 minutes, it presses Start on the console HyperSpin's idle spin just landed on. If that console is skipped, it waits for the next spin.
- **When someone uses a control,** HyperSpin's idle mode stops as it always does, and the tour stops with it. It starts counting again when HyperSpin's idle mode comes back.
- **After 60 minutes** it stops changing wheels and leaves HyperSpin's idle mode on the main menu, so Windows can turn the screen off.

The counts and times are [settings](#settings). Windows only.

## Contents

- [What it needs](#what-it-needs)
- [Installing it](#installing-it)
- [Settings](#settings)
- [How it knows where HyperSpin is](#how-it-knows-where-hyperspin-is)
- [Safety: the exit menu and other hazards](#safety-the-exit-menu-and-other-hazards)
- [Scripting HyperSpin: what to know](#scripting-hyperspin-what-to-know)
- [Log and self-test](#log-and-self-test)

## What it needs

In HyperSpin's `Settings\Settings.ini` (HyperHQ sets these; edit the file only while HyperSpin is closed, because HyperSpin rewrites it when it exits):

| Setting | Why |
|---|---|
| `[Main]` `Menu_Mode=multi` | The tour needs a main menu. In single mode HyperSpin shows one wheel, and Exit there opens the exit menu, so the tour presses nothing (and `install-tools` and `doctor` say so). |
| `[AttractMode]` `Active=true` | The tour only changes wheels while HyperSpin's idle mode runs. `Time=` is how many idle seconds before it starts (300 = 5 minutes), `Wait_For_Video=true` lets each video finish. |
| `[LEDBlinky]` `Active=true` | The tour reads every selection and every idle spin from HyperSpin's LEDBlinky calls in its `log.txt` (see [below](#how-it-knows-where-hyperspin-is)). With LEDBlinky calls off, those lines aren't written and the tour does nothing. |
| `[Startup Program]` | Something has to start the tour with HyperSpin. `install-tools` adds it to the **HyperSpin Startup Script** when that's HyperSpin's Startup Program (see [HyperSpin Startup/Exit Orchestration](cabinet-architecture-reference.md#hyperspin-startupexit-orchestration)). |

The tour presses HyperSpin's own Start and Exit keys, read from `[P1 Controls]` `Start` and `Exit` (Windows virtual-key codes; 13 = Enter and 27 = Esc when unset).

## Installing it

```bat
spindoctor install-tools --tool idle-tour            :: write the helper, preview the Startup Script entry
spindoctor install-tools --tool idle-tour --apply    :: and add it to the Startup Script
spindoctor doctor                                    :: the "Idle tour" check
```

`install-tools --tool idle-tour` writes two files to `<rocketlauncher_dir>\Modules\HyperLaunch\Tools\spindoctor\` (or `--output-dir`):

- `Idle Tour.bat`, which runs `"<the SpinDoctor EXE that ran install-tools>" --run-tool spindoctor toolkit idle-tour --settings "%~dp0Idle Tour settings.ini"`;
- `Idle Tour settings.ini`, only when there isn't one, so your settings survive a re-install.

With `--apply` it also adds the `.bat` to the `[Startup]` list of HyperSpin's Startup Script, at the next free number, after saving a `.bak` copy of the INI (beside it, or in `backup_dir\HyperSpin`; `spindoctor backup sidecar` finds it). The Startup Script is found from HyperSpin's own `[Startup Program]` setting: `Executable` in `Working_Directory`, with `.ini` for `.exe`. Every other byte of that INI is kept.

```ini
[Startup]
Program_To_Run_Target_1=HyperSearch.exe
Program_To_Run_Working_Dir_1=D:\Arcade\Utilities\HyperSearch
Program_To_Run_MaxMinHide_1=Hide
Program_To_Run_Target_2=Idle Tour.bat
Program_To_Run_Working_Dir_2=D:\Arcade\RocketLauncher\Modules\HyperLaunch\Tools\spindoctor
Program_To_Run_MaxMinHide_2=Hide
```

It starts the next time HyperSpin starts. Notes:

- **The Startup Script stops at the first missing number.** An entry after a gap never starts, and filling the gap would start it again, so `install-tools` refuses to add the tour when entries sit after a gap and says which; number them 1, 2, 3 … first. `doctor` flags a tour entry after a gap.
- **No `[Exit]` entry.** The tour runs as SpinDoctor's own EXE, so a `Process_Name_To_Close_N` for it would also close the SpinDoctor GUI, and an Exit To Windows helper still at work, when HyperSpin exits. The tour quits by itself about 10 seconds after HyperSpin has closed.
- **It's never a wheel entry.** It runs for as long as HyperSpin is open, so RocketLauncher would wait on it forever; `install-tools --add-to-system` refuses it.
- **Hidden, no window.** The Startup Script starts the `.bat` hidden, and the `.bat` runs SpinDoctor directly (not through `start`), so the CLI EXE shares that hidden console and the GUI EXE has none.
- **One copy only.** A second copy (HyperSpin restarted quickly) quits at once and the first carries on. **Never run two idle tours**, such as this one and a script of your own: both act on the same landing, and a second Exit lands on the main menu. `install-tools` and `doctor` warn when the Startup Script also starts something named like an idle tour (`IdleTour.exe`, `Idle Tour.ahk`).
- **The folder is written as a full path**, and must be plain ASCII when the Startup Script's INI has no BOM (it's read as ANSI).
- **Another startup program?** Have it run `Idle Tour.bat` hidden each time HyperSpin starts. `install-tools` says so when HyperSpin's Startup Program isn't the Startup Script.
- **The GUI:** tick **Idle Tour** in the Custom Wheels tab's helper checklist and click **Install Tools-menu helpers**; with **Apply changes** on, the Startup Script entry is written too.
- **After moving or upgrading SpinDoctor,** re-run the same `install-tools --tool idle-tour`. The `.bat` runs SpinDoctor by its full path; `doctor`'s **SpinDoctor helpers** check flags it when that EXE is gone.

`spindoctor uninstall-tools --tool idle-tour --apply` removes the `.bat`, its settings file and its `[Startup]` entry (after a backup), and numbers the later entries down so the list keeps no gap. Without `--apply` it shows what it would remove.

To switch the tour off without uninstalling it, set `Enabled=0` in its settings file.

## Settings

`Idle Tour settings.ini`, section `[IdleTour]`, read when the tour starts (when HyperSpin starts). A missing or unreadable value keeps its default.

| Key | Default | What it does |
|---|---|---|
| `Enabled` | `1` | `0` switches the tour off. |
| `ConsoleMinutes` | `5` | Minutes in a console before going back to the main menu. `0` switches this limit off. |
| `GamesPerConsole` | `5` | Games shown by HyperSpin's idle spins in a console before going back. `0` switches it off. |
| `MainMenuMinutes` | `5` | Minutes on the main menu before opening a console. `0` switches it off. |
| `ConsolesOnMainMenu` | `5` | Consoles shown on the main menu before opening one. `0` switches it off. |
| `TourMaxMinutes` | `60` | After this long it stops changing wheels and ends on the main menu, so Windows can turn the screen off (the tour's key presses count as input to Windows). It starts again after someone uses a control. `0` = never stop. |
| `Skip` | `Toolkit\|Favorites\|Most Played\|Recently Played` | Consoles it never opens, by main-menu name, separated by `\|`, ignoring case. Wheels with no `Databases\<name>\<name>.xml` are skipped too. |
| `PauseWhile` | (none) | Programs, by EXE name separated by `\|` (`.exe` may be left off), during which it presses nothing, for example a tool that drives HyperSpin itself. |
| `KeyHoldMs` | `80` | How long each key is held. HyperSpin drops shorter presses. |
| `QuietMs` | `1500` | How long HyperSpin's log must stay quiet after a spin lands before the tour acts. |

Both limits of a wheel count from the first idle spin in it, and whichever comes first wins. The change happens right after the next spin lands, so with `GamesPerConsole=5` it goes back at the 6th spin. In a console a spin comes about every 40 seconds, so the count usually comes first; console videos on the main menu often run over a minute, so there the minutes usually do.

## How it knows where HyperSpin is

HyperSpin 1.5 rewrites `log.txt` in its own folder at every start and appends to it as it goes, so the log is a live record of where it is. The tour follows the running `HyperSpin.exe`'s folder (SpinDoctor's `hyperspin_dir` if that can't be read) and reads only the lines it needs:

| Log line | Means |
|---|---|
| `<wheel> wheel loaded successfully` | A wheel was opened. HyperSpin logs it again for the same wheel on every letter jump, which isn't a change. |
| `Command Line is: "…\LEDBlinky.exe" 9 "<console>" "Main Menu"` | A selection on the main menu. |
| `Command Line is: "…\LEDBlinky.exe" 9 "<game>" …` | A selection inside a console. |
| `Command Line is: "…\LEDBlinky.exe" 5` / `6` | One of HyperSpin's idle spins starts / stops. The selection logged right after the `6` is where it landed. |
| `Command Line is: "…\LEDBlinky.exe" 8`, then `7 "<console>"` / `4` | A console is about to open / the main menu is about to come back (about a second before the wheel line). |
| `Launching Game` | A game is starting. |

The `LEDBlinky.exe` lines are HyperSpin's LEDBlinky calls: they're written only while `[LEDBlinky] Active=true`. HyperSpin's exit menu writes nothing to the log.

## Safety: the exit menu and other hazards

**The main hazard: Exit on the main menu opens HyperSpin's exit menu** ("Exit? Yes / No"), and its default answer is Yes (`[Main] Exit_Default=yes`). A stray Enter after that closes HyperSpin. The exit menu logs nothing, so a script can't see it open. The tour therefore:

- **acts only right after one of HyperSpin's idle spins has landed** and the log has then been quiet for `QuietMs`: no LEDBlinky call, wheel or game in it. HyperSpin logs LEDBlinky `8` and `7 "<console>"` about a second before it opens a console, and `4` before it goes back to the main menu, so a Start or Exit Windows doesn't count as input (a pad HyperSpin reads itself) still stops the press. The fresh landing shows where HyperSpin is (a game line in a console, a "Main Menu" line on the main menu), and that the exit menu isn't open: HyperSpin's idle spins stop while it is;
- **presses Exit only inside a console, never on the main menu,** and Start only on the main menu, on a console it may open;
- **checks what each key did:** after Exit it waits up to 15 s for the main menu to load, after Start up to 30 s for that console. If the log shows another wheel, or a game starting, it stops until someone uses a control. If nothing happens, it doesn't press again until a new idle spin lands in that wheel;
- **presses nothing during a spin** (HyperSpin swallows keys mid-spin), while `RocketLauncher.exe` runs (a game), while HyperSpin isn't the front window or shows a pop-up, while a `PauseWhile` program runs, or once anyone has pressed a key or moved the mouse since its own last press (Windows' last-input time). It installs no keyboard or mouse hook.

## Scripting HyperSpin: what to know

Worth knowing for any script that drives HyperSpin with key presses (seen on HyperSpin 1.5.1):

- **HyperSpin drops a key that goes down and up at once.** In a test 2 of 3 such presses were lost. Hold each key about 80 ms.
- **HyperSpin queues presses it gets faster than it moves** (about 2 entries a second, each logged), so a burst keeps scrolling after the script stops. Press one key at a time and wait for the log to show each step.
- **HyperSpin's idle timer ignores keys sent by a program** (`SendInput`). Only real input resets it, so a script can't keep HyperSpin's idle mode away, and once it runs, its spins can swallow the script's keys. Windows, on the other hand, counts them as input, so they keep the screen from turning off.
- **`log.txt` is a live state log** (the table above), with `LEDBlinky.exe 5` / `6` around each idle spin.
- **The exit menu isn't logged, and its default is Yes.** A script that closes HyperSpin with Esc then Enter can lose the Esc; the Enter then opens whatever is selected instead. Never send Exit unless the log proves HyperSpin is inside a console.

## Log and self-test

The tour logs to `%USERPROFILE%\.spindoctor\toolkit.log` (see [Storage locations](spindoctor-files.md#toolkitlog)), in `idle-tour:` lines:

```
2026-11-07 14:23:01  idle-tour: started (a console for 5 min or 5 games, the main menu for 5 min or 5 consoles, whichever first; tour limit 60 min, 4 wheel(s) skipped)
2026-11-07 14:23:44  idle-tour: HyperSpin's idle mode is running in Main Menu
2026-11-07 14:28:50  idle-tour: opened Sega Master System after 5.1 min and 6 idle spins on the main menu
2026-11-07 14:29:27  idle-tour: HyperSpin's idle mode is running in Sega Master System
2026-11-07 14:33:04  idle-tour: back on the main menu after 3.6 min and 6 idle spins in Sega Master System
2026-11-07 14:35:12  idle-tour: a control was used: waiting for HyperSpin's idle mode to start again
```

`spindoctor toolkit idle-tour --self-test` (add `--settings` with your settings file) prints and logs what the tour sees, presses nothing and exits: the settings, HyperSpin's folder, its idle-mode and LEDBlinky settings, the Start and Exit keys, skipped wheels with no database, where the log says HyperSpin is, and anything that would stop a key press now.

If the tour never changes wheels, see [Troubleshooting](troubleshooting.md#the-idle-tour-never-changes-wheels).
