# Light guns (Sinden + DemulShooter)

`spindoctor lightgun` wires DemulShooter into RocketLauncher's per-system launches so a Sinden (or compatible) lightgun cabinet can fire on the right emulator without hand-editing `Settings\<System>.ini` for every game system. Module `.ahk` files are never modified — all edits land in the system INI's `Pre_Launch_App` and `Post_Launch_App` keys, which RocketLauncher runs around the emulator.

> **GUI alternative:** the **Lightgun** tab in `spindoctor-gui` covers the same workflow without a console — `Detect installed gear` (with an optional `--apply` checkbox to persist discovered systems into config), `Audit wiring` (per-system table of Pre/Post launch state), and `Configure one system` (with optional `-target` and extra-args overrides). The CLI walkthrough below is still the source of truth; the GUI just builds the equivalent argv.

## Prerequisites

- **Sinden Lightgun** (or another lightgun + driver). Install per the manufacturer's instructions; spindoctor only needs the install to exist on disk. It's recognized by `Lightgun.exe` next to `Lightgun.exe.config`, so a wheel or media folder with "Sinden" in its name isn't mistaken for it.
- **DemulShooter**. Drop `DemulShooter.exe` somewhere reachable — `RocketLauncher\Modules\DemulShooter\` and `HyperSpin\Tools\DemulShooter\` are both auto-detected. If you keep it elsewhere, or keep more than one build, set `demulshooter_path` in spindoctor config. `detect`, `audit` and `configure` all use it, and `detect` lists every DemulShooter it finds when there's more than one.
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

If the system's RocketLauncher User Functions already start the gun software (see [Auditing](#auditing)), `configure` prints a warning: when they start DemulShooter, a `Pre_Launch_App` hook on top of them starts it a second time. `--apply` still writes the hooks, so keep only one of the two.

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

Lists every system with `"lightgun": true` and whether its INI's `Pre_Launch_App` and `Post_Launch_App` are wired. Systems with missing `Post_Launch_App` will leave DemulShooter running after the emulator quits — fix with another `lightgun configure --apply`. Only a `Post_Launch_App` that names DemulShooter counts; an unrelated one (a resolution reset, say) shows as `none`.

Many cabinets start the gun software from RocketLauncher **User Functions** instead of the INI hooks: the AHK files RocketLauncher runs for one system (`RocketLauncher\Lib\User Functions\<System>.ahk`), one of its games (`<System>\<Game>.ahk`) or one emulator (`Emulators\<Emulator>.ahk`, or `<System>\Emulators\<Emulator>.ahk` for that system only). A `Run` or `RunWait` line there that starts `Lightgun.exe` (the Sinden software) or DemulShooter counts as wiring, in the system's own file, the files for its `Default_Emulator` and any `Games.ini` `Emulator=` override, and its games' files. Names match whatever their case, as in RocketLauncher. Comment lines (`;`, `/* … */`) don't count, and neither does a line that runs a helper script which then starts the gun software. `Global.ahk` runs for every system, so it isn't read. The audit's **User Functions** column names the files, `lightgun detect` lists these systems as already wired, and `doctor` passes them (INFO when only some games' or emulators' files start the gun).

User Functions coverage is **partial** in the audit and INFO in `doctor` when only game files or some of the system's emulators start the gun. An emulator file applies only to games using that emulator: both `Default_Emulator` and every `Games.ini` override must be covered for an emulator-only setup to pass. A system-level file covers all of them. `Run` lines that merely name the executable as an argument (such as `taskkill /IM DemulShooter.exe`) are teardown, not startup wiring.

## Defaults and tuning

- DemulShooter is launched with `-noresize` by default — Sinden-friendly. Override globally via `demulshooter_extra_args` or per-call via `--extra-args`.
- The `Post_Launch_App` is `taskkill /IM "DemulShooter.exe" /F` so DemulShooter shuts down cleanly between launches.
- spindoctor never edits the global module `.ahk` files Tur ships with, and never creates a system's settings file just to add the hooks.

## Reverting

The INI is plain text — open `RocketLauncher\Settings\<System>\Emulators.ini` (folder layout) or `RocketLauncher\Settings\<System>.ini` and delete the `Pre_Launch_App` / `Post_Launch_App` lines. Or set `"lightgun": false` in the per-system override and re-run `lightgun audit` to confirm.

## Two guns: Model 3 and the Sinden software

spindoctor doesn't touch the emulators' own gun settings or the Sinden software's settings. These are the setups that most often leave player 2's gun dead.

### Model 3 (Supermodel)

Supermodel reads the guns itself, as mice. Two guns need all of the following:

- **Raw input.** Only Supermodel's `rawinput` input system tells two mice apart; `dinput` and `xinput` merge every mouse into one. RocketLauncher's SuperModel module passes `-input-system=` on the command line, which wins over `InputSystem` in `Supermodel.ini`. Set `InputSystem=rawinput` in the module's settings (`Modules\SuperModel\SuperModel.ini`): under `[Settings]` for every game, or in a section named after a game for that game only. The module's default is `dinput`.
- **A numbered mouse in every gun line** of `Config\Supermodel.ini`, for example `InputGunX = "MOUSE2_XAXIS"` for player 1 and `InputGunX2 = "MOUSE3_XAXIS"` for player 2. In raw input an unnumbered `MOUSE_` means *any* mouse, so player 2's trigger would fire player 1's gun too. The lines are `InputGunX`, `InputGunY`, `InputTrigger`, `InputOffscreen`, `InputAnalogGunX`, `InputAnalogGunY`, `InputAnalogTriggerLeft` and `InputAnalogTriggerRight`, plus the same eight ending in `2` for player 2. `KEY_` and `JOY` entries in the same lines stay as they are.
- **The right numbers.** Supermodel numbers mice in the reverse of Windows' raw-input device list, skips Remote Desktop devices (`Root#RDP_…`), and doesn't sort them. Anything Windows lists as a mouse counts, such as a trackball or encoder board, or a Bluetooth HID device. A number with no mouse behind it fails silently. The order can change when a device is added or removed, so if devices come and go, have a launch script recompute the numbers before each game.
- **Real keys for Start and Coin.** In raw input, Supermodel accepts keys only from real keyboards and ignores keys sent by software. A RocketLauncher keymapper remap (for example `r::1`) or any other AutoHotkey remap therefore loses Start and Coin. Bind Supermodel to the keys the panel and guns really send, and switch the remap off for Supermodel with an emulator-named profile that has no remaps (see the profile order below).
- **Both crosshairs:** `Crosshairs = 3` in `Supermodel.ini`. The values are 0 = none, 1 = player 1 only, 2 = player 2 only, 3 = both. Alt+I cycles them in game.

### RocketLauncher's keymapper profile order

With the internal AHK keymapper, RocketLauncher runs one remap file per game, the first of these that exists:

1. `Profiles\AHK\<System>\<Game>.ahk`
2. `Profiles\AHK\<System>\<Emulator>.ahk`
3. `Profiles\AHK\<System>.ahk`
4. `Profiles\AHK\_Default.ahk`

Only exact system, game and emulator names match. A file named after an emulator, holding only comments, switches a system-wide remap off for that emulator.

### Sinden software (v2)

- **Run both guns for a two-player game.** A gun set to "none" in the Sinden software is never sent any settings. It still recoils from its own firmware when its trigger is pulled, in whatever mode it was last given, so the two guns can recoil differently.
- **Recoil settings go to every gun.** The software sends the same recoil mode and strength to every gun it runs. When the **Lightgun B** single-shot strength box is filled in, its value is used for both guns, not only gun B, and the main strength slider is ignored.
- **Matching single shot to automatic:** a single-shot kick is the strength × 10, and each automatic pulse is the pulse-length slider (40–80). Strength 5 kicks as hard as a pulse length of 50.
