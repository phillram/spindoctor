# Light guns

SpinDoctor detects Sinden/DemulShooter and configures RocketLauncher hooks.
It does not install drivers, calibrate guns or configure emulator inputs.
Use **GUI → Lightgun**, or:

```text
spindoctor lightgun detect
spindoctor lightgun detect --apply
spindoctor lightgun audit
spindoctor lightgun configure --system "Sega Naomi"
```

Detection with Apply tracks discovered wiring in system overrides.
Configuration previews until `--apply`. Set `demulshooter_path` if discovery
misses your copy; detection recognizes a Sinden installation by `Lightgun.exe`
beside its config, not just a folder name.

## Wiring a new system

The system must already have RocketLauncher settings:
`Settings/<System>/Emulators.ini` (`[ROMS]`) or flat
`Settings/<System>.ini` (`[Settings]`). Configuration writes
`Pre_Launch_App`/`Post_Launch_App`, not module AHK files.

| System name contains | Default DemulShooter target |
|---|---|
| MAME | `mame` |
| Naomi / Atomiswave / Dreamcast | `demul07a` |
| Model 2 / Model 3 | `model2` / `supermodel` |
| Flycast / Chihiro | `flycast` / `chihiro` |
| Triforce / Lindbergh | `dolphin` / `lindbergh` |
| Ringedge / Global VR | `ringedge2` / `globalvr` |

Override with `--target`; optional `--extra-args` overrides defaults
(`-noresize` when no other default is set). DemulShooter uses `-target=value`,
not `-target value`; reconfigure hooks from releases that wrote the latter.
No per-game `-rom=` is generated. For targets needing it, use RocketLauncher's
own per-game DemulShooter support.

## Auditing and reverting

Audit recognizes direct `Run`/`RunWait` startup in applicable RocketLauncher
User Functions: system, game and emulator files, including `Games.ini` emulator
overrides. Comments, teardown commands and indirect helper scripts do not prove
startup. `Global.ahk` is not inspected. Partial emulator/game coverage is reported
as partial, not system-wide success.

Do not add INI hooks on top of working User Functions: that can start the gun
software twice. Inspect teardown too if DemulShooter survives game exit.

To revert, close RocketLauncherUI and restore/remove only the DemulShooter
hook values, preserving unrelated hooks. Also inspect User Functions and native
DemulShooter settings. Clearing SpinDoctor's `lightgun` flag only changes
tracking, not live wiring.

## Two guns: Model 3 and Sinden

Supermodel needs `rawinput`, distinct numbered mouse bindings for both guns,
and correct current device numbers. The RocketLauncher module's
`InputSystem` setting wins over `Supermodel.ini`. Unnumbered `MOUSE_` bindings
accept any mouse, and device order can change after USB/Bluetooth changes.
`Crosshairs=3` shows both.

Raw input ignores software-sent keys. Bind Coin/Start to the real keys sent by
your panel/guns, not an AHK remap. For other emulators using remaps, bind to the
**resulting** key: with `r::1`, the emulator receives 1, not R.

RocketLauncher's AHK profile precedence is game, emulator, system, `_Default`.
A matching emulator profile with no remaps can disable an unwanted inherited map.

Run both Sinden guns for a two-player game. Recoil settings apply to every gun
the software runs; Lightgun B's filled single-shot strength can override the
main strength for both. Firmware recoil alone does not prove a gun is configured.

## SNES Super Scope games

Snes9x starts turbo off; `Key:ScopeTurbo` toggles it. If a game needs turbo at
startup, send that key once after load from its User Functions `PostLoad()`.
Use automatic recoil for sustained fire. Edit `snes9x.conf` only while closed.
