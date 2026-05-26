# Cabinet Architecture Reference

> **Note:** This documents one specific cabinet's layout. Your setup may be different.
> SpinDoctor reads paths from your existing configuration files rather than assuming
> fixed locations — always check your own `Emulators.ini` files if something doesn't work.

---

## Directory Layout

```
D:\Arcade\
├── RocketLauncher\                   ← RocketLauncher root
│   ├── RocketLauncher.exe
│   ├── RocketLauncherGame.exe        ← SpinDoctor-created copy; used as RL#2 for synthetic wheels (see below)
│   ├── Modules\
│   │   └── PCLauncher\
│   │       ├── PCLauncher.ahk        ← AHK module invoked by RL for all PCLauncher systems
│   │       ├── PCLauncher.ini        ← Global PCLauncher game entries (legacy catch-all)
│   │       ├── Favorites\            ← ROM placeholder files (RL discovery only)
│   │       │   └── btoads2play.ini   ← placeholder — PCLauncher.ahk does NOT read this
│   │       ├── Favorites.ini         ← System-level config PCLauncher.ahk DOES read
│   │       ├── Recently Played\      ← placeholder files for Recently Played wheel
│   │       ├── Recently Played.ini   ← system-level config for Recently Played
│   │       ├── Most Played\
│   │       ├── Most Played.ini
│   │       ├── Toolkit\              ← placeholder files for Toolkit wheel
│   │       ├── Toolkit.ini           ← system-level config for Toolkit (pre-existing)
│   │       ├── PC Games.ini
│   │       ├── Gun Games.ini
│   │       ├── Gun Games (Sinden).ini
│   │       └── ...                   ← one .ini per PCLauncher system
│   ├── Settings\
│   │   ├── Global Emulators.ini      ← master emulator registry
│   │   ├── Global Statistics\
│   │   │   └── <System>.ini          ← per-system play stats (RL writes these)
│   │   ├── Favorites\
│   │   │   ├── Emulators.ini         ← folder-layout: [ROMS] Default_Emulator=PCLauncher
│   │   │   └── RocketLauncher.ini    ← all keys use_global (inherits from Global)
│   │   ├── Favorites.ini             ← flat-layout (RL reads whichever exists first)
│   │   ├── MAME\
│   │   │   └── Emulators.ini         ← [ROMS] Default_Emulator=MAME
│   │   └── Nintendo 64\
│   │       └── Emulators.ini         ← [ROMS] Default_Emulator=RetroArch
│   ├── Emulators\
│   │   └── PCLauncher\
│   │       └── PCLauncher.exe        ← the emulator exe (not the .ahk module)
│   └── Games\
│       ├── MAME\                     ← MAME ROMs
│       ├── Nintendo 64\              ← N64 ROMs
│       └── ...
├── HyperSpin\
│   ├── Databases\
│   │   ├── MAME\
│   │   │   └── MAME.xml
│   │   ├── Favorites\
│   │   │   └── Favorites.xml         ← SpinDoctor writes/manages this
│   │   └── ...
│   ├── Media\
│   │   ├── MAME\
│   │   │   ├── Images\Wheel\
│   │   │   ├── Images\Backgrounds\
│   │   │   ├── Themes\               ← themes stored as per-game .zip files
│   │   │   ├── Sound\
│   │   │   └── Video\
│   │   └── Favorites\                ← SpinDoctor mirrors media here during rebuild
│   └── Settings\
│       ├── Favorites.ini             ← HyperSpin wheel settings (hyperlaunch=true)
│       └── ...
└── Utilities\
    └── Toolkit\                      ← SpinDoctor tool executables live here
        ├── exit.exe
        ├── soundfix_mame.exe
        └── ...
```

---

## Settings Layout: Folder vs Flat

RocketLauncher supports two layouts for per-system routing. This cabinet uses the
**folder layout** (produced by HyperHQ):

| Layout  | File location                        | Section | Key read              |
|---------|--------------------------------------|---------|-----------------------|
| Folder  | `Settings/<System>/Emulators.ini`    | `[ROMS]`| `Default_Emulator=`   |
| Flat    | `Settings/<System>.ini`              |`[Settings]`| `Default_Emulator=` |

SpinDoctor writes **both** files so the cabinet works regardless of which RL prefers.

The folder-layout `Emulators.ini` for synthetic wheels looks like:
```ini
[ROMS]
Default_Emulator=PCLauncher
Rom_Extension=ini
Rom_Path=D:\Arcade\RocketLauncher\Modules\PCLauncher\Favorites
```

The flat-layout `Settings/Favorites.ini` looks like:
```ini
[Settings]
Default_Emulator=PCLauncher
Rom_Path=D:\Arcade\RocketLauncher\Modules\PCLauncher\Favorites
Rom_Extension=ini

[PCLauncher]
Rom_Path=D:\Arcade\RocketLauncher\Modules\PCLauncher\Favorites
Rom_Extension=ini
```

