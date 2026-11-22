# Wheel refreshers and cabinet helpers

The GUI's **Custom Wheels** page manages refreshers, installation and startup
scheduling. All tools share `.spindoctor/config.json`.

## Wheel builders

| Main CLI | Pip helper | Source wrapper |
|---|---|---|
| `spindoctor fav` | `spindoctor-fav` | `scripts/spindoctor-fav.py` |
| `spindoctor recent` | `spindoctor-recent` | `scripts/spindoctor-recent.py` |
| `spindoctor stats-report` | `spindoctor-stats` | `scripts/spindoctor-stats.py` |

```text
spindoctor-fav rebuild --apply
spindoctor-recent rebuild --limit 20 --apply
spindoctor-stats build-wheel --limit 25 --apply
```

Favorites sorts by display title and imports HyperSpin favorites during rebuild.
Recent sorts by last played; Most Played ranks total time with play count as a
tiebreaker. Recent/Most Played read RocketLauncher statistics.

Windows v3 ships no separate helper EXEs. Either standalone EXE embeds them:

```text
spindoctor-cli.exe --run-tool spindoctor-fav rebuild --apply
```

A `.bat` invoking the windowed GUI must wait:

```bat
start "" /B /WAIT "C:\SpinDoctor\spindoctor.exe" --run-tool spindoctor-fav rebuild --apply
```

The checkout's convenience `.bat` files call pip helper names on PATH, not the
embedded workers. Prefer generated wrappers for binary installations.

## Wiring into HyperSpin Tools menu

```text
spindoctor install-tools --tool refresh-all
spindoctor install-tools --tool refresh-all --add-to-system Toolkit --apply
spindoctor uninstall-tools --tool refresh-all --add-to-system Toolkit --apply
```

Select helpers explicitly with repeated/comma-separated `--tool`. Other installed
helpers remain untouched. Without `--add-to-system`, files default to
`<rocketlauncher_dir>/Modules/HyperLaunch/Tools/spindoctor`; register their bats
in HyperHQ's Tools menu. `--output-dir` overrides the destination.

For a wheel, the target database must exist and use PCLauncher. Installation
uses its first `Rom_Path` when available, otherwise its PCLauncher folder, and
adds database/module routing and missing bundled wheel art with `--apply`.
**Helper files are written even without Apply; registration is what previews.**
Existing custom art is preserved; uninstall only removes art still matching
SpinDoctor's bytes.

## Available helpers

| `--tool` | Runs |
|---|---|
| `refresh-favorites`, `refresh-recently-played`, `refresh-most-played` | Individual rebuild |
| `refresh-all` | All three rebuilds |
| `shut-down-cabinet`, `restart-cabinet` | Cancelable countdown, close frontend, shut down/restart Windows |
| `exit-to-windows` | Close frontend and restore desktop/taskbar |
| `reset-button-lights` | Clear PAC-LED64 onboard flash speeds |
| `set-windows-resolution` | Restore primary display to HyperSpin's configured resolution |
| `idle-tour` | Start alongside HyperSpin, not from a wheel/menu |

Toolkit power/display/LED actions run **immediately**, not behind `--apply`.
Shutdown/restart force-close Windows applications after the countdown; save work.
Esc cancels the countdown. Exit To Windows restarts Explorer to restore the
taskbar. Resolution changes are saved. LED reset needs the compatible
`PacDrive32.dll`. Actions log to `.spindoctor/toolkit.log`.

## Wiring into Windows startup

In **Custom Wheels → Auto-refresh on cabinet startup**, enable the logon task
with a delay, or disable/check it. Generated BAT/VBS shims run embedded workers
hidden at low priority. Task Scheduler permissions depend on local policy.
The intro-video task is separate.

After moving the EXE or upgrading from older releases, regenerate installed
helpers and re-enable both tasks to refresh absolute paths. `doctor` flags
missing helper executables. Installing the app alone schedules nothing.

The [idle tour](idle-tour.md) instead joins HyperSpin's Startup Script list;
it exits when HyperSpin closes and must not have a broad EXE-kill Exit entry.

## Tools audit

```text
spindoctor tools-audit --extra-path D:\ArcadeUtilities --show-unknown
```

Inventories known utilities and suggests overlapping SpinDoctor commands.
It never uninstalls software. Drivers, mappers, HyperHQ, RocketLauncherUI and
gun software remain external dependencies where your cabinet uses them.
