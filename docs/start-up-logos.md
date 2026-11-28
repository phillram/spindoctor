# Console start-up logos

A real console plays its own logo before each game: the Game Boy's scrolling
"Nintendo", the PlayStation and PlayStation 2 logos, the GameCube cube, the
Dreamcast swirl. That logo is part of the console's boot ROM or BIOS, so an
emulator can only play it when it has that file, and each emulator has its own
setting for it. `boot-intros` finds the emulators RocketLauncher starts and turns
that setting on or off, for all of them at once or one at a time. SpinDoctor
doesn't supply BIOS files.

This is not HyperSpin's own intro video, which is [`introvideo`](workflows.md#managing-intro-videos).

## Turning them on or off

```text
spindoctor boot-intros list
spindoctor boot-intros off
spindoctor boot-intros off --apply
spindoctor boot-intros on gambatte mgba --apply
spindoctor boot-intros off "DuckStation (PS1)" --apply
spindoctor boot-intros off melonds-ds --game-files --apply
```

- **`list`** shows each emulator with such a setting, the consoles it covers,
  whether the logo is on, and whether the boot ROM or BIOS it needs was found.
  Emulators on the cabinet without a setting are named at the end.
- **`on` and `off`** change every emulator in the list, or only the ones named. A
  name is the **Name** column (`gambatte`, `duckstation`), the emulator's or core's
  name, its folder, or a RocketLauncher emulator name. `Gambatte (RetroArch 1.22.2)`,
  as the list shows it, picks one core in one RetroArch. A Name or label picks only
  that emulator: `dolphin` is the standalone Dolphin, `dolphin-core` the RetroArch core.
- **Both preview** what they would change, file by file, until `--apply`. Each file
  is backed up first (`<file>.<date>_<time>.bak`, or under `backup_dir\Emulators`)
  while `backup_before_modify` is on, and only the one setting changes: the rest of
  the file stays as it was, byte for byte, BOM and line ends included.
- **Turning a logo on needs its file.** An emulator whose boot ROM or BIOS isn't
  found is left as it is, and the file and the folders looked in are named. Where
  each console of an emulator has its own file (Gambatte's Game Boy and Game Boy
  Color boot ROMs), one is enough, and the others are named: those games start
  without the logo.
- **Close the emulators first.** RetroArch, melonDS, PCSX2 and others write their
  settings back when they close, over a change made while they ran.
- **In the GUI:** the Intro Video page's **Console start-up logos** list shows only
  the emulators whose logo can be turned both on and off now, each with its current
  state (**Start-up logo now**), and **Turn on / Turn off selected** and **All on /
  All off** switch them. An emulator still missing its boot ROM or BIOS is only
  named below the list. The Apply switch decides between a preview and writing, as
  everywhere else.

Emulators are found from the `Emu_Path` of every section in RocketLauncher's
`Global Emulators.ini` and the wheels' own `Emulators.ini`, as `doctor` reads them.
With no RocketLauncher entries, the folders one level under `emulators_dir`.

### RetroArch cores

- **Every core RetroArch has in its `cores` folder** that has a setting is listed,
  once per RetroArch install.
- **The core's options file** is `<config folder>\<core name>\<core name>.opt`. A
  per-game or per-folder `.opt` beside it is read *instead of* the core's file for
  that game, so that game keeps its own setting: that is how a game the console's
  BIOS refuses is kept off it (below). `list` counts them, `on` and `off` name the
  ones they leave different, and `--game-files` changes them too.
- **A core that has no options file yet gets one.** It starts with the core's lines
  from the old shared `retroarch-core-options.cfg` when there is one, as RetroArch
  does itself the first time. With `global_core_options = "true"`, only the shared
  file is used and changed.