> **Critical:** `[PCLauncher]` in the flat file MUST have `Rom_Extension=ini`. RL reads
> `Rom_Extension` from `[PCLauncher]` first and ignores the `[Settings]` value when that
> section is present.

---

## Global Emulators.ini — PCLauncher Entry

`Settings\Global Emulators.ini` registers every emulator. The `[PCLauncher]` section
**must** have `Rom_Extension=ini` set. Without it, RL falls back to the global extension
list (`zip|rar|7z|...`) and can't find the per-game `.ini` ROM files.

```ini
[PCLauncher]
Emu_Path=..\Emulators\PCLauncher\PCLauncher.exe
Module=PCLauncher.ahk
Rom_Extension=ini
```

> **This is a manual cabinet setting.** SpinDoctor does not modify `Global Emulators.ini`.
> It was the root cause of "Cannot find Rom X with any provided Rom_Extension: zip|rar|7z|…"
> errors seen on this cabinet.

---

## PCLauncher Architecture — Two-File System

PCLauncher uses **two separate file types** for synthetic wheels. Many people confuse them:

### 1. ROM Placeholder Files — `Modules\PCLauncher\<System>\<game>.ini`

Used **only by RocketLauncher** to enumerate which games exist in the wheel.
**PCLauncher.ahk never reads these.** Their content does not matter.

```ini
; This file is a ROM placeholder for RL discovery.
; PCLauncher.ahk reads the system-level INI below instead.
[Settings]
ApplicationPath=D:\Arcade\RocketLauncher\RocketLauncher.exe
ApplicationParameters=-s "MAME" -r "btoads2play"
StartIn=D:\Arcade\RocketLauncher
```

### 2. System-Level PCLauncher Config — `Modules\PCLauncher\<System>.ini`

**Read by PCLauncher.ahk** to find what to launch for each game.
From the PCLauncher.ahk comment (line 13): *"PCLauncher supports per-System inis.
Copy your PCLauncher ini in the same folder and rename it to match the System's Name."*

Each game is a `[<game_name>]` section:

```ini
[btoads2play]
Application=D:\Arcade\RocketLauncher\RocketLauncherGame.exe
Parameters=-s "MAME" -r "btoads2play"
WorkingFolder=D:\Arcade\RocketLauncher
AppWaitExe=MAME.exe

[25pacman]
Application=D:\Arcade\RocketLauncher\RocketLauncherGame.exe
Parameters=-s "MAME" -r "25pacman"
WorkingFolder=D:\Arcade\RocketLauncher
AppWaitExe=MAME.exe
```

> **Important:** `Application=` uses `RocketLauncherGame.exe`, **not** `RocketLauncher.exe`.
> See *AHK #SingleInstance* below for why.

Key names PCLauncher.ahk recognises: `Application=`, `Parameters=`, `WorkingFolder=`,
`AppWaitExe=`, `FadeTitle=`, `SteamID=`, `ExitMethod=`, `PreLaunch=`, `PostLaunch=`.

> **Important:** Use `Application=` not `ApplicationPath=`. PCLauncher does not recognise
> `ApplicationPath=` and will throw "not set up in RocketLauncherUI" if only that key exists.

---

## Recursive RocketLauncher Launch — Why and How

### Why synthetic wheels need a second RL

A normal wheel (MAME, Nintendo 64, etc.) maps every entry to a single system. HyperSpin
exits, one `RocketLauncher.exe` runs, the emulator loads. One RL instance, start to finish.

