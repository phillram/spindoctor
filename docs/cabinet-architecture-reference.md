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
`AppWaitExe=`, `FadeTitle=`, `FadeTitleTimeout=`, `SteamID=`, `ExitMethod=`, `PreLaunch=`, `PostLaunch=`.

> **Important:** Use `Application=` not `ApplicationPath=`. PCLauncher does not recognise
> `ApplicationPath=` and will throw "not set up in RocketLauncherUI" if only that key exists.

The system-level INI that SpinDoctor generates includes `FadeTitle=` and `FadeTitleTimeout=` — see the *FadeTitle* section below for why.

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

### Critical: `FadeTitle=` required to fix "error waiting for window ahk_pid XXXX"

Even with `AppWaitExe=` set, PCLauncher.ahk v2.2.7 (lines 214–224) still tries to find
the emulator's **Win32 window by PID** after the process starts:

```ahk
If !FadeTitle {
    appPrimaryWindow.Wait(AppWaitExeTimeout)   ; waits for a window owned by PID
    ...
}
```

DirectX emulators in exclusive fullscreen — or emulators whose game window is created by a
child process — don't produce a Win32 window detectable by the launcher PID. The wait times
out after ~30 seconds:

> "There was an error waiting for the window ahk_pid XXXX. Please check if you have the
> correct version emulator installed…"

The game keeps running (orphaned); the user must ALT+TAB.

**Fix:** Setting `FadeTitle=` to any non-empty string causes PCLauncher to skip the
`If !FadeTitle` block entirely. Instead it calls `WinWait` with the title string, which
uses case-insensitive partial matching and works regardless of child-process hierarchy.
`AppWaitExe.Process("WaitClose")` then handles exit detection cleanly.

SpinDoctor writes `FadeTitle=` and `FadeTitleTimeout=30` into the system-level PCLauncher
INI for every synthetic wheel entry. The default value is the emulator's registered name
(e.g. `FadeTitle=MAME` for a MAME game, `FadeTitle=Supermodel` for a Model 3 game). AHK's
`WinWait` uses case-insensitive partial matching, so "MAME" matches "MAME [1942 (World)]",
"Supermodel" matches "Supermodel 3.1 UI", and so on — no configuration needed for the
vast majority of emulators.

`FadeTitleTimeout=30` prevents an infinite hang if the emulator crashes before showing a
window: PCLauncher errors after 30 seconds instead of waiting forever.

**Exception — PCLauncher-based source systems** (e.g. "PC Games", "Windows"): the source
system's emulator is PCLauncher itself, which has no identifiable window of its own. These
entries omit `FadeTitle=` and rely on `AppWaitExe=<game.exe>` from the per-game INI.

**When to use `emulator-title set`:** If an emulator's window title has no overlap with
its registered name (e.g. emulator registered as "Model2" but window shows
"Sega Model 2 Emulator"), use:
```bat
spindoctor emulator-title set "Model2" "Sega Model 2"
```
This stores the correction in `config.json` under `emulator_window_titles`. User
corrections take precedence over the built-in default.

---

## Synthetic Wheel Statistics — What Is and Isn't Counted

RocketLauncher records play sessions in `Statistics.ini` files keyed to the **system
name** used at launch. When a game is launched from a synthetic wheel (Favorites, Recently
Played, Most Played), RL#2 runs standalone and attributes the session to the **original
source system** (e.g. "MAME"), not to "Favorites". This is because PCLauncher passes
`-s "MAME" -r "1942"` to RL#2.

However, if a session is somehow attributed to a synthetic system name (e.g. if RL#1 logs
the session before RL#2 runs), SpinDoctor's stats reader (`collect_play_records` in
`recent.py` and `load_all_playtime` in `playtime.py`) **skips** Statistics.ini files for
the three synthetic system names:

```python
SYNTHETIC_SYSTEM_NAMES = frozenset({"Favorites", "Recently Played", "Most Played"})
```