- **Folders come from `retroarch.cfg`** beside `retroarch.exe` and from the configs
  in its config folder that RocketLauncher starts it with (`-c config\<System>.cfg`).
  Each of those configs' system folders needs the BIOS file. `system_directory =
  "default"` means each game's own folder, so it can't be checked: set a system
  folder first.
- **RetroArch takes only its own spelling of a value.** `ON` for mGBA, `Enabled` for
  Gearboy, `enabled` for most others: any other spelling is ignored and the default
  used, so `boot-intros` writes each core's own.

## What each emulator has

Every key below was read in the emulator's own source code (November 2026). "Logo"
is the value that plays it; the other one skips it. Files are in RetroArch's system
folder unless the row says otherwise.

| Emulator | Name | Consoles | Setting | Logo | Default | Needs |
|---|---|---|---|---|---|---|
| Gambatte (RetroArch) | `gambatte` | Game Boy, Game Boy Color | `gambatte_gb_bootloader` | `enabled` | logo | `gb_bios.bin`, `gbc_bios.bin` (either) |
| mGBA (RetroArch) | `mgba` | Game Boy Advance (and GB, GBC) | `mgba_skip_bios` (and `mgba_use_bios = "ON"`) | `OFF` | logo | `gba_bios.bin`, `gb_bios.bin`, `gbc_bios.bin`, `sgb_bios.bin` (any) |
| Gearboy (RetroArch) | `gearboy` | Game Boy, Game Boy Color | `gearboy_bootrom_dmg`, `gearboy_bootrom_gbc` | `Enabled` | no logo | `dmg_boot.bin`, `cgb_boot.bin` (either) |
| Gearsystem (RetroArch) | `gearsystem` | Master System, Game Gear | `gearsystem_bios_sms`, `gearsystem_bios_gg` | `Enabled` | no logo | `bios.sms`, `bios.gg` (either) |
| Genesis Plus GX (RetroArch) | `genesis-plus-gx` | Mega Drive, Master System, Game Gear | `genesis_plus_gx_bios` | `enabled` | no logo | `bios_MD.bin`, `bios_U.sms` / `bios_E.sms` / `bios_J.sms`, `bios.gg` (any) |
| Genesis Plus GX Wide (RetroArch) | `genesis-plus-gx-wide` | as above | `genesis_plus_gx_wide_bios` | `enabled` | no logo | as above |
| Beetle PSX / Beetle PSX HW (RetroArch) | `beetle-psx`, `beetle-psx-hw` | PlayStation | `beetle_psx_skip_bios` / `beetle_psx_hw_skip_bios` | `disabled` | logo | a Sony BIOS (`scph5500.bin`, `scph5501.bin`, `scph5502.bin`, ...) |
| PCSX ReARMed (RetroArch) | `pcsx-rearmed` | PlayStation | `pcsx_rearmed_show_bios_bootlogo` | `enabled` | no logo | a Sony BIOS, and `pcsx_rearmed_bios` not `HLE` |
| SwanStation (RetroArch) | `swanstation` | PlayStation | `swanstation_BIOS_PatchFastBoot` | `false` | logo | `scph5500.bin` / `scph5501.bin` / `scph5502.bin` |
| Flycast (RetroArch) | `flycast-core` | Dreamcast | `reicast_hle_bios` | `disabled` | logo | `dc\dc_boot.bin` or `dc\dc_bios.bin` |
| melonDS DS (RetroArch) | `melonds-ds` | Nintendo DS | `melonds_boot_mode` (and `melonds_sysfile_mode = "native"`) | `native` | no logo | `bios7.bin`, `bios9.bin` and a DS firmware, in `system` or `system\melonDS DS` |
| melonDS (RetroArch, old core) | `melonds-core` | Nintendo DS | `melonds_boot_directly` | `disabled` | no logo | `bios7.bin`, `bios9.bin`, `firmware.bin` |
| DeSmuME (RetroArch) | `desmume` | Nintendo DS | `desmume_boot_into_bios` (and `desmume_use_external_bios`, `desmume_cpu_mode = "interpreter"`) | `enabled` | no logo | `bios7.bin`, `bios9.bin`, `firmware.bin` |
| Virtual Jaguar (RetroArch) | `virtual-jaguar` | Atari Jaguar (cartridges) | `virtualjaguar_bios` | `enabled` | no logo | nothing: the boot ROMs are built in |
| Dolphin (RetroArch) | `dolphin-core` | GameCube | `dolphin_skip_gc_bios` | `disabled` | no logo | `dolphin-emu\Sys\GC\<USA, EUR, JAP or DEV>\IPL.bin` |
| DuckStation | `duckstation` | PlayStation | `settings.ini` `[BIOS] PatchFastBoot` | `false` | logo | the BIOS it already needs |
| PCSX2 2.x | `pcsx2` | PlayStation 2 | `inis\PCSX2.ini` `[EmuCore] EnableFastBoot` | `false` | no logo | the BIOS it already needs |
| Dolphin | `dolphin` | GameCube | `Config\Dolphin.ini` `[Core] SkipIPL` | `False` | no logo | `IPL.bin` for **every** region, in `User\GC\<USA, EUR, JAP>` or `Sys\GC\<region>` |
| Flycast | `flycast` | Dreamcast | `emu.cfg` `[config] UseReios` | `no` | logo | `dc_boot.bin` or `dc_bios.bin` in `Dreamcast.BiosPath`, `data` or a content folder |
| xemu | `xemu` | Xbox | `xemu.toml` `[general] skip_boot_anim` | `false` | logo | the files it already needs |
| melonDS 1.x / 0.9 | `melonds` | Nintendo DS | `melonDS.toml` `[Emu] DirectBoot` (and `ExternalBIOSEnable = true`); 0.9: `melonDS.ini` `DirectBoot=0` | `false` | no logo | the files `[DS] BIOS9Path`, `BIOS7Path`, `FirmwarePath` name |

Things worth knowing:

- **A console's BIOS refuses some games, as the real console does.** With
  Genesis Plus GX's BIOS on, the Genesis TMSS ROM locks up a cartridge without
  `SEGA` at `0x100` (some early EA and Accolade games such as Populous, Budokan and
  Ishido, and some unlicensed ones); the Game Gear BIOS can lock up one without the
  `TMR SEGA` header; the export Master System BIOS checks the header and its
  checksum. Japanese and headerless Master System games boot as before, because
  Genesis Plus GX gives them the Japanese BIOS (`bios_J.sms`), which is usually not
  there. Gearsystem's own option text warns the same, and a Game Boy boot ROM
  (Gambatte, Gearboy) stops on a cartridge whose logo or header checksum is wrong,
  as a patched ROM's can be; mGBA skips its BIOS for those instead. Keep such a
  game off the BIOS with its own options file: a copy of the core's `.opt` named
  after the game file (`config\Genesis Plus GX\Populous (USA).opt`) with
  `genesis_plus_gx_bios = "disabled"`.
- **Dolphin won't start a GameCube game whose region has no `IPL.bin`** ("the GC IPL
  could not be found") while `SkipIPL` is off, so all three regions are needed. Wii
  games never show it. Its user folder is `User` beside `Dolphin.exe` with
  `portable.txt`, else `Documents\Dolphin Emulator` if it exists, else
  `%APPDATA%\Dolphin Emulator`; a folder set in the registry isn't followed.
- **Flycast off is Flycast's built-in BIOS** (no swirl). Flycast still picks the real
  BIOS by itself for the few games that need it.
- **Gambatte's boot ROM also decides** whether a Game Boy game in GBC or GBA mode
  starts as a Game Boy Color (only with `gbc_bios.bin` and the boot ROM on).
- **mGBA off** keeps the BIOS and skips only its logo (`mgba_skip_bios`).
- **DeSmuME on** also turns on its external BIOS and its interpreter CPU, which is
  slower than its JIT.
- **Virtual Jaguar off** is its default, so its own per-title list may still use the
  boot ROM for a game that needs it; on is always honoured. Jaguar CD has its own
  setting (`virtualjaguar_cd_boot_mode`), not changed here.
- **PCSX2:** a `-fastboot` or `-slowboot` on the command line (a RocketLauncher
  module's parameters) or a game's own settings win over `EnableFastBoot`.
- **DuckStation:** `[Main] DisableAllEnhancements = true` plays the logo whatever
  `PatchFastBoot` says. Its settings are `settings.ini` beside the exe when that or
  `portable.txt` is there, else `Documents\DuckStation` if it exists, else
  `%LOCALAPPDATA%\DuckStation`.
- **xemu off** shortens the Xbox boot animation rather than removing it.
- **Sega CD** games always start through the CD BIOS, in Genesis Plus GX and
  PicoDrive alike.
- **An emulator's settings file must exist.** One that was never started has none,
  and `boot-intros` doesn't make one (RetroArch cores aside): start it once.

## Emulators with no such setting

These are listed as having none, never given a made-up key:

- **RetroArch cores:** SameBoy (always plays its built-in boot ROMs), PicoDrive,
  ProSystem (plays the 7800 BIOS whenever `7800 BIOS (U).rom` is there), Opera,
  NeoCD, Beetle Saturn, Beetle PC-FX, Beetle PCE and PCE Fast, and Mesen, FCEUmm and
  Nestopia for the Famicom Disk System BIOS. Yabause, Kronos and YabaSanshiro have
  only a switch to their HLE BIOS (`yabause_force_hle_bios`, ...), which also
  changes how games run, so it is left alone.
- **Standalone:** PCSX2 1.x (only the `--fullboot` command-line switch), Mednafen,
  Cemu, RPCS3, Vita3K, Azahar and Citra, Project64, Snes9x and Supermodel.
- **Not covered yet:** PPSSPP's `GameBootAnimation` (it needs files from a PSP
  firmware), Mesen 2's Game Boy Advance and WonderSwan boot screens, and the
  standalone mGBA.
- **Closed source, so nothing to check:** SSF, Demul, BigPEmu, Redream and Kega
  Fusion.

## Where each key comes from

Read in each project's default branch on GitHub:

- Gambatte `libgambatte/libretro/libretro_core_options.h`, `libretro.cpp`
- mGBA `src/platform/libretro/libretro_core_options.h`, `libretro.c`
- Gearboy and Gearsystem `platforms/libretro/libretro_core_options.h`, `libretro.cpp`
- Genesis Plus GX `libretro/libretro_core_options.h`, `libretro.c`
- Beetle PSX `libretro_options.h`, `libretro_core_options.h`
- PCSX ReARMed `frontend/libretro_core_options.h`, `libpcsxcore/r3000a.c`
- SwanStation `src/libretro/libretro_core_options.h`, `src/core/system.cpp`
- Flycast `shell/libretro/libretro_core_option_defines.h`, `core/cfg/option.cpp`,
  `core/emulator.cpp`, `core/nvmem.cpp`
- melonDS DS `src/libretro/config/definitions/system.hpp`, `constants.hpp`
- melonDS (old core) `src/libretro/libretro_core_options.h`
- DeSmuME `desmume/src/frontend/libretro/libretro_core_options.h`, `libretro.cpp`
- Virtual Jaguar `libretro_core_options.h`, `libretro.c`
- Dolphin (RetroArch) `Source/Core/DolphinLibretro/Common/Options.cpp`, `Boot.cpp`
- DuckStation `src/core/settings.cpp`, `settings.h`
- PCSX2 `pcsx2/Pcsx2Config.cpp`, `pcsx2/VMManager.cpp`
- Dolphin `Source/Core/Core/Config/MainSettings.cpp`, `Core/Boot/Boot.cpp`,
  `Core/BootManager.cpp`
- xemu `config_spec.yml`, `system/vl.c`
- melonDS `src/frontend/qt_sdl/Config.cpp`, `EmuInstance.cpp`
- RetroArch `runloop.c`, `configuration.c`, `config.def.h`, `file_path_special.c`