A **synthetic wheel** (Favorites, Recently Played, Most Played) is a cross-system list.
A single Favorites wheel might contain a MAME game, a Zinc game, and a PC game side by
side. HyperSpin has no native concept of cross-system wheels — it can only launch entries
from one system using one emulator. The only mechanism available is **PCLauncher**, which
acts as a relay: RL#1 loads PCLauncher for the synthetic wheel, PCLauncher reads the
system-level INI, and calls a second RL (RL#2) with the real system and ROM details.

This is the **only** scenario where two `RocketLauncher` instances must be alive simultaneously.

```
Normal wheel:
  HyperSpin exits
    → RocketLauncher.exe #1  (-s MAME -r btoads2play)
          → MAME.exe

Synthetic wheel (Favorites):
  HyperSpin stays open
    → RocketLauncher.exe #1  (-s Favorites -r btoads2play, loads PCLauncher module, stays alive)
          → PCLauncher.exe
                → RocketLauncherGame.exe #2  (-s MAME -r btoads2play, standalone)
                      → MAME.exe  ← game plays
                      → MAME exits → RL#2 exits → PCLauncher exits → RL#1 exits → HyperSpin restored
```

### Critical: AHK `#SingleInstance` causes silent RL#2 failure

`RocketLauncher.exe` is a compiled **AutoHotkey v1** script. All AHK scripts include a
`#SingleInstance` directive that prevents two instances of the **same executable path**
from running simultaneously. When RL#2 (`RocketLauncher.exe`) starts while RL#1
(`RocketLauncher.exe`) is already alive, AHK detects the path collision, exits RL#2
**immediately and silently** — before it opens a log file, before it loads the emulator
module, before it launches anything.

**Symptom:** Only one `RocketLauncher.exe *32` process ever appears in Task Manager
during a Favorites launch. The AppWaitExe timer runs 15 seconds, then:

> "PCLauncher — There was an error getting the Process ID of your AppWaitExe `ZiNc.exe`"

**Fix (v2.4.7):** SpinDoctor creates `RocketLauncherGame.exe` as a byte-for-byte copy of
`RocketLauncher.exe` in the same directory. AHK's single-instance mutex is keyed to the
**full executable path**, so `RocketLauncherGame.exe` is a completely different identity —
no conflict. PCLauncher entries in the system-level INI use `Application=RocketLauncherGame.exe`.
Both RL instances coexist freely, the emulator loads in ~4 seconds.

The copy is created or refreshed automatically by `ensure_rl_game_exe()` in
`rocketlauncher.py` during every wheel rebuild. Size-based staleness check handles RL
updates. Falls back to `RocketLauncher.exe` if the source is missing or the copy can't
be written.

**How to confirm the bug:** With a game actively running (RL#1 alive), run from CMD:
```
RocketLauncher.exe -s "Zinc" -r "tondemo"
```
Nothing happens. The running game continues. No new process appears. This is `#SingleInstance`
in action — silent exit, no log, no error.

### Critical: No `-p HyperSpin` in recursive call

RL#1 already owns the HyperSpin IPC pipe and has faded the UI. If RL#2 is also launched
with `-p HyperSpin`, it tries to send a second FadeOut to an already-faded, already-owned
pipe. This causes RL#2 to stall or fail with:

> "There was an error waiting for the window ahk_pid XXXX. Please check if you have the
> correct version emulator installed…"

The fix: launch RL#2 **without** `-p HyperSpin`. RL#2 runs in standalone mode, launches
the emulator, waits for it to exit, then returns. PCLauncher (in RL#1) detects RL#2
exiting and returns control to RL#1, which handles the HyperSpin fade-back normally.

### Critical: `AppWaitExe=` required for all PCLauncher entries

RL#2 in standalone mode has no visible window. PCLauncher.ahk's default behaviour is to
wait for a window owned by the application's PID (`Window.Wait ahk_pid XXXX`). When RL#2
has no window, PCLauncher times out after ~30 seconds:

> "There was an error waiting for the window ahk_pid XXXX"

`AppWaitExe=<emulator.exe>` tells PCLauncher to poll for the named process instead of a
window. SpinDoctor resolves the correct emulator exe name by reading the source system's
`Settings/<System>/Emulators.ini` → `Default_Emulator=` → `Settings/Global Emulators.ini`
→ `[<Emulator>]` → `Emu_Path=`. Falls back to the PCLauncher game INI's `AppWaitExe=`
if that chain fails.

The hardcoded `AppWaitExe` timeout in PCLauncher.ahk v2.2.7 is **15 seconds** (not
configurable from INI). With the SingleInstance fix in place, the emulator typically
appears in ~4 seconds.

---

## Toolkit System

SpinDoctor installs maintenance tools into the Toolkit wheel. The `Settings\Toolkit\Emulators.ini`
on this cabinet has a non-default `Rom_Path`:

```ini
[ROMS]
Default_Emulator=PCLauncher
Rom_Path=D:\Arcade\Utilities\Toolkit
```

SpinDoctor detects this by reading the existing `Emulators.ini` before writing tool files,
so executables land in the correct directory (`D:\Arcade\Utilities\Toolkit`) rather than
the default `Modules\PCLauncher\Toolkit`.

---

## Media Layout

HyperSpin looks for media under `Media\<SystemName>\<SubDir>\<GameName>.<ext>`:

| SubDir              | Contents                                   |
|---------------------|--------------------------------------------|
| `Images\Wheel\`     | Wheel art (`.png`)                         |
| `Images\Backgrounds\`| Background images                         |
| `Images\Artwork1-3\`| Additional artwork                         |
| `Themes\`           | Theme files — stored as **`.zip` files** (e.g. `Themes\1942.zip`), not extracted directories |
| `Sound\`            | Sound clips                                |
| `Video\`            | Video previews                             |

SpinDoctor's media mirror copies all of the above from the source system to the synthetic
wheel. Both file-form themes (`.zip`) and directory-form themes are handled.
