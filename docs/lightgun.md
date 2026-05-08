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

The dry-run output shows the exact `Pre_Launch_App` and `Post_Launch_App` lines that will be inserted. `--apply` writes them and marks the system as lightgun-enabled in spindoctor config.

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
- spindoctor never edits the global module `.ahk` files Tur ships with. If a per-system INI didn't exist, it's generated using the same template as `generate-config`.

## Reverting

The INI is plain text — open `RocketLauncher\Settings\<System>.ini` and delete the `Pre_Launch_App` / `Post_Launch_App` lines. Or set `"lightgun": false` in the per-system override and re-run `lightgun audit` to confirm.
