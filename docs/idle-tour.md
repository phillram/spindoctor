# Idle tour: HyperSpin's idle mode visits the consoles

HyperSpin's own idle mode (attract mode) starts after a few idle minutes, spins the wheel you're on at random and lets each video play to its end. It never changes wheels, and HyperSpin usually starts on the main menu, so a cabinet left alone only ever shows the console videos.

The idle tour, `spindoctor toolkit idle-tour`, runs beside HyperSpin and changes wheels while HyperSpin's idle mode runs. HyperSpin keeps doing the spinning and the video timing in each wheel the tour opens.

- **In a console:** after 5 games or 5 minutes, whichever comes first, it presses HyperSpin's Exit key, back to the main menu, just as the last game's video ends. The first game shown after the tour opened the console counts as game 1.
- **On the main menu:** after 5 consoles or 5 minutes, it presses Start on the console whose video just played, just as that video ends. Skipped consoles count but are never opened; it waits for the next one.
- **On a game or console with no video,** where HyperSpin's idle mode would wait its whole idle time (5 minutes) before spinning again, it presses Down after 8 seconds. The item that brings up counts like any other.
- **When someone uses a control,** HyperSpin's idle mode stops as it always does, and the tour stops with it. It starts counting again when HyperSpin's idle mode comes back.
- **It keeps touring** for as long as HyperSpin's idle mode runs. Its key presses count as input to Windows, so the screen stays on meanwhile. With a tour limit (`TourMaxMinutes`) it stops changing wheels after that many minutes and leaves HyperSpin's idle mode on the main menu, so Windows can turn the screen off.

