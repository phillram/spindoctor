# Light guns (Sinden + DemulShooter)

`spindoctor lightgun` wires DemulShooter into RocketLauncher's per-system launches so a Sinden (or compatible) lightgun cabinet can fire on the right emulator without hand-editing `Settings\<System>.ini` for every game system. Module `.ahk` files are never modified — all edits land in the system INI's `Pre_Launch_App` and `Post_Launch_App` keys, which RocketLauncher runs around the emulator.

> **GUI alternative:** the **Lightgun** tab in `spindoctor-gui` covers the same workflow without a console — `Detect installed gear` (with an optional `--apply` checkbox to persist discovered systems into config), `Audit wiring` (per-system table of Pre/Post launch state), and `Configure one system` (with optional `-target` and extra-args overrides). The CLI walkthrough below is still the source of truth; the GUI just builds the equivalent argv.

## Prerequisites

- **Sinden Lightgun** (or another lightgun + driver). Install per the manufacturer's instructions; spindoctor only needs the install to exist on disk.
- **DemulShooter**. Drop `DemulShooter.exe` somewhere reachable — `RocketLauncher\Modules\DemulShooter\` and `HyperSpin\Tools\DemulShooter\` are both auto-detected. If you keep it elsewhere, set `demulshooter_path` in spindoctor config.
- **RocketLauncher 1.x** with per-system INIs at `RocketLauncher\Settings\<System>.ini` (the standard layout).

## One-time setup

```bat
spindoctor lightgun detect
```

The first run reports whether Sinden, DemulShooter, and (optionally) Arcade Guns Utility are present, and lists every system whose RL INI already has a `DemulShooter` `Pre_Launch_App` line — typically systems Tur or Don's pre-wired for you.

```bat
spindoctor lightgun detect --apply
```

Adds `"lightgun": true` to `system_overrides` for each pre-wired system so future audits and configures know which systems matter.

## Wiring a new system

```bat
spindoctor lightgun configure --system "Sega Naomi"             :: dry-run preview
spindoctor lightgun configure --system "Sega Naomi" --apply     :: commit
```

The dry-run output shows the exact `Pre_Launch_App` and `Post_Launch_App` lines that will be inserted. `--apply` writes them and marks the system as lightgun-enabled in spindoctor config. They go into the system's existing settings file: `Settings\<System>\Emulators.ini` (under `[ROMS]`) when the system uses the folder layout, otherwise `Settings\<System>.ini` (under `[Settings]`). Nothing else in the file changes. A system with neither file has no RocketLauncher settings yet; set it up in RocketLauncherUI or with `generate-config --apply` first.

DemulShooter is started as `"<DemulShooter.exe>" -target=<target> <extra args>`. DemulShooter only accepts its options with `=`; SpinDoctor 2.15.0 and earlier wrote `-target <target>`, which DemulShooter ignores, so re-run `configure --apply` on systems wired by them. No `-rom=` is written: the hook is per system, and RocketLauncher has no documented way to put each game's ROM name into it. Targets that need `-rom=` are better served by RocketLauncher's own DemulShooter support (DemulShooter path under **Global → Third Party** in RocketLauncherUI, then **DemulShooter Enabled** per game in the module's settings).

For systems spindoctor doesn't auto-target (rare emulators, custom builds), pass `--target <name>` — anything DemulShooter accepts, see its readme:

```bat
spindoctor lightgun configure --system "My Custom" --target supermodel --apply
```

## Auto-targeted systems

System name contains | DemulShooter `-target`
---|---
mame | `mame`
naomi, atomiswave, dreamcast | `demul07a`
model 2 | `model2`
model 3 | `supermodel`
flycast | `flycast`
chihiro | `chihiro`
triforce | `dolphin`
lindbergh | `lindbergh`
ringedge | `ringedge2`
global vr | `globalvr`

Pass `--target` to override.

## Auditing

```bat
spindoctor lightgun audit
```

Lists every system with `"lightgun": true` and whether its INI's `Pre_Launch_App` and `Post_Launch_App` are wired. Systems with missing `Post_Launch_App` will leave DemulShooter running after the emulator quits — fix with another `lightgun configure --apply`.

## Defaults and tuning

- DemulShooter is launched with `-noresize` by default — Sinden-friendly. Override globally via `demulshooter_extra_args` or per-call via `--extra-args`.
- The `Post_Launch_App` is `taskkill /IM "DemulShooter.exe" /F` so DemulShooter shuts down cleanly between launches.
- spindoctor never edits the global module `.ahk` files Tur ships with, and never creates a system's settings file just to add the hooks.

## Reverting

The INI is plain text — open `RocketLauncher\Settings\<System>\Emulators.ini` (folder layout) or `RocketLauncher\Settings\<System>.ini` and delete the `Pre_Launch_App` / `Post_Launch_App` lines. Or set `"lightgun": false` in the per-system override and re-run `lightgun audit` to confirm.