This ensures that playing "Strider" from Favorites never adds it to Recently Played or
Most Played via the synthetic wheel path — only real arcade wheel plays count.

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
| `Themes\`           | Theme files — stored as **`.zip` files** (e.g. `Themes\1942.zip`), not extracted directories. `Default.zip` is the console-wide fallback theme HyperSpin uses for games without a per-game zip. |
| `Sound\`            | Navigation sound clips (`navigate.mp3`, `select.mp3`, `back.mp3`, `letter.mp3`). `navigate.mp3` plays on every left/right cursor move. |
| `Video\`            | Video previews                             |

SpinDoctor's media mirror copies all of the above from the source system to the synthetic
wheel. Both file-form themes (`.zip`) and directory-form themes are handled.

**`Default.zip` fallback** — When a game has no per-game theme zip in the source system,
SpinDoctor copies `Default.zip` from that system's `Themes\` folder as `<GameName>.zip`
in the synthetic wheel. This preserves the console-themed background and video layout
(e.g. the NES theme for Kirby's Adventure) that HyperSpin would show in the native wheel.

**`navigate.mp3` auto-install** — SpinDoctor bundles a navigation click sound and installs
it as `Media\<SystemName>\Sound\navigate.mp3` for each synthetic wheel during `rebuild --apply`
(skip-if-exists). This is the per-system Sound folder, distinct from `Media\Main Menu\Sound\`
which controls active-browsing music at the top-level system wheel.

---

## LEDBlinky

### Key files

| File | Purpose |
|------|---------|
| `C:\LEDBlinky\Settings.ini` | Main application settings — animation modes, emulator config paths, speech, audio |
| `C:\LEDBlinky\Controls.ini` | Per-ROM button assignments (what buttons a game uses) |
| `C:\LEDBlinky\Colors.ini` | Per-ROM LED colors for each assigned button |
| `C:\LEDBlinky\LEDBlinkyControls.xml` | Per-emulator / per-ROM XML control map used by LedBlinky at runtime |
| `C:\LEDBlinky\*.lwa` | Animation files — played for idle / attract / in-game states |

### `Color-RGB.ini` — master color dictionary

LedBlinky's named color system uses `Color-RGB.ini` as its source of truth. Each entry maps a name to R, G, B intensity values in the **0-48 range** (not 0-255):

```ini
[Colors]
Blue=0,0,48      ; equivalent to #0000FF at full brightness
Red=48,0,0       ; equivalent to #FF0000
Orange=48,24,0
```

These names are referenced in two places:
- `Colors.ini` — as values, e.g. `P1_COIN=Orange`
- `LEDBlinkyControls.xml` — as XML attributes, e.g. `color="Red"`

`spindoctor ledblinky colors edit` renames a color in all three files atomically. Hex input (0-255 per channel) is accepted and auto-converted to the 0-48 range.

SpinDoctor's `generate` command writes `Colors.ini` entries in LedBlinky's native named format (`P1_BUTTON1=Red`, `P1_JOYSTICK=White`) by looking up each default color in `Color-RGB.ini`. Older SpinDoctor versions (pre-2.4.21) wrote a legacy hex format (`ledcolor1=FF0000`, `joystick=FFFFFF`) that LedBlinky itself cannot read — if you have an older `Colors.ini`, run `spindoctor ledblinky colors normalize --apply` once to convert it. Legacy hex entries are **not** affected by `colors edit` renames (which match by name, not value).

### `Colors.ini` — multi-player and admin key naming

`Colors.ini` sections support any `P{n}_*` prefix. LedBlinky recognises the following key pattern for each player number `n`:

| Key | Description |
|-----|-------------|
| `P{n}_BUTTON1` … `P{n}_BUTTON8` | Action buttons (1-8 per player) |
| `P{n}_JOYSTICK` | Joystick / directional |
| `P{n}_START` | Player-n Start button |
| `P{n}_COIN` | Player-n Coin/Credit button |

Standard cabinets use P1 and P2. Four-player cabinets extend to P3/P4. SpinDoctor's `fill-defaults --players N` generates blocks for P1 through P{N} all mirrored to the same color.

**Admin / cabinet-level buttons** (functions like Select, Exit, Search, Pause) live on the *next available player slot*. For a 2-player cabinet this is P3; for a 4-player cabinet it's P5. Use `--admin-buttons N --admin-color COLOR` to add these entries automatically:

```ini
P3_BUTTON1=Green
...
P3_BUTTON6=Green
P3_COIN=Green
P3_START=Green
```

**Per-button admin color override** — `spindoctor ledblinky admin-buttons set` walks *every* existing section in `Colors.ini` (not just new ones) and writes individual colors to each `P{player}_BUTTON*` key. This is the right command when you want specific buttons to always show specific colors regardless of the current game (e.g. Select=Green, Exit=Red, Search=Blue):

```bat
spindoctor ledblinky admin-buttons set --player 3 --colors "Red,Blue,Green,White,White,Yellow" --apply
```

This complements `fill-defaults --admin-buttons` (which adds the admin block to new ROM entries) by ensuring every *existing* entry also has the correct admin colors. Run both: `fill-defaults` first to cover gaps, then `admin-buttons set` to normalize all sections to the desired override colors.

**Updating existing uniform entries** — `fill-defaults --override-uniform` extends the fill pass to also update existing sections where every `P*_BUTTON/JOYSTICK/START/COIN` key has the same value (e.g. all White). Sections with intentionally mixed colors are never touched. Use `--no-add-keys` alongside `--override-uniform` to restrict the update to only the keys already present — no new button keys are inserted — which is useful when an entry deliberately has fewer buttons than the `--buttons` count:</p>

```bat
:: Re-color all uniform entries to White without adding new keys
spindoctor ledblinky fill-defaults --color White --override-uniform --no-add-keys --apply
```

### `Color-RGB.ini` — brightness

Each named color is stored as three 0-48 integer intensities (not 0-255). `spindoctor ledblinky colors brightness --scale PCT` normalizes every color's dominant channel to 48 first, then scales by `PCT/100`. This means:

- **100 %** = every color at maximum brightness (dominant channel = 48). Any colors previously stored at reduced intensity are boosted up. This ensures all buttons (P1, P2, admin, Start) are uniformly bright.
- **50 %** = half brightness (dominant channel = 24).
- **10 %** = near-dark night mode.
- **0 %** = all off.

Pure-black entries (0,0,0) are left untouched. The operation is reversible by running at 100 % to restore full brightness, or restoring from the auto-generated `.bak` backup.

Auto-backups are routed to subsystem-specific subfolders under `config.backup_dir` when that field is configured:

| Operation | Backup subfolder |
|-----------|-----------------|
| LEDBlinky (fill-defaults, patch-settings, normalize, colors edit, brightness, admin-buttons set) | `config.backup_dir/LEDBlinky/` |
| HyperSpin database saves (update-db, batch-edit, fav/recent/stats rebuild) | `config.backup_dir/HyperSpin/` |
| RocketLauncher INI writes (generate-config) | `config.backup_dir/RocketLauncher/` |

If `backup_dir` is not configured, backups land next to the source file (timestamped `.bak` sibling).

### `controls.ini` format

SpinDoctor generates `controls.ini` from `mame -listxml` output (cached in `~/.spindoctor/mame_listxml_cache/`). Existing entries are preserved unless `--overwrite` is passed.

The correct runtime format uses LedBlinky's own key names for each control present in the game. LedBlinky reads **every key it does not recognise as metadata as a literal control identifier** — if unrecognised keys are present (e.g. `P1_NUMBUTTONS`, `P1_CONTROLS`) they silently replace the real button names in the control list, breaking LED mapping for that ROM.

Correct format for a 2-player, 1-button, 8-way-joystick game (`005`):

```ini
[005]
numPlayers=2
alternating=0
P1_BUTTON1=1
P1_JOYSTICK=1
P1_START=1
P1_COIN=1
P2_BUTTON1=1
P2_JOYSTICK=1
P2_START=1
P2_COIN=1
```

Keys recognised as metadata (not treated as control names): `numPlayers`, `alternating`, `description`.  All other keys become control identifiers.

**SpinDoctor versions prior to 2.4.22** generated the wrong format (`P1_NUMBUTTONS=1`, `P1_CONTROLS=JOYSTICK_8WAY,BUTTON1`). If your `controls.ini` was generated by an older version, regenerate it:

```bat
spindoctor ledblinky generate --overwrite --apply
```

### `LEDBlinkyControls.xml` — structure

The XML is the runtime control map LedBlinky uses to determine per-ROM LED state (which buttons are on, their colors, and their input codes). It is **organised by emulator**, not globally:

```xml
<dat>
  <emulator emuname="MAME" emuDesc="MAME Defaults and Control Overrides">
    <controlGroup groupName="DEFAULT" ...>   <!-- fallback for all MAME ROMs -->
      <player number="0">                    <!-- shared/UI controls -->
        <control name="UI_CANCEL" alwaysActive="1" color="Red" />
      </player>
      <player number="1">                    <!-- per-player game controls -->
        <control name="P1_BUTTON1" alwaysActive="0" color="White" />
        ...
      </player>
    </controlGroup>
    <controlGroup groupName="005" ...>       <!-- ROM-specific override -->
      <player number="0"> ... </player>
      <player number="1"> ... </player>
    </controlGroup>
  </emulator>
  <emulator emuname="AAE" emuDesc="">
    ...
  </emulator>