The counts and times are [settings](#settings), which the GUI and `spindoctor toolkit idle-tour-settings` change. Windows only.

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

The tour presses HyperSpin's own Start, Exit and Down keys, read from `[P1 Controls]` `Start`, `Exit` and `Down` (Windows virtual-key codes; 13 = Enter, 27 = Esc and 40 = the down arrow when unset).

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
- **The GUI:** tick **Idle Tour** in the Custom Wheels tab's helper checklist and click **Install Tools-menu helpers**; with **Apply changes** on, the Startup Script entry is written too. The **Idle Tour settings** box below it edits the [settings](#settings).
- **After moving or upgrading SpinDoctor,** re-run the same `install-tools --tool idle-tour`. The `.bat` runs SpinDoctor by its full path; `doctor`'s **SpinDoctor helpers** check flags it when that EXE is gone.

`spindoctor uninstall-tools --tool idle-tour --apply` removes the `.bat`, its settings file and its `[Startup]` entry (after a backup), and numbers the later entries down so the list keeps no gap. Without `--apply` it shows what it would remove.

To switch the tour off without uninstalling it, set `Enabled=0` in its settings file.

## Settings

`Idle Tour settings.ini`, section `[IdleTour]`, read when the tour starts (when HyperSpin starts). A missing or unreadable value keeps its default.

| Key | Default | What it does |
|---|---|---|
| `Enabled` | `1` | `0` switches the tour off. |
| `GamesPerConsole` | `5` | Games shown in a console before going back to the main menu, the first one after the tour opened it included. `0` switches this limit off. |
| `ConsoleMinutes` | `5` | Minutes in a console before going back. `0` switches it off. |
| `ConsolesOnMainMenu` | `5` | Consoles shown by HyperSpin's idle spins on the main menu before opening one, skipped ones included. `0` switches it off. |
| `MainMenuMinutes` | `5` | Minutes on the main menu before opening a console. `0` switches it off. |
| `TourMaxMinutes` | `0` | The tour limit. `0` = never stop: it tours for as long as HyperSpin's idle mode runs. With a number of minutes, it stops changing wheels after that long and ends on the main menu, so Windows can turn the screen off (the tour's key presses count as input to Windows). It starts again after someone uses a control. |
| `Skip` | `Toolkit\|Favorites\|Most Played\|Recently Played` | Consoles it never opens, by main-menu name, separated by `\|`, ignoring case. Wheels with no `Databases\<name>\<name>.xml` are skipped too. |
| `PauseWhile` | (none) | Programs, by EXE name separated by `\|` (`.exe` may be left off), during which it presses nothing, for example a tool that drives HyperSpin itself. |
| `NoVideoSeconds` | `8` | Seconds on a game or console with no video before it presses Down to the next one ([below](#items-with-no-video)); at least 2. `0` = wait for HyperSpin's own next spin. |
| `KeyHoldMs` | `80` | How long each key is held. HyperSpin drops shorter presses. |
| `QuietMs` | `1500` | How long HyperSpin's log must stay quiet after a spin lands before the tour acts on that landing (the fallback below). |
| `EndMarginMs` | `1500` | How long before a video's end the tour changes wheels. |

**When it changes wheels.** Both limits of a wheel count from the first idle spin in it (in a console the tour opened, from the first game it shows), and whichever comes first wins. The minutes are checked against "now + this video's length", so it never cuts a video short. The change happens `EndMarginMs` before the last item's video ends, because HyperSpin spins as soon as a video ends and swallows keys mid-spin. The length comes from the video file, `.mp4` first, then `.flv`, in the wheel's video folder: `Settings\<wheel>.ini` `[video defaults]` `path=` when it names a folder (absolute, or under `Media` or HyperSpin's folder), else `Media\<wheel>\Video`; the main menu's console videos are in `Media\Main Menu\Video`.

**The fallback: right after the next spin lands.** When the length can't be read (an unreadable file, or no video with `NoVideoSeconds=0`), or the video ends sooner than its file says (a spin starts first), it changes right after the next idle spin lands instead: Exit in a console, and on the main menu Start on the console that spin landed on, or on the next one that isn't skipped. It does the same, always, when HyperSpin reads a joystick itself (see [Safety](#safety-the-exit-menu-and-other-hazards)).

<a id="items-with-no-video"></a>**Items with no video.** With no `.mp4` or `.flv` for an item (none, or only a still), HyperSpin's idle mode has no video to wait for, so it sits on the item for its whole idle time (`[AttractMode]` `Time=`, 300 s by default) before spinning again. After `NoVideoSeconds` the tour presses Down once instead. The item that brings up counts like one an idle spin landed on: HyperSpin plays its video and spins as it ends. If the item with no video was the wheel's last, the tour changes wheels after `NoVideoSeconds` instead (Exit in a console, Start on the main menu), and a skipped console with no video gets a Down too. Should HyperSpin not spin within 5 s of the end of a video a Down brought up, the tour presses Down again. The video folder is the one above; in a wheel without one, every item counts as having no video. With a joystick HyperSpin reads itself there is no Down at all (see [Safety](#safety-the-exit-menu-and-other-hazards)).

**Changing them.** In the GUI, the Custom Wheels tab's **Idle Tour settings** box (below **Install Tools-menu helpers**) shows the values with **Load current settings**, and the skip list as HyperSpin's main menu, where you tick the consoles it never opens. **Save settings** writes them at once. On the command line:

```bat
spindoctor toolkit idle-tour-settings                     :: show them
spindoctor toolkit idle-tour-settings --consoles-on-main-menu 1 --games-per-console 10 --console-minutes 0 --main-menu-minutes 0
spindoctor toolkit idle-tour-settings --skip "Toolkit|Favorites|Apple II"
spindoctor toolkit idle-tour-settings --no-video-seconds 0  :: no Down past items with no video
spindoctor toolkit idle-tour-settings --disabled          :: Enabled=0
```

Both change only the keys given, and only their values: comments, the other keys, the encoding and the line ends stay as they are, and a value the file already has isn't rewritten. They use the settings file beside the `Idle Tour.bat` that HyperSpin's Startup Script starts, else the one in install-tools' folder (`--settings` picks another). The tour reads them the next time HyperSpin starts. `PauseWhile`, `KeyHoldMs`, `QuietMs` and `EndMarginMs` are edited in the file itself.

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

- **presses only while an item's video plays and nothing has been logged since the item appeared** (no spin, LEDBlinky call, selection, wheel or game), or right after one of HyperSpin's idle spins has landed and the log has then been quiet for `QuietMs`. HyperSpin logs LEDBlinky `8` and `7 "<console>"` about a second before it opens a console, and `4` before it goes back to the main menu, so a Start or Exit Windows doesn't count as input still stops the press. The item's own selection line (an idle-spin landing, or the first game after the tour's Start) shows where HyperSpin is (a game line in a console, a "Main Menu" line on the main menu), and that the exit menu isn't open: HyperSpin's idle spins stop while it is;
- **never presses as a video ends when HyperSpin reads a joystick itself** (`[P1 Joystick]` or `[P2 Joystick]` `Enabled=true`). Windows doesn't see those presses, so a joystick Exit during a main-menu video would open the exit menu without a word in the log, and Start at the video's end would answer Yes. With one, the tour changes wheels only right after an idle spin lands, which shows HyperSpin's idle mode is still running, and presses no Down past items with no video (a Down in an exit menu the tour can't see would move its highlight). Its log says so when it starts. Pads mapped to keys (JoyToKey and the like) are seen by Windows and need nothing;
- **presses Exit only inside a console, never on the main menu,** and Start only on the main menu, on a console it may open. Down only moves the wheel one step, wherever it is, and gets the same checks as the other keys; after one, the tour waits up to 3 s for the next selection, and if none comes it waits for HyperSpin's next spin;
- **checks what each key did:** after Exit it waits up to 15 s for the main menu to load, after Start up to 30 s for that console. If the log shows another wheel, or a game starting, it stops until someone uses a control. If nothing happens, it doesn't press again until a new idle spin lands in that wheel;
- **presses nothing during a spin** (HyperSpin swallows keys mid-spin), while `RocketLauncher.exe` runs (a game), while HyperSpin isn't the front window or shows a pop-up, while a `PauseWhile` program runs, or once anyone has pressed a key or moved the mouse since its own last press (Windows' last-input time). It installs no keyboard or mouse hook.

## Scripting HyperSpin: what to know

Worth knowing for any script that drives HyperSpin with key presses (seen on HyperSpin 1.5.1):

- **HyperSpin drops a key that goes down and up at once.** In a test 2 of 3 such presses were lost. Hold each key about 80 ms.
- **HyperSpin queues presses it gets faster than it moves** (about 2 entries a second, each logged), so a burst keeps scrolling after the script stops. Press one key at a time and wait for the log to show each step.
- **HyperSpin's idle timer ignores keys sent by a program** (`SendInput`). Only real input resets it, so a script can't keep HyperSpin's idle mode away, and once it runs, its spins can swallow the script's keys. Windows, on the other hand, counts them as input, so they keep the screen from turning off.
- **`log.txt` is a live state log** (the table above), with `LEDBlinky.exe 5` / `6` around each idle spin. A scripted Down logs only the new selection, no `5` / `6`.
- **HyperSpin's idle mode treats an item a script brought up like one it landed on:** it plays that item's video and spins as it ends. On an item with no video it waits its whole idle `Time` instead.
- **The exit menu isn't logged, and its default is Yes.** A script that closes HyperSpin with Esc then Enter can lose the Esc; the Enter then opens whatever is selected instead. Never send Exit unless the log proves HyperSpin is inside a console.

## Log and self-test

The tour logs to `%USERPROFILE%\.spindoctor\toolkit.log` (see [Storage locations](spindoctor-files.md#toolkitlog)), in `idle-tour:` lines:

```
2026-11-07 17:19:02  idle-tour: started (a console for 3 games, the main menu for 1 consoles, whichever first; no tour limit, 4 wheel(s) skipped, Down past items with no video after 8 s)
2026-11-07 17:19:40  idle-tour: HyperSpin's idle mode is running in Main Menu
2026-11-07 17:19:40  idle-tour: main menu: console 1 is Sammy Atomiswave (45.9 s): opening it as its video ends
2026-11-07 17:20:25  idle-tour: opened Sammy Atomiswave after 0.8 min, 1 consoles on the main menu
2026-11-07 17:20:27  idle-tour:   Sammy Atomiswave: game 1 is Dolphin Blue
2026-11-07 17:21:05  idle-tour:   Sammy Atomiswave: game 2 is Faster Than Speed (no video: stepping on in 8 s)
2026-11-07 17:21:14  idle-tour:   Sammy Atomiswave: game 3 is Metal Slug 6 (36 s): leaving as its video ends
2026-11-07 17:21:49  idle-tour: back on the main menu after 1.4 min, 3 games in Sammy Atomiswave
2026-11-07 17:22:28  idle-tour: main menu: console 1 is Sega Hikaru (skipped, not opened)
2026-11-07 17:35:12  idle-tour: a control was used: waiting for HyperSpin's idle mode to start again
```

`spindoctor toolkit idle-tour --self-test` (add `--settings` with your settings file) prints and logs what the tour sees, presses nothing and exits: the settings, HyperSpin's folder, its idle-mode and LEDBlinky settings, the Start, Exit and Down keys, skipped wheels with no database, where the log says HyperSpin is, anything that would stop a key press now, and the selection's video (its length, or none) and the folder it's read from.

If the tour never changes wheels, see [Troubleshooting](troubleshooting.md#the-idle-tour-never-changes-wheels).