</dat>
```

Key rules:
- A ROM-specific entry **must be placed under the correct `<emulator>` section**. An entry under `AAE` is never matched when MAME launches a game, even if the `groupName` is correct.
- `player number="0"` holds UI / shared controls (UI_CANCEL, UI_PAUSE, etc.).
- `player number="1"` and `player number="2"` hold P1 / P2 game controls.
- `alwaysActive="1"` keeps an LED permanently on during gameplay regardless of input detection. Without it, LedBlinky only lights the button when it detects the mapped input code being pressed — which fails if the physical button sends joystick events and only keyboard codes are mapped.
- The `color=` attribute in the XML is the **fallback** color. If a `Colors.ini` entry exists for the same ROM, Colors.ini takes precedence.

LedBlinky resolves the control profile for a launched ROM in this order:
1. ROM-specific `controlGroup` in the XML under the matching emulator → `Controls: [EMULATOR-ROM]` in the log
2. DEFAULT `controlGroup` under the matching emulator → `Controls: [EMULATOR-DEFAULT]`
3. OTHER-DEFAULT (for emulators with no XML section at all)

`controls.ini` entries (when present and correctly formatted) define **which control names** appear in the control list. The XML then provides input codes and `alwaysActive` settings for those names.  If `controls.ini` has an entry for a ROM, it overrides the XML's control list — so a broken `controls.ini` entry will suppress the ROM-specific XML entry entirely.

### `controls.ini` and `colors.ini` — generation

### `Settings.ini` — idle animation and in-game behavior

Two keys control behaviors that aren't obvious in LedBlinky's configuration UI:

**`[GameOptions] GamePlayLWAFile=`**
Controls what happens to buttons **not used by the current game** while a game is running. The default value `<Random>` makes LedBlinky play a random animation on all unassigned buttons — which looks like random flashing on unused buttons.

- **`""` (empty)** — LedBlinky falls back to each button's `defaultInactive` color from `LEDBlinkyControls.xml`. The DEFAULT control group has `defaultInactive="0,0,0,0"`, so unused buttons go off. Recommended for a clean gameplay experience.
- **`lwa\MyAnim.lwa`** (relative path from `ledblinky_dir`) — LedBlinky plays that animation on all unused buttons during gameplay. This is a global setting; `Settings.ini` has no per-game or per-system override for this key.

`.lwa` animation files are stored under `<ledblinky_dir>\lwa\` and its subdirectories.

**`[FEOptions] FELWAFile=`**
Controls the animation played on buttons while browsing the HyperSpin frontend. `<Random>` picks a different animation file every time. Set to a specific `.lwa` path (relative to `ledblinky_dir`, e.g. `lwa\Slow Fade.lwa`) for a consistent smooth effect, or empty for static colors.

SpinDoctor patches both keys with `spindoctor ledblinky patch-settings`. A timestamped `.bak` copy of `Settings.ini` is written before any change.

```bat
spindoctor ledblinky patch-settings --apply                          :: fix in-game unused-button flash
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --apply :: also fix idle animation
```

### `LEDBlinkyControls.xml` and HyperSpin Search compatibility

LedBlinky injects process hooks (`Start_Hyperspin_Process` / `Exit_Hyperspin_Process`) into the HyperSpin per-menu `Settings.ini` files for Search, Genre, and Favorites. These hooks crash HyperSpin's overlay launcher for those menus. Additionally, `LEDBlinkyControls.xml` has no entry for the Search special menu, causing a lookup failure.

SpinDoctor diagnoses and repairs both issues:

```bat
spindoctor ledblinky check         :: read-only scan
spindoctor ledblinky fix --apply   :: comment out hooks + add XML entries
```

### Diagnosing LEDs not lighting during gameplay

When player buttons do not light up (even when pressed) while Coin/Start buttons work:

1. **Wrong `controls.ini` format (SpinDoctor pre-2.4.22)** — The log shows `Controls: [EMULATOR-ROM]` but the control list contains `P1_NUMBUTTONS` / `P1_CONTROLS` instead of `P1_BUTTON1` / `P1_JOYSTICK`. Regenerate: `spindoctor ledblinky generate --overwrite --apply`.

2. **No per-ROM entry in `LEDBlinkyControls.xml`** — The log shows `Controls: [MAME-DEFAULT]`. The MAME DEFAULT group has `alwaysActive="0"` on all player buttons. Buttons only light when input codes fire, but if the cabinet uses joystick events and the mapping only has keyboard codes (`KEYCODE_A`), they never fire. Fix: add a ROM-specific XML entry under the correct emulator section with `alwaysActive="1"` on player buttons.

3. **ROM-specific XML entry under the wrong emulator** — An entry for a MAME ROM placed under `emuname="AAE"` is never matched. Check `LEDBlinkyLog.txt`: if it says `Controls: [MAME-DEFAULT]` the entry is missing or mis-placed.

4. **Input code mismatch** — Physical buttons send `JOYCODE_1_BUTTON1` but the XML only maps `KEYCODE_A`. LedBlinky never detects the press. Setting `alwaysActive="1"` bypasses input detection entirely and is the preferred approach for always-on arcade buttons.

### Diagnosing colors not applying at runtime

When game colors show as white despite correct `Colors.ini` entries, the most common causes are:

1. **Name mismatch** — the name RocketLauncher sends to LedBlinky does not match the `[romname]` section header in `Colors.ini`. Check `LEDBlinkyLog.txt` for the exact name received.
2. **Legacy hex format** — `Colors.ini` entries use `ledcolor1=FF0000` format that LedBlinky cannot read. Run `colors normalize --apply`.
3. **No `LEDBlinkyControls.xml` per-game entry** — LedBlinky uses its DEFAULT control group and may ignore `Colors.ini` overrides for that game.
4. **`Use Color File` disabled** — LedBlinky Settings UI has a toggle; if off, `Colors.ini` is never consulted.

```bat
spindoctor ledblinky inspect-rom 005   :: read Colors.ini, controls.ini, XML, listxml for ROM "005"
```

`inspect-rom` reports what LedBlinky would see for a specific ROM, flags any mismatches, and prints the path to `LEDBlinkyLog.txt` with instructions on what to search for.
