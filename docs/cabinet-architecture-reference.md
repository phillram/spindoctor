# Cabinet Architecture Reference

> **Note:** This documents one specific cabinet's layout. Your setup may be different.
> SpinDoctor reads paths from your existing configuration files rather than assuming
> fixed locations — always check your own `Emulators.ini` files if something doesn't work.

---

## Platform

| Property | Value |
|----------|-------|
| OS | **Windows 7** |
| HyperSpin runtime | Adobe AIR (H.264 Main Profile ≤ Level 4.0 only — see video section) |
| Python target | Must work on Windows 7; use `pathlib.Path` for all path construction |
| Regex replacements | Always use `lambda m: replacement` in `re.sub`/`re.subn` when the replacement string may contain a Windows path — backslash sequences like `\U`, `\N`, `\A` are misread as regex backreferences and raise `re.error` |

Both the **CLI and the GUI** must function correctly on Windows 7. Windows-specific bugs
(path separator handling, regex escape processing, Tk widget compatibility) are invisible on
macOS development but break the cabinet.

---

## Directory Layout

> **Important:** HyperSpin is installed directly at `D:\Arcade\` — there is **no** `D:\Arcade\HyperSpin\` subfolder. `hyperspin_dir` in `config.json` is `D:\Arcade`. `Databases\`, `Media\`, and `Settings\` are all direct children of `D:\Arcade\`.

```
D:\Arcade\                            ← HyperSpin root (= hyperspin_dir in config)
├── Databases\                        ← HyperSpin game databases
│   ├── MAME\
│   │   └── MAME.xml
│   ├── Favorites\
│   │   └── Favorites.xml             ← SpinDoctor writes/manages this
│   └── ...
├── Media\                            ← HyperSpin media (= hyperspin_dir/Media)
│   ├── MAME\
│   │   ├── Images\Wheel\
│   │   ├── Images\Backgrounds\
│   │   ├── Themes\               ← themes stored as per-game .zip files
│   │   ├── Sound\
│   │   └── Video\
│   └── Favorites\                ← SpinDoctor mirrors media here during rebuild
├── Settings\                         ← HyperSpin per-system wheel settings
│   ├── Main Menu.ini                 ← top-level wheel settings
│   ├── MAME.ini                      ← MAME wheel settings
│   ├── Favorites.ini                 ← HyperSpin wheel settings (hyperlaunch=true)
│   ├── 4-Player Games.ini            ← contains [video defaults] path= redirect (see below)
│   └── ...                           ← one .ini per HyperSpin system
├── RocketLauncher\                   ← RocketLauncher root (= rocketlauncher_dir in config)
│   ├── RocketLauncher.exe
│   ├── RocketLauncherGame.exe        ← SpinDoctor-created copy; used as RL#2 for synthetic wheels (see below)
│   ├── Data\
│   │   └── Statistics\
│   │       ├── MAME.ini              ← per-system play stats (RL writes these; see Statistics section)
│   │       └── ...                   ← one .ini per system that has been launched
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
│       ├── MAME\                     ← MAME ROMs (legacy; ROMs moved to J:\Games\MAME)
│       ├── Nintendo 64\
│       └── ...
├── Emulators\                        ← emulators (= emulators_dir in config)
│   ├── MAME\
│   │   └── mame64.exe
│   ├── RetroArch\
│   ├── Dolphin Ishiiruka\
│   └── ...
├── LEDBlinky\                        ← LEDBlinky install (= ledblinky_dir in config)
│   ├── LEDBlinky.exe
│   ├── Settings.ini
│   ├── controls.ini
│   ├── Colors.ini
│   ├── LEDBlinkyControls.xml
│   ├── Color-RGB.ini
│   └── lwa\
└── Utilities\
    └── Toolkit\                      ← SpinDoctor tool executables live here
        ├── exit.exe
        ├── soundfix_mame.exe
        └── ...
```

### ROM storage

ROMs live on a separate drive: `J:\Games\` (= `roms_dir` in `config.json`). This drive was moved from `D:` at some point; `generate-config` detects this and updates `Rom_Path=` entries accordingly.

```
J:\Games\
├── MAME\          ← shared by MAME and all MAME subsystem wheels
├── Nintendo 64\
├── Daphne\        ← Daphne LaserDisc system (see Daphne section below)
│   ├── lair.txt   ← RL "ROM" for Dragon's Lair — this is a Daphne framefile, NOT a placeholder
│   ├── esh.txt
│   ├── ... (one .txt per game)
│   ├── roms\      ← chip ROM zips read by daphne.exe via -homedir J:\Games\Daphne
│   │   ├── lair.zip
│   │   └── ...
│   ├── vldp\      ← VLDP video files, one subfolder per game
│   │   ├── lair\
│   │   │   ├── dl-slates.m2v
│   │   │   └── ...
│   │   └── ...
│   └── vldp_dl\   ← Digital Leisure variant VLDP files
└── ...
```

---

## SpinDoctor Configuration and Storage

> For a complete listing of every file SpinDoctor creates and manages — with copy-pastable paths — see **[SpinDoctor Files](spindoctor-files.md)**.

### Configuration file

SpinDoctor stores its configuration in a single JSON file:

```
C:\Users\<username>\.spindoctor\config.json
```

(equivalently `%USERPROFILE%\.spindoctor\config.json`)

All paths are absolute. This cabinet's `config.json`:

```json
{
  "roms_dir":       "J:\\Games",
  "hyperspin_dir":  "D:\\Arcade",
  "emulators_dir":  "D:\\Arcade\\Emulators",
  "rocketlauncher_dir": "D:\\Arcade\\RocketLauncher",
  "ledblinky_dir":  "D:\\Arcade\\LEDBlinky",
  "output_dir":     "J:\\spindoctor\\output",
  "backup_dir":     "J:\\spindoctor\\backups",
  "atomic_tmp_dir": "J:\\spindoctor\\temps"
}
```

**Derived paths** (not stored in config, always computed at runtime):

| Property | Derived as | Example |
|----------|-----------|---------|
| `config.media_dir` | `hyperspin_dir / "Media"` | `D:\Arcade\Media` |
| `config.databases_dir` | `hyperspin_dir / "Databases"` | `D:\Arcade\Databases` |

### Output directories

SpinDoctor writes all its output files to `output_dir`, never into the HyperSpin or RocketLauncher source trees. Backups go to `backup_dir`. Atomic writes use `atomic_tmp_dir` as a staging area (same drive as the destination to allow atomic rename).

```
J:\spindoctor\
├── output\     ← generated XML files, rebuilt databases, run logs (Save Log), etc.
├── backups\    ← timestamped .bak copies before any destructive change
│   ├── HyperSpin\
│   ├── LEDBlinky\
│   └── RocketLauncher\
└── temps\      ← staging area for atomic writes (same drive as output)
```

The GUI's status-bar **Save Log** checkbox (off by default) writes a `.txt` backup of each finished command's exact output straight into `output_dir` — same rule as everything else on this page, no separate config key.

MAME `listxml` cache (used by `ledblinky generate`) is stored at:
```
%USERPROFILE%\.spindoctor\mame_listxml_cache\
```

---

## HyperSpin Settings INIs and the Video Redirect

### Location

HyperSpin stores per-system wheel settings in:

```
D:\Arcade\Settings\<System>.ini
```

(i.e. `hyperspin_dir / "Settings" / f"{system}.ini"`)

Each INI can contain multiple sections controlling the wheel's appearance and launch behaviour. The one SpinDoctor cares about is `[video defaults]`.

> **When renaming a system:** HyperSpin will display "Cannot find &lt;NewName&gt;.ini" and refuse to open the wheel until `Settings\<OldName>.ini` is renamed to `Settings\<NewName>.ini`. This is purely a filename rename — no content changes are needed. It is separate from the other files that must be updated when renaming (Main Menu.xml, `RocketLauncher\Settings\<System>\`, HyperSpin `Databases\<System>\`). SpinDoctor does not manage Settings INI files.

### `[video defaults]` — video path redirect

MAME subsystem wheels ("4-Player Games", "Driving Games", "Gun Games", etc.) do not have their own video collection. Instead they share the MAME video folder. HyperSpin is told where to look via the `[video defaults]` section in the system's Settings INI:

```ini
; D:\Arcade\Settings\4-Player Games.ini
[video defaults]
path=D:\Arcade\Media\MAME\Video\
```

**How SpinDoctor reads this** — `_read_hs_video_dir(settings_dir, system)` in `medialink.py` reads `[video defaults]` → `path=` and returns the path if it exists on disk. `plan_mirror` accepts a `video_dir_override` kwarg: when the source system has no `Video\` directory of its own, the override directory is scanned instead.

This is called in `fav rebuild` (`favorites.py`) and `recent rebuild` / `stats build-wheel` (`recent.py`) with a per-system cache to avoid re-reading the same INI multiple times.

**Without this redirect**, games from MAME subsystem wheels silently skip video during a synthetic wheel rebuild because `Media\4-Player Games\Video\` does not exist. The video file (e.g. `D:\Arcade\Media\MAME\Video\iceclmrdxbox.mp4`) is present but never found.

---

## Intro Video Randomizer

A separate, third-party AutoHotkey/launcher script (not part of HyperSpin, RocketLauncher, or SpinDoctor) that runs on cabinet boot and copies a randomly-chosen video over HyperSpin's startup video, so the intro clip varies between sessions. SpinDoctor does not run this script — `spindoctor introvideo` only manages the pool of candidate videos and the INI file the script reads. See [Command reference → Intro Video Randomizer](commands.md#intro-video-randomizer) for the CLI.

### File paths (example cabinet)

```
D:\Arcade\Media\Frontend\Video\Intro.mp4                                  ← FileToRandomize: the file HyperSpin actually plays on boot
D:\Arcade\Media\Frontend\Video\Intro Video Randomizer\Random.ini          ← the randomizer's own config (config.intro_randomizer_dir points here)
D:\Arcade\Media\Frontend\Video\Intro Video Randomizer\Intro Videos\       ← Folder: the pool of candidate videos
D:\Arcade\Media\Frontend\Video\Intro Video Randomizer\Intro Videos\Backup\  ← never scanned or touched by SpinDoctor
```

`config.intro_randomizer_dir` is the folder containing `Random.ini` — set once via the Setup tab or `spindoctor config set intro_randomizer_dir <path>`. The video pool folder (`Folder=`) and the boot-video target (`FileToRandomize=`) are **not** separate config fields; SpinDoctor reads both out of `Random.ini` itself on every command, since the randomizer script already treats that INI as the single source of truth for its own paths.

### `Random.ini` format

```ini
[Randomize1]
Option=1
Folder=D:\Arcade\Media\Frontend\Video\Intro Video Randomizer\Intro Videos
FileToRandomize=D:\Arcade\Media\Frontend\Video\Intro.mp4
FileList=Arcade Loading Screen.mp4|5 Second loading bar.mp4|Capcom Intro.mp4
RandomList=Arcade Loading Screen.mp4|Capcom Intro.mp4
```

`FileList=` and `RandomList=` are pipe (`|`) delimited filename lists (bare filenames, no path). SpinDoctor treats them as one concept — "is this video in rotation" — and keeps them in sync: `introvideo add` appends a filename to both, `introvideo remove` drops it from both. Nothing in SpinDoctor currently relies on a file being present in one list but not the other.

### How SpinDoctor edits it (`introvideo.py`)

- **Read** (`load_randomizer`) — line-based scan of the `[Randomize1]` section (not `configparser`, to sidestep its lower-casing of keys); `FileList=`/`RandomList=` are split on `|`.
- **Write** (`add_videos` / `remove_videos`, `add_video`/`remove_video` are single-item wrappers around them) — surgical: only the `FileList=` and `RandomList=` lines are rewritten, using the same verbatim-preserving technique as `rocketlauncher.rewrite_pclauncher_application`. Every other line, key, comment, and the file's original key casing survive untouched.
- **`introvideo add <file>...`** copies each source file into `Folder=` (skip, never overwrite, if a same-named file is already there) and appends the filename to both lists. Accepts one or more files in a single call. Every source is validated up front — before any copy happens — so a missing file anywhere in the batch aborts cleanly with nothing copied and `Random.ini` untouched, rather than leaving earlier files in that call copied but unregistered. Dry-run by default; `--apply` commits.
- **`introvideo remove <filename>...`** only edits the two INI lists — **the video file(s) on disk are never deleted**. This keeps the operation non-destructive and trivially reversible: `introvideo add <path-to-the-still-present-file>` re-registers it. Accepts one or more filenames in a single call.
- **`introvideo list`** unions the on-disk video files (scanning `Folder=`, excluding the `Backup\` subfolder — non-recursive, so nothing under `Backup\` is ever considered) with the INI's `FileList=`/`RandomList=` entries, surfacing both orphaned disk files (present on disk, not registered) and dangling INI references (registered, missing from disk).
- **Backups** — before either write, if `config.backup_before_modify` is on (the default), a timestamped copy of `Random.ini` is written to `config.backup_dir/IntroVideoRandomizer/` (or next to the file if `backup_dir` is unset) — see the backup-routing table above. A multi-file `add`/`remove` call shares a single backup across the whole batch rather than writing one per file.

---

## RocketLauncher Play Statistics

### File location

RL writes per-system play statistics to:

```
D:\Arcade\RocketLauncher\Data\Statistics\<System>.ini
```

(i.e. `rocketlauncher_dir / "Data" / "Statistics" / f"{system}.ini"`)

One `.ini` file exists per system that has had at least one game launched.

### File format

Each file contains a top-level aggregate section (`[General]`, `[TopTen_Time_Played]`, etc.) followed by one section per game that has been played:

```ini
[General]
...

[005]
Number_of_Times_Played=1
Last_Time_Played=Saturday June 13, 2026 07:51:53 AM
Average_Time_Played=0
Total_Time_Played=0

[pc_1942]
Number_of_Times_Played=-1
Last_Time_Played=Saturday June 13, 2026 07:51:19 AM
Average_Time_Played=0
Total_Time_Played=0
```

**Key names used by SpinDoctor:**

| Key | Used by | Notes |
|-----|---------|-------|
| `Last_Time_Played` | Recently Played (`_read_stats_file`) | Date format: `"Saturday June 13, 2026 07:51:53 AM"` |
| `Number_of_Times_Played` | Most Played (`_read_playstats_file`) | RL starts at `-2` (uninitialized) and counts up; `-1` means played once |
| `Total_Time_Played` | Most Played | Seconds |

> **Failure mode (pre-v2.5.3):** `_read_stats_file` looked for `Last_Played` / `LastPlayed` — neither key is written by current RocketLauncher builds. The correct key is `Last_Time_Played`. With no valid timestamp, every record was silently skipped, producing a "0 parseable records" result and an empty Recently Played wheel.

The Toolkit system's stats file (`Data\Statistics\Toolkit.ini`) is explicitly excluded from stats collection so that tool runs (Refresh Favorites, Refresh Recently Played, etc.) never appear in the synthetic wheels.

---

## Settings Layout: Folder vs Flat

RocketLauncher supports two layouts for per-system routing. This cabinet uses the
**folder layout** (produced by HyperHQ):

| Layout  | File location                        | Section | Key read              |
|---------|--------------------------------------|---------|-----------------------|
| Folder  | `Settings/<System>/Emulators.ini`    | `[ROMS]`| `Default_Emulator=`   |
| Flat    | `Settings/<System>.ini`              |`[Settings]`| `Default_Emulator=` |

SpinDoctor writes **both** files for new systems so the cabinet works regardless of which
layout RL prefers. For existing systems, SpinDoctor performs an in-place `Rom_Path=` update
only — all other keys are preserved.

**Some emulator families share a single ROM folder.** This cabinet has two known families:

| Family | Shared folder | Systems | Emulators |
|--------|--------------|---------|-----------|
| MAME | `J:\Games\MAME` | MAME (Vector), MAME Atari Classics, 4-Player Games, … | MAME, MAME (XBOX 4P DSW), … |
| Daphne | `J:\Games\Daphne` | Daphne, American Laser Games, WoW Action Max | Daphne, Daphne Singe, Daphne Singe (WoW Action Max) |

SpinDoctor applies a three-tier strategy when running `generate-config` for these systems:

1. **No existing INI (new file):** `generate-config` derives `Rom_Path` as the system-named
   folder first. If that folder doesn't exist, it checks whether the system's emulator
   belongs to a known family (MAME or Daphne) and falls back to that family's shared folder
   when it exists.  Examples:
   - `MAME (Vector)` → `roms_dir\MAME` (MAME keyword in system name)
   - `American Laser Games` → emulator `Daphne` → `roms_dir\Daphne`

2. **Existing file with `Default_Emulator` in a known family:**
   - **MAME family — relative `Rom_Path`** (e.g. `..\Games\MAME` as written by RLUI):
     resolved from the RL root directory.  Preserved if the resolved directory exists;
     replaced with `roms_dir\MAME` if it has gone stale (ROMs moved from D: to J:).
   - **Any family — absolute `Rom_Path` that doesn't exist:** replaced with the family's
     shared folder if that folder exists.  Covers cases like `J:\Games\American Laser Games`
     appearing in an old backup when ROMs actually live in `J:\Games\Daphne`.

3. **Existing file has a valid absolute `Rom_Path`:** the filesystem-existence guard fires
   — the existing path is a real directory but the system-derived path does not exist —
   so the file is left unchanged (`preserved (custom path)` in the dry-run table).

For a permanent explicit override that survives any restore, use `config system set --rom-path`:

```bat
spindoctor config system set "MAME (Vector)" --rom-path "J:\Games\MAME"
spindoctor config system set "4-Player Games" --rom-path "J:\Games\MAME"
spindoctor config system set "American Laser Games" --rom-path "J:\Games\Daphne"
```

This writes `rom_path` under `system_overrides` in `config.json`; that value always wins
regardless of what folders exist on disk.  Use `--emulator` in the same command when the
system's `Default_Emulator=` also needs to be set for the first time.

> **Daphne+RL ROM layout:** RL "ROMs" for Daphne games are `.txt` **framefile** files
> (e.g. `J:\Games\Daphne\lair.txt`) — not empty placeholders; they contain video frame
> timing data.  The Daphne.ahk module passes the full path as `-framefile
> "J:\Games\Daphne\lair.txt"` to daphne.exe.  Chip ROMs live at
> `J:\Games\Daphne\roms\<game>.zip` and are found by daphne.exe via
> `homedir = J:\Games\Daphne` in `Daphne.ini` (not by RL).  If RL reports "No valid roms
> found in the archive lair.zip", a chip ROM zip is in `J:\Games\Daphne\` instead of
> `J:\Games\Daphne\roms\` — move it there.  See the [Daphne section](#daphne-laserdisc-games--file-layout-and-configuration) for full details.

> **Failure mode (pre-v2.4.27):** Running `generate-config --apply` created a per-system
> `Emulators.ini` for MAME (Vector) with `Rom_Path=J:\Games\MAME (Vector)`.  Because RL
> checks per-system settings **before** `Global Emulators.ini`, inserting that file into
> the lookup chain caused RL to find the wrong (non-existent) path and refuse to launch any
> MAME (Vector) ROM.  Pre-generate-config, RL fell through to the global file and used the
> correct shared path.

### Per-system Emulators.ini — real format

This is what a real per-system `Emulators.ini` on this cabinet looks like (minimal — no
`[<Emulator>]` section, no `Emu_Path`):

```ini
[ROMS]
Default_Emulator=MAME
Rom_Path=..\Games\MAME
```

```ini
[ROMS]
Default_Emulator=SSF
Rom_Path=..\Games\Sega Saturn
```

The path is relative to the `Settings\` folder, i.e. `..\Games\MAME` resolves to
`D:\Arcade\RocketLauncher\Games\MAME`. After a ROM drive migration SpinDoctor updates
it to an absolute path: `Rom_Path=J:\Games\MAME`.

**What `Default_Emulator` maps to** — RocketLauncher reads this value and then looks
up `[<EmulatorName>]` in `Global Emulators.ini` to find `Emu_Path`. The emulator
names used on this cabinet include: `MAME`, `RetroArch`, `SSF` (Sega Saturn),
`Mednafen`, `NullDC` / `Demul` (Dreamcast), `Project64`, `PCSX2`, `ZiNc`, etc.
SpinDoctor only knows a subset of these. For systems whose emulator it does not
recognise, it leaves `Default_Emulator` unchanged (see note below).

> **Critical — never overwrite `Default_Emulator`:** Before this was fixed, SpinDoctor
> replaced the entire per-system file with a template and changed `Default_Emulator` to
> its fallback guess (`RetroArch`) for any system not in its built-in map.  This caused
> RocketLauncher to look for `[RetroArch]` in the per-system file, find the bare section
> SpinDoctor had injected (no `Emu_Path`), stop its lookup chain there, and report
> *"Could not find an Emu_path for RetroArch"* for every game on every console.

The folder-layout `Emulators.ini` for synthetic wheels (Favorites, Recently Played,
Most Played, Recompiled) looks like — SpinDoctor writes these in full:

```ini
[ROMS]
Default_Emulator=PCLauncher
Rom_Path=D:\Arcade\RocketLauncher\Modules\PCLauncher\Favorites
Rom_Extension=ini

[PCLauncher]
Rom_Path=D:\Arcade\RocketLauncher\Modules\PCLauncher\Favorites
Rom_Extension=ini
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

> **Critical:** Both files MUST have `[PCLauncher]` with `Rom_Extension=ini`. RL v1.2
> reads `Rom_Extension` from the emulator section (`[PCLauncher]`) first. When no
> `[PCLauncher]` section exists in the system file, RL falls back to `Global Emulators.ini`'s
> `[PCLauncher]` which may omit `Rom_Extension=ini`. Without it RL uses its built-in
> default extension list (`zip|rar|7z|lha|…`) and cannot find the placeholder `.ini` files,
> producing: *"Cannot find Rom \<game\> In any Rom_Paths provided … with any provided
> Rom_Extension: zip|rar|7z|lha|lzh|gzip|tar|"*.

---

## Global Emulators.ini — Structure and Emulator Lookup Chain

`Settings\Global Emulators.ini` is the master emulator registry. Every emulator on the
cabinet has a section here. RocketLauncher's lookup chain when launching a game:

1. Read `Default_Emulator=` from the per-system `Settings\<System>\Emulators.ini` `[ROMS]` section
2. Look for `[<EmulatorName>]` in the per-system file — if `Emu_Path=` is found, use it
3. Fall back to `[<EmulatorName>]` in `Settings\Global Emulators.ini` — read `Emu_Path=` from there

Because the per-system files on this cabinet have NO `[<Emulator>]` section, RL always
falls back to step 3 for `Emu_Path`. **This is why adding a bare `[<Emulator>]` section
without `Emu_Path=` to a per-system file breaks launches** — RL finds the section in step 2,
reads no `Emu_Path`, stops, and reports *"Could not find an Emu_path"* instead of
continuing to step 3 where the path is actually defined.

### Per-emulator section format

Each emulator section in `Global Emulators.ini` uses these keys:

```ini
[MAME]
Emu_Path=..\Emulators\MAME\mame64.exe
Rom_Extension=zip|7z|txt
Module=MAME.ahk
Pause_Save_State_Keys=...
Pause_Load_State_Keys=...

[RetroArch]
Emu_Path=..\Emulators\RetroArch\retroarch.exe
Rom_Extension=rar|7z|zip|sfc|gba|...
Module=RetroArch.ahk
Pause_Save_State_Keys=...
Pause_Load_State_Keys=...

[SSF]
Emu_Path=..\Emulators\SSF\SSF.exe
Rom_Extension=7z|zip|cue|ccd|iso|mds|mdf|rar
Module=SSF.ahk
Pause_Save_State_Keys=
Pause_Load_State_Keys=

[PCLauncher]
Module=PCLauncher.ahk
Emu_Path=..\Emulators\PCLauncher\PCLauncher.exe
Pause_Save_State_Keys=
Pause_Load_State_Keys=
Rom_Extension=
```

Key points:
- `Emu_Path=` is **relative to the `Settings\` folder** (i.e. `..\Emulators\...` resolves
  to `D:\Arcade\RocketLauncher\Emulators\...`). Some entries under `Games\` use
  `..\Games\<name>\<exe>` for emulators installed alongside their ROMs (e.g. AAE, Daphne).
- `Emu_Path=` is the key RocketLauncher reads. SpinDoctor's `generate-config` uses
  `Emu_Path=` when creating a new `Global Emulators.ini` from scratch.
- This cabinet has 40+ emulator sections including many variant instances
  (`MAME (Gun Games)`, `RetroArch (MultiPlayer)`, `Demul58`, etc.).

### `[PCLauncher]` — Rom_Extension requirement

The `[PCLauncher]` section **must** have `Rom_Extension=ini`. PCLauncher "ROMs" are
always per-game INI files stored in `Modules\PCLauncher\<system>\<game>.ini`; the actual
application executable (`.exe`, `.lnk`, etc.) is referenced inside the INI. This applies
to both synthetic wheels (Favorites, Recently Played, Most Played, Recompiled) and real PC/Windows/Steam
systems.

When `Rom_Extension` is missing or set to a non-ini value, RL falls back to its built-in
default extension list (`zip|rar|7z|lha|lzh|gzip|tar|`) and cannot find the placeholder
`.ini` files.

SpinDoctor's `generate-config` (and `mainmenu add` for synthetic wheels) writes
`[PCLauncher]` with `Rom_Extension=ini` directly in the **per-system settings files** so
that RL reads the correct extension from the system file rather than falling back to
`Global Emulators.ini`.

> **SpinDoctor does not modify an existing `Global Emulators.ini`.** It only creates the
> file if none exists, covering the common emulators in its built-in map. The cabinet's
> full `Global Emulators.ini` (with 40+ hand-configured emulators) was set up manually
> and is never overwritten by SpinDoctor. When SpinDoctor creates a new Global Emulators.ini,
> it writes `Rom_Extension=ini` for the `[PCLauncher]` section.

---

## Daphne (LaserDisc Games) — File Layout and Configuration

Daphne uses **three separate file types** that live in three different locations. Getting any one wrong produces a different error.

### File layout

| File type | Location | Who reads it |
|-----------|----------|-------------|
| Framefile (`.txt`) | `J:\Games\Daphne\<game>.txt` | RocketLauncher (treats it as the ROM) + daphne.exe (`-framefile` arg) |
| Chip ROMs (`.zip` containing `.bin` files) | `J:\Games\Daphne\roms\<game>.zip` | daphne.exe directly (via `homedir`) |
| VLDP video files | `J:\Games\Daphne\vldp\<game>\*.m2v` | daphne.exe (path read from framefile) |

### Why `.txt` files are the RL "ROM"

`Global Emulators.ini` `[Daphne]` has `Rom_Extension=txt`. RocketLauncher therefore scans `Rom_Path` (= `J:\Games\Daphne`) for `.txt` files, finds `lair.txt`, and passes it to the Daphne.ahk module as `romExtension=.txt`. Because `.txt` is not in the 7-zip format list (`zip|rar|7z|lha|...`), the module skips extraction entirely and passes the full path as `-framefile` to daphne.exe.

**Never put the chip ROM `.zip` in `J:\Games\Daphne\`.** If `lair.zip` is there and `lair.txt` is absent, RL finds the zip, tries to extract it looking for a `.txt` file inside, and fails with "No valid roms found in the archive lair.zip".

### Framefile format

A Daphne framefile is a text file with game-specific video frame timing data. It is **not an empty placeholder** — it ships with the Daphne ROM set.

The **first line** of the framefile is the path to the VLDP video directory, relative to the framefile's own location:

```
vldp\lair
<frame timing data...>
```

daphne.exe resolves this relative to the directory containing the framefile (`J:\Games\Daphne\`), so `vldp\lair` → `J:\Games\Daphne\vldp\lair\`.

### Chip ROM location and `homedir`

Daphne looks for chip ROMs at `<homedir>\roms\<game>.zip`. The `homedir` value is read per-game from `Daphne.ini` in the module folder:

```
D:\Arcade\RocketLauncher\Modules\Daphne\Daphne.ini
```

Every game section has a `homedir` key. On this cabinet it is set to `J:\Games\Daphne` for all games:

```ini
[lair]
homedir = J:\Games\Daphne
...

[esh]
homedir = J:\Games\Daphne
...
```

This causes daphne.exe to be called with `-homedir J:\Games\Daphne`, so chip ROMs are found at:

```
J:\Games\Daphne\roms\lair.zip
```

> **Default value is `.`** — if `homedir` is left as `.`, daphne resolves it against its working directory (`D:\Arcade\Emulators\Daphne\`) and looks for ROMs in `D:\Arcade\Emulators\Daphne\roms\`. This is the out-of-box default from the RL module ini and must be changed when ROMs live on a separate drive.

To update all game sections in bulk:

```powershell
(Get-Content "D:\Arcade\RocketLauncher\Modules\Daphne\Daphne.ini" -Raw) `
    -replace 'homedir = \.', 'homedir = J:\Games\Daphne' |
    Set-Content "D:\Arcade\RocketLauncher\Modules\Daphne\Daphne.ini"
```

Note that `homedir` only controls where daphne finds chip ROMs and other daphne-specific data (config, RAM saves). The VLDP video path is controlled separately by the framefile first line.

### Common path mistakes in the framefile

| Path in framefile | Resolves to | Problem |
|-------------------|-------------|---------|
| `/vldp/lair` | `D:\vldp\lair\` (absolute from drive root) | Leading `/` makes it absolute; daphne.exe runs from D:, so it looks on D: |
| `../vldp/lair` | `J:\Games\vldp\lair\` | `..` goes up from `J:\Games\Daphne\` to `J:\Games\` — correct only if vldp is at `J:\Games\vldp\` |
| `vldp\lair` | `J:\Games\Daphne\vldp\lair\` | **Correct** — relative to framefile location, stays inside the Daphne folder |

If you need to bulk-correct framefiles that have the wrong path prefix, use PowerShell from the cabinet:

```powershell
# Preview what would change (no -replace yet)
Select-String -Path "J:\Games\Daphne\*.txt" -Pattern "^/" | Select-Object Filename,Line

# Fix a specific prefix in all framefiles
Get-ChildItem "J:\Games\Daphne\*.txt" | ForEach-Object {
    (Get-Content $_.FullName -Raw) -replace '^/vldp/', 'vldp/' | Set-Content $_.FullName
}
```

Always preview before running the bulk replace, and always edit one file first to confirm the fix works before applying to all.

---

## Daphne Singe (WoW Action Max) — File Layout and Configuration

WoW Action Max uses a **custom build of Daphne Singe 1.0.10** housed in its own emulator folder, separate from the standard Daphne install. Three locations must all be correct for a game to launch; each missing piece produces a distinct failure.

> **Dual-copy requirement:** This Daphne Singe build has unusual asset loading behaviour. The engine assets (Emulator.singe, sprites, sounds, fonts) must be present in **both** the emulator directory on D: and the ROM directory on J:. Removing them from either location breaks the games. The exact loading path that reads from J: is not fully understood — empirically confirmed through testing.

### Emulator directory layout

```
D:\Arcade\Emulators\WoW Action Max\data\
├── daphne.exe                        ← custom Daphne Singe 1.0.10 build
├── sound\                            ← Daphne engine sound samples
│   └── saveme.wav  (+ others)        ← copy from D:\Arcade\Emulators\Daphne\sound\
└── singe\
    ├── ActionMax\                    ← ALL engine assets live here; loaded by Emulator.singe
    │   ├── Emulator.singe            ← master emulator script (loaded via dofile from CWD)
    │   ├── sprite_LightOn.png        ┐
    │   ├── sprite_LightOff.png       │ shared across all games
    │   ├── sprite_ActionMax.png      │
    │   ├── sprite_Crosshair.png      │
    │   ├── sprite_Bullet.png         ┘
    │   ├── sprite_<GameName>.png     ← one per game (e.g. sprite_PopsGhostly.png)
    │   ├── sound_ActionMax.wav       ┐
    │   ├── sound_ASteadyAimIsCritical.wav │
    │   ├── sound_GetReadyForAction.wav    │ shared across all games
    │   ├── sound_Gunshot.wav         │
    │   ├── sound_GoodHit.wav         │
    │   ├── sound_BadHit.wav          │
    │   ├── sound_GameOver.wav        ┘
    │   ├── font_BlueStone.ttf        ┐
    │   ├── font_chemrea.ttf          │ fonts used by Emulator.singe
    │   └── font_*.ttf                ┘ (5 total; names visible in daphne_log.txt on failure)
    └── Singe\
        └── Framework.singe           ← Singe engine framework; must exist or game silently fails
```

> **Why D: needs these files:** Every per-game `.singe` script calls `dofile("singe/ActionMax/Emulator.singe")`. The `dofile()` path is relative to **daphne.exe's working directory** (D:\Arcade\Emulators\WoW Action Max\data\), not to where the `.singe` script lives. `Emulator.singe` then loads all sprites, sounds, and fonts using the same `singe/ActionMax/<filename>` relative prefix — again from D:. If any of these are absent from D:, Daphne logs `SINGE: Unable to load sprite singe/ActionMax/...` errors.
>
> **Why J: also needs these files:** Empirically confirmed — removing sprites, sounds, fonts, or `Emulator.singe` from `J:\Games\WoW Action Max\` also breaks the games, even when D: copies are present. The exact loading path that reads from J: is not visible in `daphne_log.txt`. Treat the J: copies as a required duplicate; do not delete them.

### ROM directory layout (J: drive)

```
J:\Games\WoW Action Max\
├── <GameName>.singe             ← per-game script (config vars + dofile() call)
├── <GameName>.txt               ← per-game framefile (video frame timing data)
├── video_<GameName>.m2v         ┐
├── video_<GameName>.ogg         │ per-game video content
├── video_<GameName>.dat         ┘
├── Emulator.singe               ← duplicate of D: copy; must exist here too
├── sprite_*.png                 ← duplicate of D: copies (shared + per-game)
├── sound_*.wav                  ← duplicate of D: copies
└── font_*.ttf                   ← duplicate of D: copies
```

The engine assets on J: are flat (no `singe\ActionMax\` subfolder). Do not delete them — the games fail without copies in both locations.

### Global Emulators.ini entry

```ini
[Daphne Singe (WoW Action Max)]
Emu_Path=..\Emulators\WoW Action Max\data\daphne.exe
Rom_Extension=singe|bat|ogg|mpeg|mpg
Module=..\Daphne Singe\Daphne Singe.ahk
```

### How the module launches a game

The Daphne Singe module **ignores the actual file extension RL found** and always constructs its own command line:

```
daphne.exe singe vldp ... -framefile "<romPath>\<romName>.txt" -script "<romPath>\<romName>.singe"
```

This means if RL finds a `.bat` file in the ROM folder (e.g. `38AmbushAlley.bat`), it uses `38AmbushAlley` as the ROM name but the module still looks for `38AmbushAlley.txt` and `38AmbushAlley.singe` at the same path. The `.bat` content is never executed.

### Three failure modes in launch order

| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| 1 | RL error: "Could not find your emulator/application" | `Emu_Path` in `Global Emulators.ini` pointed into `Games\` instead of `Emulators\` | Set `Emu_Path=..\Emulators\WoW Action Max\data\daphne.exe` |
| 2 | Daphne error dialog: "Loading 'saveme.wav' failed / Sound initialization failed" | `sound\` folder missing from the emulator `data\` directory | Copy `D:\Arcade\Emulators\Daphne\sound\` → `D:\Arcade\Emulators\WoW Action Max\data\sound\` |
| 3 | RL fade-in completes, then RL errors "waiting for window DAPHNE" with no Daphne dialog | `Framework.singe` missing from `singe\Singe\`; Daphne exits silently | Place `Framework.singe` at `D:\Arcade\Emulators\WoW Action Max\data\singe\Singe\Framework.singe` |
| 4 | `SINGE: Unable to load sprite singe/ActionMax/...` or `Could not open singe/ActionMax/sound_...` | Sprites, sounds, or fonts missing from `D:\...\singe\ActionMax\` | Copy from J: to D: with xcopy (see dual-copy note above) |
| 5 | Game launches but crashes / fails mid-load with no clear error | Sprites, sounds, fonts, or `Emulator.singe` missing from `J:\Games\WoW Action Max\` | Restore the flat copies on J: — both locations are required |

Failure mode 3 produces **no Daphne error dialog** — Daphne simply exits. Temporarily disable RL Fade to see bare Daphne output when diagnosing it.

Failure modes 4 and 5 are mirror images of each other due to the dual-copy requirement. If games fail silently or partially, check that the engine assets exist in both locations.

### SingePathUpdate — not useful for WoW Action Max

The Daphne Singe RL module has a `SingePathUpdate` feature (`Daphne Singe.ini`) that rewrites hardcoded paths inside `.singe` files to match the current `romPath`. This does **not** help WoW Action Max.

The per-game `.singe` scripts contain no absolute paths — only `dofile("singe/ActionMax/Emulator.singe")`, which is a CWD-relative path that is correct by design. `SingePathUpdate` would rewrite it to an absolute J: path, which would break the dofile() call and is not what you want.

`Emulator.singe` similarly uses `singe/ActionMax/<asset>` relative paths throughout. These must stay as-is, resolving from daphne.exe's working directory on D:.

**Leave `SingePathUpdate=false` for WoW Action Max.**

---

## Daphne Singe (American Laser Games) — File Layout and Path Rewrite

American Laser Games (ALG) titles — *Mad Dog McCree*, *Space Pirates*, *Crime Patrol*, and others — use a custom Daphne Singe 1.0.10 build with its own emulator folder. The original `.singe` scripts have hardcoded absolute `D:` paths referencing the old game location; these must be rewritten once when ROMs live on a different drive.

> **Dual-copy requirement — .singe files only:** After the path rewrite (below), `.singe` script files must be present in **both** the ROM directory on J: and the emulator's `singe\[gamename]\` directory on D:. Assets (sprites, sounds, fonts, `.cfg` files) only need to be on J:. This is distinct from WoW Action Max, which requires *all* assets duplicated for an empirically-confirmed but poorly-understood reason, and whose scripts use CWD-relative paths that must not be rewritten.

### File layout

```
D:\Arcade\Emulators\American Laser Games\data\     ← daphne.exe working directory (CWD)
├── daphne.exe                                     ← custom Daphne Singe 1.0.10 build
├── sound\                                         ← Daphne engine sounds
└── singe\
    └── [gamename]\                                ← .singe copies (required — see below)
        ├── service.singe
        └── *.singe  (all scripts for this game)

J:\Games\American Laser Games\[gamename]\          ← ROM directory (one subfolder per game)
├── [gamename].txt                                 ← framefile (video frame timing — RL "ROM")
├── [gamename]_cdrom.singe                         ← main entry-point script (RL -script target)
├── service.singe                                  ← reads/writes game settings + high scores
├── *.singe                                        ← hitbox, level, and config scripts
├── [gamename].cfg                                 ← settings + high scores; must exist before first run
├── *.png  *.wav  *.ttf                            ← sprites, sounds, fonts (J: only — no D: copy needed)
└── cdrom\                                         ← video data
```

### How RL launches a game

The `Daphne Singe.ahk` module constructs:

```
daphne.exe singe vldp ... -framefile "J:\Games\American Laser Games\[gamename]\[gamename].txt" -script "J:\Games\American Laser Games\[gamename]\[gamename]_cdrom.singe"
```

Daphne runs with its CWD set to `D:\Arcade\Emulators\American Laser Games\data\`. Any `dofile()` path that is **relative** (e.g. `dofile("singe/maddog/service.singe")`) resolves against that D: CWD — not against the J: ROM directory.

### Why paths fail after moving ROMs to J:

The original ALG `.singe` scripts have hardcoded absolute paths to the old game location on D:, for example:

```lua
dofile("D:/Arcade/Games/American Laser Games/data/singe/maddog/service.singe")
spriteLoad("D:/Arcade/Games/American Laser Games/data/singe/maddog/bullet.png")
io.input("D:/Arcade/Games/American Laser Games/data/singe/maddog/maddog.cfg")
```

With ROMs on J: and the old D: game folder absent, every `spriteLoad`, `soundLoad`, `fontLoad`, and `dofile()` call fails. The `.cfg` file error crashes the game on the first overlay update frame even after the video starts playing.

### SingePathUpdate and ForcePathUpdate

These two keys in `Daphne Singe.ini` (`D:\Arcade\RocketLauncher\Modules\Daphne Singe\Daphne Singe.ini`) control a one-time path rewrite:

| Key | Behaviour |
|-----|-----------|
| `SingePathUpdate=true` | Before launching Daphne, rewrite every matching line in every `*.singe` file in `romPath` (the J: game directory). Calls `exitapp` after — **Daphne never launches on this run**. |
| `ForcePathUpdate=true` | Bypass the skip-if-already-updated check. Without this, any `.singe` file that already contains the `romPath` string anywhere is skipped entirely, which can leave other files with stale D: paths. |

The Lua functions the rewrite recognises: `dofile(`, `spriteLoad`, `io.input`, `io.output`, `fontLoad`, `soundLoad`

Each matching line has its path directory replaced with the current `romPath` (the J: game directory); the filename at the end of the path is preserved.

> **Expected behaviour after running:** No `daphne_log` is produced. RocketLauncher exits after the rewrite. This is correct — the path-rewrite run is a setup step, not a game launch. Set both keys back to `false` before the next run, which will actually launch the game.

### Why .singe files need copies on both D: and J:

`SingePathUpdate` updates the J: ROM directory copies. The `-script` argument points to a J: file, so the main script loads from J: with the updated paths. However, scripts frequently call `dofile()` with **relative** paths:

```lua
dofile("singe/maddog/service.singe")
```

Because Daphne's CWD is `D:\Arcade\Emulators\American Laser Games\data\`, this resolves to:

```
D:\Arcade\Emulators\American Laser Games\data\singe\maddog\service.singe
```

Daphne loads the D: copy of `service.singe` — which still has the original D: paths for `io.input`, `io.output`, etc. The updated J: copy is bypassed entirely.

**Fix:** after SingePathUpdate has rewritten the J: copies, copy them to D::

```bat
xcopy /Y "J:\Games\American Laser Games\[gamename]\*.singe" "D:\Arcade\Emulators\American Laser Games\data\singe\[gamename]\"
```

The destination directory must exist first. Only `.singe` files need copying — sprites, sounds, fonts, and `.cfg` files are referenced by absolute J: paths in the updated scripts and do not need D: copies.

### .cfg files — game settings and high scores

Each game has a `.cfg` file (e.g. `maddog.cfg`) storing difficulty, coin settings, and high scores. `service.singe` reads it at game start via `io.input()` and writes it on exit via `io.output()`. After SingePathUpdate, these paths point to `J:\Games\American Laser Games\[gamename]\[gamename].cfg`.

**The `.cfg` file must exist at the J: path before the game can run.** If missing, `io.input()` throws an error and the game crashes on the first overlay update frame. Either copy it from the old D: location if one exists, or create it with default values — see `service.singe` for the expected format (plain-text `key = value` lines followed by high score name/score entries).

### One-time setup procedure

This is done once per game. After completion, both keys stay `false` permanently.

1. **Set both flags in `D:\Arcade\RocketLauncher\Modules\Daphne Singe\Daphne Singe.ini`:**
   ```ini
   SingePathUpdate=true
   ForcePathUpdate=true
   ```

2. **Launch each ALG game from HyperSpin once.** The `.singe` files in the J: ROM directory for that game are rewritten, then RL exits. No game window appears; no `daphne_log` is produced. This is expected and correct.

   > `SingePathUpdate` is **per-game** — it only processes `.singe` files for the game currently being launched. Repeat this step for every ALG title.

3. **Copy updated .singe files to D:.** For each game:
   ```bat
   xcopy /Y "J:\Games\American Laser Games\[gamename]\*.singe" "D:\Arcade\Emulators\American Laser Games\data\singe\[gamename]\"
   ```

4. **Restore both flags:**
   ```ini
   SingePathUpdate=false
   ForcePathUpdate=false
   ```

5. **Launch each game normally to play.**

### Comparison with WoW Action Max

| | American Laser Games | WoW Action Max |
|---|---|---|
| Original script paths | Hardcoded absolute D: paths | CWD-relative (`singe/ActionMax/`) |
| SingePathUpdate | **Required** (one-time setup per game) | **Do not use** — would break CWD-relative paths |
| What needs D: copies | `.singe` files only | All assets (sprites, sounds, fonts) |
| What needs J: copies | Everything (scripts + assets + cfg) | Everything |
| Reason D: copy needed | `dofile()` relative paths resolve from D: CWD | Asset loading via unknown path (empirically confirmed) |

---

## Dolphin (Nintendo Gamecube / Wii) — Version and ROM Format Notes

### Emulator version on this cabinet

| Slot | Version | Path | Supports RVZ |
|------|---------|------|--------------|
| Active | **Dolphin 5.0-16101** | `D:\Arcade\Emulators\Dolphin Ishiiruka\Dolphin.exe` | Yes |
| Original | Dolphin Ishiiruka (2017) | replaced by above | No |

The original Dolphin Ishiiruka build (dated 2017) was replaced with Dolphin 5.0-16101.
This is the **last Dolphin dev build that runs on Windows 7** — Windows 7 support was
removed from Dolphin in July 2023. RVZ support was added in Dolphin 5.0-12188 (December 2020),
so any build in the range 5.0-12188 through ~5.0-17000 supports both RVZ and Windows 7.

The emulator folder name (`Dolphin Ishiiruka`) was kept intentionally so that
`Global Emulators.ini` needs no changes — it still points to the same path.
The `User\` subfolder (portable mode) carries over all GCPad/Wiimote profiles and
Dolphin.ini settings automatically.

### Dolphin portable mode

Dolphin stores its settings under `User\Config\Dolphin.ini` relative to the emulator
folder when a `portable.txt` file is present. This cabinet uses portable mode:

```
D:\Arcade\Emulators\Dolphin Ishiiruka\
├── Dolphin.exe          ← the emulator (currently 5.0-16101)
├── portable.txt         ← triggers portable mode
└── User\
    └── Config\
        ├── Dolphin.ini  ← main settings (Fullscreen, HideCursor, etc.)
        ├── GCPadNew.ini ← GameCube controller mappings
        └── WiimoteNew.ini ← Wiimote mappings
```

RocketLauncher's Dolphin module reads `Dolphin.ini` from this path and updates
`Fullscreen`, `RenderToMain`, `HideCursor`, `ConfirmStop`, and `UsePanicHandlers`
before each launch.

### ROM formats

| Extension | Format | Notes |
|-----------|--------|-------|
| `.iso` | Raw disc image | Universal; largest file size |
| `.gcm` | GameCube disc image | Identical to ISO, different extension |
| `.gcz` | Dolphin GCZ compression | Smaller than ISO; supported since early Dolphin |
| `.ciso` | Compact ISO | Wii-only compression format |
| `.wbfs` | Wii Backup FS | Wii-only; can be a full partition image |
| `.rvz` | RVZ compression | Requires Dolphin **5.0-12188+**; NOT supported by Dolphin Ishiiruka (2017) or older |

**RVZ is the modern compressed format** produced by tools like Dolphin's own conversion
and Dolphin Tool. It's smaller than GCZ and lossless. If ROMs come as `.rvz` inside a
`.zip` archive and RocketLauncher reports *"No valid roms found in the archive"*, the
cause is a mismatch between the inner extension and `Rom_Extension=` in Global Emulators.ini.

### Upgrading Dolphin or switching versions

To replace the Dolphin executable while keeping all settings and controller profiles:

1. Download the target Dolphin build (`Dolphin-x64.7z` from the Dolphin dev builds archive)
2. Copy the new `Dolphin.exe` (and supporting DLLs if present) into
   `D:\Arcade\Emulators\Dolphin Ishiiruka\` — overwrite the old exe only
3. The `User\` folder and `portable.txt` are untouched; settings carry over automatically
4. No changes to `Global Emulators.ini` are needed
5. **If upgrading from a 2017-era Dolphin Ishiiruka (wx-based) to Dolphin 5.0-12188+
   (Qt-based), the RocketLauncher module also needs updating** — see *RL module
   compatibility when upgrading build generation* below.

### RL module compatibility when upgrading build generation

Old Dolphin builds used the **wxWidgets** UI framework (window class `wxWindowNR`).
Dolphin 5.0-12188+ switched to **Qt** (window class `Qt5150QWindowIcon`).
RocketLauncher's `Dolphin.ahk` module detects game windows by class name, so upgrading
from a wx build to a Qt build without updating the module causes two failures:

| Symptom | Cause |
|---------|-------|
| RL fade-in completes, then error: *"There was an error waiting for the window FPS ahk\_class wxWindowNR"* | Module looks for `wxWindowNR`; Qt Dolphin registers as `Qt5150QWindowIcon` |
| Dolphin opens to the game browser instead of launching the selected game | Old Windows-style flags (`/b /e`) are not parsed by Qt-based Dolphin; use POSIX-style (`-b -e`) |

**Three edits are needed in `D:\Arcade\RocketLauncher\Modules\Dolphin\Dolphin.ahk`:**

1. **All window class references** — replace every occurrence of `wxWindowNR` with
   `Qt5150QWindowIcon`. There are 7 occurrences (primary window × 3, game window × 3,
   NetPlay windows × 2 across several conditional blocks).

2. **Launch flags** — find the line that runs the emulator:
   ```ahk
   primaryExe.Run(" /b /e """ . romPath . "\" . romName . romExtension . """")
   ```
   Change `/b /e` to `-b -e`:
   ```ahk
   primaryExe.Run(" -b -e """ . romPath . "\" . romName . romExtension . """")
   ```

3. **Render_To_Main module setting** — the module's game-window detection relies on a
   separate render window titled `FPS`. In newer Dolphin builds this window may not
   appear as a separate top-level window. If the game still fails to launch after the
   above two fixes, set `Render_To_Main=true` in
   `D:\Arcade\RocketLauncher\Modules\Dolphin\Dolphin.ini`:
   ```ini
   [Settings]
   Render_To_Main=true
   ```
   The module will then write `RenderToMain=True` into Dolphin's own `Dolphin.ini`
   and wait for the main Dolphin window instead of the separate FPS render window.

> **CRC warning is harmless.** Editing `Dolphin.ahk` causes RL to log
> *"CRC does not match official module"* — this is a WARNING, not an error, and
> does not prevent the module from running.

### RVZ — per-system Rom_Extension

When ROMs are stored as bare `.rvz` files (not inside a zip), `rvz` must appear in the
`Rom_Extension=` list in the **per-system** settings file as well as `Global Emulators.ini`:

```ini
; D:\Arcade\RocketLauncher\Settings\Nintendo Gamecube\Nintendo Gamecube.ini
[ROMS]
Rom_Extension=lha|lzh|gzip|tar|gcz|7z|zip|ciso|iso|elf|dol|gcm|wad|rar|wbfs|rvz
```

If ROMs are stored as `.rvz` **inside** a `.zip` archive, add `rvz` to `Global Emulators.ini`
`[Dolphin Ishiiruka]` → `Rom_Extension=` instead (or in addition). Unzipping the `.rvz` files
directly to the ROM folder is the simpler layout — `.rvz` is already compressed and gains
nothing from being re-zipped.

To add a **second Dolphin instance** (e.g. keep Ishiiruka for one system, new build for another):

1. Install the new build to a different folder, e.g. `D:\Arcade\Emulators\Dolphin\`
2. Copy the `User\` folder from `Dolphin Ishiiruka\` to carry over settings and profiles
3. Add a `[Dolphin]` section to `Global Emulators.ini`:
   ```ini
   [Dolphin]
   Emu_Path=..\Emulators\Dolphin\Dolphin.exe
   Rom_Extension=iso|gcm|gcz|wbfs|ciso|rvz
   Module=Dolphin.ahk
   ```
4. Create (or update) `Settings\Nintendo Gamecube\Emulators.ini`:
   ```ini
   [ROMS]
   Default_Emulator=Dolphin
   Rom_Path=J:\Games\Nintendo Gamecube
   ```

### `check-archive-ext` — catching extension mismatches before launch

Run `spindoctor check-archive-ext --system "Nintendo Gamecube"` (or the **Check archive
extensions** button in the Diagnostics tab) to scan every `.zip`/`.7z`/`.rar` in the ROM
directory and report files whose inner extensions are not listed in `Rom_Extension`. This
catches `.rvz`, `.nkit.iso`, or any other non-standard format before the user tries to
launch a game and gets the cryptic *"No valid roms found in the archive"* error.

### Controller input — DS4Windows and XInput

This cabinet uses a PS4 DualShock 4 controller. Windows does not natively expose PS4
controllers as XInput devices; DS4Windows provides that translation layer.

#### How DS4Windows works

DS4Windows runs as a background process and presents the PS4 controller to Windows as a
virtual Xbox 360 (XInput) controller. Without DS4Windows running, Windows sees two
representations of the controller:

| Device | Protocol | Visible when |
|--------|----------|--------------|
| `DInput/0/Wireless Controller` | DirectInput (raw HID) | Always |
| `XInput/0/Gamepad` | XInput (virtual Xbox 360) | Only while DS4Windows is running |

Dolphin's GCPad must be configured for **`XInput/0/Gamepad`** — the DS4Windows virtual
controller. If configured for `DInput/0/Wireless Controller` (the raw HID device), inputs
will not register correctly.

#### DS4Windows must run independently of HyperSpin

DS4Windows is started alongside HyperSpin and exits when HyperSpin exits. If DS4Windows
closes during an active Dolphin session — or its process lifetime is tied to HyperSpin —
the virtual `XInput/0/Gamepad` device disappears and Dolphin shows:

```
[disconnected] DInput/0/Wireless Controller
```

The controller does not recover until DS4Windows is restarted or the machine is rebooted.

**Fix:** Configure DS4Windows to start at Windows login (Startup folder or Task Scheduler),
independent of HyperSpin's process lifetime.

#### LED colour change is normal

When DS4Windows activates, the PS4 controller lightbar switches from its default blue to
the colour in the active DS4Windows profile. This is expected and indicates DS4Windows has
taken ownership of the device. It is not a sign of a problem.

#### Diagnosis checklist

If the GameCube controller stops responding after launching through HyperSpin:

1. Open Dolphin's controller settings (`Options → Controller Settings`). If Port 1 shows
   `[disconnected] DInput/0/Wireless Controller`, DS4Windows is not running.
2. Press `Win+B` to focus the system tray (works even when HyperSpin hides the taskbar),
   then open DS4Windows from the tray icon and confirm the controller is listed.
3. Confirm Dolphin's GCPad Port 1 device is set to `XInput/0/Gamepad`.

---

## Phoenix (Atari Jaguar) — Emulator Configuration and ROM Path Fix

Phoenix v2.8.JAG emulates the Atari Jaguar (and Panasonic 3DO). Unlike most emulators, Phoenix does not accept a ROM path on the command line — RocketLauncher launches it by **editing `phoenix.config.xml` before each launch**.

### File layout

| File | Path |
|------|------|
| Emulator | `D:\Arcade\Emulators\Phoenix\PhoenixEmuProject.exe` |
| Config | `D:\Arcade\Emulators\Phoenix\phoenix.config.xml` |
| BIOS | `D:\Arcade\Emulators\Phoenix\Jaguar\BIOS\[BIOS] Atari Jaguar (World).j64` |
| ROMs | `J:\Games\Atari Jaguar\` (extension `.j64`) |
| RL module | `D:\Arcade\RocketLauncher\Modules\Phoenix\Phoenix.ahk` |

### How the RL module loads a game

Phoenix stores its media library in `phoenix.config.xml` as `<Dump>` entries under a `<CARTRIDGE>` node. The `attach` attribute on `<CARTRIDGE>` tells Phoenix which game to auto-select on startup:

```xml
<Platform-Jaguar>
    <CARTRIDGE expanded="true" attach="J:/Games/Atari Jaguar/Tempest 2000 (World).j64"
               last-path="J:/Games/Atari Jaguar">
        <Dump path="J:/Games/Atari Jaguar/Air Cars (World).j64" ... />
        <Dump path="J:/Games/Atari Jaguar/Tempest 2000 (World).j64" ... />
        ...
    </CARTRIDGE>
</Platform-Jaguar>
```

Phoenix **only auto-selects a game if `attach` matches a `<Dump>` entry path exactly.** If the paths differ, Phoenix opens with no cartridge selected and any Power On attempt fails with *"You must select CARTRIDGE."*

Before launch the module:
1. Reads `phoenix.config.xml` into memory
2. Rewrites every `<Dump path="…">` that contains `D:/Arcade/Games/Atari Jaguar/` → `J:/Games/Atari Jaguar/`
3. Sets `attach` to the J: ROM path of the selected game
4. Writes the file back and launches Phoenix
5. Sends `{Alt}{Right}{Enter}{Enter}` to navigate Control → Power On

### Why Dump paths needed rewriting

The Phoenix library was originally built from `D:\Arcade\Games\Atari Jaguar\` (games added via *File → Add CARTRIDGE file to the collection*). The ROMs were later moved to `J:\Games\Atari Jaguar\`. Phoenix's library retained the D: paths, so any `attach` value set to a J: path would not match any `<Dump>` entry — causing the *"You must select CARTRIDGE"* error on every launch.

The RL module rewrites the paths on every launch. After the first successful launch Phoenix saves the J: paths back to `phoenix.config.xml` itself, so subsequent launches the `StringReplace` finds nothing to replace and is a no-op.

### BIOS

The Jaguar BIOS is registered in the same `phoenix.config.xml` under a `<BIOS>` node and lives at:

```
D:\Arcade\Emulators\Phoenix\Jaguar\BIOS\[BIOS] Atari Jaguar (World).j64
```

This path is on D: (emulator folder, not game drive) and is not affected by the Dump path rewrite.

### Reference copy of the RL module

A reference copy of the customised `Phoenix.ahk` is kept in
`spindoctor/assets/archive/Phoenix.ahk`. The canonical installed file is at
`D:\Arcade\RocketLauncher\Modules\Phoenix\Phoenix.ahk` on the cabinet.

---

## PCLauncher Architecture — Two-File System

PCLauncher uses **two separate file types** for synthetic wheels. Many people confuse them:

### 1. ROM Placeholder Files — `Modules\PCLauncher\<System>\<game>.ini`

For **synthetic wheels** (Favorites, Recently Played, Most Played, Recompiled): used only by RocketLauncher to enumerate which games exist in the wheel. PCLauncher.ahk reads the system-level INI instead (see section 2). The placeholder content is irrelevant.

For **PC game wheels** (PC Games, Windows, etc.): the per-game INI IS the launch config. PCLauncher.ahk reads it first (before the system-level INI) and uses `[<game_name>]` / `Application=`. See *PCLauncher Architecture — PC Game Wheels* below.

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

## PCLauncher Architecture — PC Game Wheels (non-synthetic)

PC game wheels (system name "PC Games", "Windows", etc.) are **different from synthetic wheels**. PCLauncher.ahk uses a three-level INI lookup hierarchy for each game:

```
1. Per-game INI:    Modules\PCLauncher\<SystemName>\<GameName>.ini   ← checked FIRST
2. System INI:      Modules\PCLauncher\<SystemName>.ini               ← fallback
3. Global INI:      Modules\PCLauncher\PCLauncher.ini                 ← last resort
```

The per-game INI for a PC game **is not a placeholder** — it contains the actual launch config. PCLauncher.ahk reads `Application=` from the `[<GameName>]` section:

```ini
[Master Key]
Application=J:\Games\PC Games\Master Key\MasterKey.exe
WorkingFolder=J:\Games\PC Games\Master Key
```

SpinDoctor's `pc-rename` command writes per-game INIs in this format. Because per-game INIs are checked before the system-level INI, SpinDoctor's entries shadow any existing `<SystemName>.ini`.

### Stale System-Level INIs (RLUI-created)

Cabinet owners who originally configured PC games in RocketLauncherUI get a single system-level `PC GAMES.ini` with all games in `[game_name]` sections. These often contain **relative paths** such as:

```ini
[Master Key]
Application=..\Games\PC Games\Master Key\Master Key.exe
```

A relative path like `..\Games\...` resolves from the RL base directory (`D:\Arcade\RocketLauncher\`) to `D:\Arcade\Games\...`. After a ROM drive migration (old `D:\Arcade\Games\` → new `J:\Games\`), this path points to the wrong drive and the game fails to launch:

> `Cannot find this Application: D:\Arcade\Games\PC Games\Master Key\Master Key.exe`

**Fix:** Run `spindoctor pc-rename "PC Games" --apply`. SpinDoctor scans the current `roms_dir` for `.exe` and `.lnk` files, writes per-game INIs with absolute current paths, and PCLauncher finds the per-game INIs before the stale system-level one:

```ini
; Written to Modules\PCLauncher\PC Games\Master Key.ini
[Master Key]
Application=J:\Games\PC Games\Master Key\MasterKey.exe
WorkingFolder=J:\Games\PC Games\Master Key
```

The old `PC GAMES.ini` is left on disk but no longer consulted for games that have a per-game INI. The system-level filename casing (`PC GAMES.ini` vs `PC Games.ini`) is irrelevant on Windows (case-insensitive filesystem).

### Section-Name Mismatch — game titles with colons or other Windows-invalid characters

Windows filenames cannot contain `: * ? " < > | \ /`. When a game's HyperSpin dbName contains a colon (e.g. `Submachine: Legacy`), the INI **filename** must strip it (`Submachine Legacy.ini`) — but the INI **section header** must use the exact dbName that PCLauncher.ahk receives from RocketLauncher:

```ini
; Filename: Modules\PCLauncher\PC Games\Submachine Legacy.ini
; (colon stripped — Windows can't store colons in filenames)

[Submachine: Legacy]
; ↑ section header MUST match the HyperSpin dbName exactly, colon included
Application=J:\Games\PC GAMES\Submachine Legacy\Submachine Legacy.exe
WorkingFolder=J:\Games\PC GAMES\Submachine Legacy
```

If the section header also has the colon stripped (`[Submachine Legacy]`) PCLauncher.ahk cannot find it and falls through to the system-level `PC GAMES.ini`. If that file has a stale RLUI entry with an old drive letter the game fails to launch with the familiar "Cannot find this Application" error — even though a correctly-pathed per-game INI exists on disk.

**SpinDoctor's handling (v2.6.2+):** `pc-rename` and `add-pc-system` consult the HyperSpin XML to find the canonical dbName for each folder-derived title. When the folder name and dbName differ only in stripped characters (e.g. folder `Submachine Legacy` ↔ dbName `Submachine: Legacy`), the per-game INI is written with the safe filesystem stem as the filename and the original dbName as the section header. The `--verbose` stale-detection path uses the same mapping, so an INI whose section header doesn't match the dbName is correctly reported as **stale** rather than "current".

**Symptom to watch for:** If `pc-rename --verbose` shows a game as "current" but it still launches from the wrong path, the per-game INI may have been written with a mismatched section header by an older version of SpinDoctor (or by hand). Run `pc-rename "PC Games" --apply --overwrite-pclauncher` to rewrite all per-game INIs with correct section headers.

**`add-pc-system --verbose`** provides the same per-game visibility during an initial bootstrap or refresh run. After the title-review step it prints each game labelled `new` (not yet in the HyperSpin XML) or `existing` (already present), followed by the resolved `Application=` path. Titles that are in the XML but absent from the current ROM scan are flagged as `will be removed` — `add-pc-system --apply` automatically removes them from the database and deletes the corresponding PCLauncher INI. In the PCLauncher INI step each INI is listed with its full path and whether it would be written, skipped, or deleted (stale). Use `add-pc-system --verbose` rather than `pc-rename --verbose` when you want the full bootstrap output (system overrides, `add-system` invocation, DB write, and media fetch) alongside the per-game detail.

### Non-exe ROM files (GOG `webcache.zip`, multi-part archives, etc.)

RocketLauncher finds a "rom" for each PC game by scanning the game folder for files whose extension matches the system's `romExtensions` setting (typically `zip|rar|7z|…`). For GOG installs this often surfaces `webcache.zip` (a cache file of no use to PCLauncher) or a redistributable archive rather than the real game executable.

**SpinDoctor's handling (v2.6.3+):** When writing or rewriting a per-game PCLauncher INI, `pc-rename` and `add-pc-system` check whether the proposed path ends in `.exe`. If not, they call `_pick_best_exe` on the game folder: scan for `.exe` files, filter out known non-game executables (`unins*`, `setup*`, `vcredist*`, `crashpad*`, `chromedriver*`, `nwjc*`, etc.), then prefer the file whose name most closely matches the game title (largest file wins ties). The resolved path is used for `Application=` regardless of what the rom scanner found. Stale detection uses the same resolved path, so a game whose INI was already corrected with `pc-fix-exe` shows as `ok`, not `stale`.

The exclusion list covers NW.js / Electron runtimes (`chromedriver.exe`, `nwjc.exe`, `nacl_irt_*.nexe`). This is required for RPGMaker and NW.js-packaged games where the real launcher is `Game.exe` but the runtime bundles `chromedriver.exe` in the same folder (which sorts before `Game.exe` alphabetically and would otherwise be selected).

Example — ElecHead (GOG install):

```
J:\Games\PC GAMES\ElecHead\
  ElecHead.exe      ← 5 MB, name matches title → selected
  unins000.exe      ← 1.3 MB, excluded (uninstaller prefix)
  webcache.zip      ← 153 KB, not an exe → triggers resolution
  ...
```

Example — Look Outside (NW.js / RPGMaker install):

```
J:\Games\PC GAMES\Look Outside\
  Game.exe          ← real game launcher → selected
  chromedriver.exe  ← NW.js runtime, excluded (chromedriver prefix)
  ...
```

SpinDoctor writes `Application=J:\Games\PC GAMES\ElecHead\ElecHead.exe`. The `webcache.zip` is ignored entirely.

Run `pc-rename "PC Games" --no-interactive --verbose --overwrite-pclauncher --apply` after upgrading to v2.6.3 to bulk-fix any games that were written with `webcache.zip` (or similar) as `Application=` by an older version.

### Per-game vs system-level: how they differ from synthetic wheels

| | Synthetic wheel (Favorites) | PC game wheel |
|---|---|---|
| Per-game INI content | Placeholder only; PCLauncher.ahk ignores it | Actual launch config; PCLauncher reads it |
| System-level INI content | All game entries (SpinDoctor writes this) | May be stale/missing; per-game INIs take priority |
| SpinDoctor writes | System-level `.ini` via `fav rebuild` | Per-game `.ini` per game via `pc-rename` |
| `Application=` key points to | `RocketLauncherGame.exe` (recursive RL) | The game's actual `.exe` or `.lnk` |

### `read_pclauncher_ini_application_path` — stale detection

SpinDoctor's dry-run mode compares each per-game INI's `Application=` value against the resolved executable path (not the raw rom path — see exe resolution above). The lookup uses the HyperSpin dbName (colon included) as the expected section name — not the INI filename stem — so a file written with a colon-stripped section header is correctly detected as stale. Old `[Settings]` / `ApplicationPath=` INIs return empty and are also treated as stale, triggering a re-write on the next `--apply` run.

---

## Recursive RocketLauncher Launch — Why and How

### Why synthetic wheels need a second RL

A normal wheel (MAME, Nintendo 64, etc.) maps every entry to a single system. HyperSpin
exits, one `RocketLauncher.exe` runs, the emulator loads. One RL instance, start to finish.

A **synthetic wheel** (Favorites, Recently Played, Most Played, Recompiled) is a cross-system list.
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

SpinDoctor writes `FadeTitle=` and `FadeTitleTimeout=300` into the system-level PCLauncher
INI for every synthetic wheel entry. The default value is the emulator's registered name
(e.g. `FadeTitle=MAME` for a MAME game, `FadeTitle=Supermodel` for a Model 3 game). AHK's
`WinWait` uses case-insensitive partial matching, so "MAME" matches "MAME [1942 (World)]",
"Supermodel" matches "Supermodel 3.1 UI", and so on — no configuration needed for the
vast majority of emulators.

`FadeTitleTimeout=300` prevents an infinite hang if the emulator crashes before showing a
window: PCLauncher errors after 5 minutes instead of waiting forever. PCLauncher proceeds
immediately when the window appears, so fast-loading games are not delayed.

SpinDoctor also ships a built-in correction table for emulators whose window titles diverge
from their registered name. Notable entries: `"Dolphin Ishiiruka"` → `"Dolphin"` (Qt-based
Dolphin 5.0 builds dropped "Ishiiruka" from the title; without this correction, launching
any Dolphin game from a synthetic wheel hits the timeout while the game plays in the
background). User corrections via `emulator-title set` take precedence over the built-in
table.

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
corrections take precedence over the built-in correction table described above.

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
these system names:

```python
SYNTHETIC_SYSTEM_NAMES = frozenset({"Favorites", "Recently Played", "Most Played"})
```

This ensures that playing "Strider" from Favorites never adds it to Recently Played or
Most Played via the synthetic wheel path — only real arcade wheel plays count.

> **Note:** `Recompiled` is intentionally absent from `SYNTHETIC_SYSTEM_NAMES`. It is a
> curated hand-picked wheel (not auto-generated from stats), so plays from it *do* count
> toward Recently Played and Most Played. Only the three auto-generated wheels are excluded.

### Stale stats entries from failed launches (cascading failure)

**RL#2 writes stats on every exit, including failed launches.** If the PCLauncher INI
has the wrong `-r` value for a game (e.g. `Kirby's Adventure` instead of
`Kirby's Adventure (USA)`), RL#2 will fail to find the ROM — but before exiting it still
writes a stats record to the source system's `Statistics.ini` under the wrong name. The
next `recent rebuild` or `stats build-wheel` reads that stale entry and writes the same
wrong `-r` value back into the PCLauncher INI, making the problem permanent.

**SpinDoctor breaks this cycle** by validating every stats entry against the source
system's HyperSpin database XML before writing any launcher. If `rom_name` from stats
does not appear as a `name` attribute in the database, the entry is logged and skipped.
Entries from systems whose database cannot be read are preserved (safe fallback).

This validation happens inside `_build_synthetic_wheel` (shared by Recently Played,
Most Played, and Favorites), before `_resolve_target_names` or any file write.

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

### Module INI requirement

`install-tools --add-to-system Toolkit` also writes (or updates) the **PCLauncher module INI** at
`Modules\PCLauncher\Toolkit.ini`. Without this file, PCLauncher.ahk has no `Application=` value
to read and fails immediately with:

> *You have not set up \<tool\> in RocketLauncherUI yet, so PCLauncher does not know what exe,
> FadeTitle, and/or SteamID to watch for.*

The generated sections look like:

```ini
[Refresh Recently Played]
Application=D:\Arcade\Utilities\Toolkit\Refresh Recently Played.bat
WorkingFolder=D:\Arcade\Utilities\Toolkit
```

PCLauncher.ahk reads this, launches the `.bat`, and waits for the `cmd.exe` process to exit
via PID detection (no `FadeTitle` or `AppWaitExe` needed for batch files). Existing
non-SpinDoctor sections in `Toolkit.ini` are preserved when the command is re-run.

---

## Media Layout

HyperSpin looks for media under `Media\<SystemName>\<SubDir>\<GameName>.<ext>`:

| SubDir              | Contents                                   |
|---------------------|--------------------------------------------|
| `Images\Wheel\`     | Wheel art (`.png`)                         |
| `Images\Backgrounds\`| Background images                         |
| `Images\Artwork1-3\`| Additional artwork                         |
| `Images\Titles\`    | Title-screen captures — displayed in theme side-panels when a game is highlighted. |
| `Images\Letters\`   | Alphabetic scroll-bar letter art           |
| `Themes\`           | Theme files — stored as **`.zip` files** (e.g. `Themes\1942.zip`), not extracted directories. `Default.zip` is the console-wide fallback theme HyperSpin uses for games without a per-game zip. |
| `Sound\`            | Navigation sound clips (`Wheel Click.mp3`, `select.mp3`, `back.mp3`, `letter.mp3`). `Wheel Click.mp3` plays on every left/right cursor move. |
| `Video\`            | Video previews (`.mp4`, `.wmv`, `.mpeg`, `.mpg`, `.flv`, `.avi`, `.mkv`, …) |
| `Video\Trailers\`   | Full trailers                              |

SpinDoctor's media mirror copies all of the above from the source system to the synthetic
wheel. Both file-form themes (`.zip`) and directory-form themes are handled.

**MAME subsystem video redirect** — MAME subsystem wheels ("4-Player Games", "Driving Games", etc.) have no `Media\<System>\Video\` folder of their own. HyperSpin reads the video redirect from `D:\Arcade\Settings\<System>.ini` under `[video defaults]` → `path=`. SpinDoctor follows this same redirect during `fav rebuild` / `recent rebuild` so subsystem games get their videos copied to the synthetic wheel. See *HyperSpin Settings INIs and the Video Redirect* above.

**`Default.zip` fallback** — When a game has no per-game theme zip in the source system,
SpinDoctor copies `Default.zip` from that system's `Themes\` folder as `<GameName>.zip`
in the synthetic wheel. This preserves the console-themed background and video layout
(e.g. the NES theme for Kirby's Adventure) that HyperSpin would show in the native wheel.

**`Wheel Click.mp3` auto-install** — SpinDoctor bundles a navigation click sound and installs
it as `Media\<SystemName>\Sound\Wheel Click.mp3` for each synthetic wheel during `rebuild --apply`
(skip-if-exists). This is the per-system Sound folder, distinct from `Media\Main Menu\Sound\`
which controls active-browsing music at the top-level system wheel.

**Zero-byte detection** — `audit.check_media()` uses `stat().st_size > 0` (not just `exists()`) to check each slot. A 0-byte file — left behind when a download completed with an empty HTTP 200 body or was interrupted just before content arrived — is treated identically to an absent file: it appears in the audit's missing-media list and causes `fetch-media` to re-download the slot on the next run. Without this check, a zero-byte stub would permanently satisfy the presence test and the slot would silently stay broken.

### Main Menu wheel image lookup — known failure modes

HyperSpin resolves a system's wheel graphic in `Media\Main Menu\Images\Wheel\` by matching the filename stem (without `.png`) against the system's `<game name="…"/>` entry in `Databases\Main Menu\Main Menu.xml`. **The match is effectively case-sensitive** even on Windows — a casing discrepancy between the XML entry and the image filename causes HyperSpin to intermittently fall back to rendering the system name as plain text instead of the image. (The filesystem finds the file case-insensitively, but HyperSpin's internal cache key is case-exact, so the lookup succeeds on some passes and fails on others.)

**Fix:** rename the wheel image file to match the XML entry name exactly, character for character.

Common examples seen on this cabinet:

| XML entry | Mismatched filename | Correct filename |
|---|---|---|
| `Colecovision` | `ColecoVision.png` | `Colecovision.png` |
| `NEC Turbografx-CD` | `NEC TurboGrafx-CD.png` | `NEC Turbografx-CD.png` |
| `Mugen` | `MUGEN.png` | `Mugen.png` |

**Duplicate wheels from duplicate XML entries** — if `Main Menu.xml` contains two `<game>` entries whose names differ only by casing or a punctuation variant (e.g. `Atari 8-Bit` / `Atari 8-bit`, `Doujin Games` / `Doujin Soft`, `Panasonic 3DO` / `Panasonic 3D0`), HyperSpin renders both as separate wheel items. Typically one entry matches the database folder (loads games correctly) while the other matches the wheel image filename (shows the graphic) — neither item is fully functional on its own. The fix is to remove the incorrect variant, keeping whichever name matches both `Databases\<name>\<name>.xml` and the wheel image file.

The same name must match across three places to avoid split or broken wheels:

```
Databases\Main Menu\Main Menu.xml    <game name="Foo Bar"/>
Databases\Foo Bar\Foo Bar.xml        ← folder and XML filename both match
Media\Main Menu\Images\Wheel\Foo Bar.png  ← image filename matches exactly
```

### Scraper provider comparison

SpinDoctor queries ScreenScraper and TheGamesDB for metadata and media. They have very different capabilities and coverage — understanding the difference is important for diagnosing gaps.

| Capability | ScreenScraper | TheGamesDB |
|---|---|---|
| Metadata (name, year, genre, players) | ✅ | ✅ (genre/developer require `include=genres,developers`) |
| Wheel art | ✅ (multiple regions, US-first) | ✅ clearlogo via `Games/Images` endpoint → wheel slot |
| Background image | ✅ | ✗ |
| Title screenshot | ✅ | ✗ |
| Snap / in-game screenshot | ✅ | ✅ screenshot via `Games/Images` → snap slot |
| Fade image | ✅ | ✗ |
| Video / trailer | ✅ | ✗ |
| Theme (`.zip`) | ✅ (sparse) | ✗ |
| Sound | ✅ (sparse) | ✗ |
| Box art (front/back) | ✅ (as `artwork`) | ✅ (as `artwork`, direct CDN URLs) |
| Newer indie PC games | ⚠️ stub entries, often no media | ✅ (e.g. Peglin 2022 found with clearlogo + boxart) |
| Classic/mainstream games | ✅ full coverage | ✅ metadata + clearlogo + boxart |
| Systems covered | 249 (see `SCREENSCRAPER_SYSTEMS`) | 153 (see `THEGAMESDB_PLATFORMS`) |

**ScreenScraper is the primary provider; TheGamesDB is the complementary fallback.** The default `CombinedMetadataClient` queries both per game: SS metadata and every SS media slot take priority; TGDB fills any slot SS left empty (e.g. wheel clearlogo, snap screenshot). If SS finds nothing at all, the full TGDB result is used. `--source screenscraper|thegamesdb|both` forces a specific behaviour (available in both CLI and GUI). TheGamesDB is especially useful for newer indie PC games that have stub-only entries on ScreenScraper.

**Steam Store is a supplemental per-game source** (not part of the main `fetch-meta`/`fetch-media` pipeline). `SteamClient.fetch_by_app_id(app_id)` hits `store.steampowered.com/api/appdetails?appids=<id>&filters=basic,screenshots,movies` (no auth required) and returns a `GameMetadata` with `video`, `snap`, `background`, `artwork`, and `wheel` candidates populated. The `background` slot uses the same screenshot list as `snap` — the first screenshot is written to `Images\Backgrounds\` as the per-game background; a different screenshot can be selected via `--background-index`. Invoked explicitly via `spindoctor fetch-steam-media` or the GUI's Steam media panel — never as an automatic fallback inside `CombinedMetadataClient`. This keeps the main bulk-fetch path clean: Steam is for the long tail of PC games that SS/TGDB simply don't have, targeted one game at a time. Steam provides no transparent-logo equivalent, so the header capsule image doubles as the `wheel` slot (rectangular banner, not a transparent logo). The `steam_app_id` key in `config.game_overrides` stores the App ID for a game so `fetch-steam-media` can find it without the user re-pasting the URL.

**Windows-invalid filename characters — full list:** `_win_safe_stem()` strips the nine characters Windows forbids in filenames (`\ / : * ? " < > |`), trims leading/trailing spaces, and strips trailing dots. It also guards against Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM0–9`, `LPT0–9`): any of these as a game or system name would silently write to the corresponding device handle instead of creating a file. The function appends `_` when the sanitised stem matches a reserved name (e.g. a hypothetical game "NUL" → `NUL_`). The function is defined in `rocketlauncher.py` (for PCLauncher INI filenames) and copied verbatim into `media.py` (for media paths) to avoid a circular import.

**Steam image format — always PNG:** Steam's `header_image` (used for both `artwork` and `wheel`) and all `screenshots[].path_full` URLs are JPEG. HyperSpin's `Images/Wheel/`, `Images/Artwork1/`, and `Images/Artwork3/` (Snap) folders only load files by their `.png` name — a `.jpg` file in `Wheel/` is simply not found. `MediaDownloader._download_to` therefore never overrides a `.png` destination with a JPEG URL extension. After the download, `_convert_to_png_inplace()` converts the JPEG bytes to real PNG when Pillow (`spindoctor[preview]`) is installed; without Pillow the JPEG content lives under the `.png` name, which Windows GDI+ loads correctly via magic-byte detection.

**Steam video URL format — two assets per trailer:** Steam's `appdetails` API includes both `movies[].mp4.max` and `movies[].hls_h264` for most games. These are **not** the same content at different quality levels: `mp4.max` is a short highlight/autoplay clip (~10–15 s) that autoplays on Steam store browse pages; `hls_h264` is the full-length trailer (the video you see when you click Play on the store page). `_parse_steam` adds **both** as separate `MediaCandidate` entries for each movie entry. After `_parse_steam` returns, `SteamClient.fetch_by_app_id()` fetches the HLS M3U8 master playlist and its first variant stream playlist for each HLS candidate, sums `#EXTINF` segment durations, and stores the result in `MediaCandidate.duration_secs`. The GUI dropdown and CLI picker display this as `M:SS` so the user can distinguish the 11-second highlight from the 1:14 full trailer at a glance. MP4 candidates carry no duration (probing an MP4 requires downloading at least its header). `MediaDownloader._download_to` detects `.m3u8` URLs and delegates to `_download_hls`, which runs:

When the audio rendition is present (the common case for 2024+ Steam titles):

```
ffmpeg -protocol_whitelist file,http,https,tcp,tls,crypto -i <video_variant_url> -i <local_audio_tmp.mp4> -map 0:v:0 -map 1:a:0 -c copy -movflags +faststart <dest>.mp4
```

When no separate audio rendition exists (older muxed-track variants):

```
ffmpeg -protocol_whitelist file,http,https,tcp,tls,crypto -i <video_variant_url> -c copy -movflags +faststart <dest>.mp4
```

`-protocol_whitelist` enables HTTPS segment fetching from Steam's Akamai CDN. `-c copy` stream-copies video and audio tracks without re-encoding — this is critical for CMAF/fMP4 segments: re-encoding audio with `-c:a aac` introduces timestamp discontinuities that cause ffmpeg to silently abort the mux after 2–3 seconds while still exiting 0. `-movflags +faststart` places the moov atom at the start for Windows Media Player seek compatibility. Without ffmpeg a clear error is returned rather than a silent failure.

When an audio rendition is present, `_download_hls` **pre-downloads** the audio segments via the Python `requests` session rather than passing the audio HLS URL directly to ffmpeg. Steam's audio renditions use CMAF/fMP4 segments (`EXT-X-MAP` init segment + `.m4s` chunks); older Windows 7 ffmpeg versions silently truncate CMAF audio HLS after ~5 seconds when given the playlist URL as a second `-i` input — the same family of bug that caused video truncation (fixed by explicit variant selection). Since there is no lower-quality audio fallback, `_download_hls` fetches each segment over HTTPS, concatenates init + chunks into a temporary fMP4 file in the system temp directory, and passes the local path to ffmpeg as the second `-i`. The temp file is removed after the ffmpeg call regardless of success. If any segment download fails the fallback is to pass the rendition URL directly to ffmpeg (the pre-v2.8.1 behaviour).

**HLS quality variants and size:** Steam's HLS master playlist (`hls_h264` URL ending in `_master.m3u8`) contains `EXT-X-STREAM-INF` entries for multiple resolutions and `EXT-X-MEDIA TYPE=AUDIO` entries carrying the audio rendition URI. `_pick_hls_variant(master_url, max_height, session)` parses both, selects the highest-resolution video variant that fits within `max_height`, and returns `(video_variant_url, audio_rendition_url_or_None)`. SpinDoctor always performs explicit variant selection — even when `--hls-quality best` is requested (sentinel `max_height=9999` selects the highest available), the master URL is never passed directly to ffmpeg. Passing the master URL causes ffmpeg to select a CMAF/fMP4 stream (`dash_h264/chunk-stream0-XXXXX.m4s`), which older Windows 7 ffmpeg versions silently abort after ~9 seconds while still exiting 0. The CLI flag `--hls-quality best|1080p|720p|480p|360p` (default `best`) controls the cap. At 1080p a long trailer (e.g. Submachine Legacy at 11:13) can reach 400+ MB; 480p brings the same trailer to ~25 MB. The GUI exposes this as a Quality dropdown (`Best (1080p)` / `720p` / `480p` / `360p`) next to the Overwrite checkbox in the Steam apply row.

**Truncation detection:** After a successful ffmpeg run, `_probe_hls_duration(path, ffprobe)` runs `ffprobe -v quiet -show_entries format=duration -of csv=p=0` on the output file and parses the result as seconds. `_hls_truncation_warning(label, size, duration, stderr_text)` returns a non-empty warning string when the file is below `_HLS_MIN_BYTES` (5 MB) or the duration is below `_HLS_MIN_DURATION_SECS` (30 s). The warning is surfaced in both CLI output and `DownloadResult.warning`. `DownloadResult` carries two additional fields added for this feature: `file_size_bytes: Optional[int]` (output file size after download) and `duration_secs: Optional[float]` (ffprobe result). The CLI prints both alongside the success message as `(XX.X MB, M:SS)`.

**Network error propagation** — `CombinedMetadataClient` raises `MetadataError` when both sources fail (DNS down, timeouts, connection refused). Before v2.7.1 both failures were silently swallowed and every game was counted as "no match", producing `Failed: 500` with no diagnostic output. The error is now printed per-game, and `fetch-media` aborts the metadata phase after 3 consecutive network failures rather than grinding through all games. All details are also written to `%USERPROFILE%\.spindoctor\scraper.log`.

#### Per-game ID overrides bypass name matching entirely

`config.game_overrides` (`{system: {game: {screenscraper_id, thegamesdb_id, steam_app_id}}}`, managed via `spindoctor config game-override set/list/clear` or the GUI's Metadata & Media "Per-game & override (Optional)" panel) lets a cabinet owner force a specific scraper game ID for one title instead of relying on fuzzy name matching — the deterministic fix for a title that just never matches well by name (a recurring repro case: a non-English-primary ScreenScraper listing whose fuzzy `similarity()` score against the English ROM name never clears the match threshold). All three ID options accept a bare numeric ID or a full browser URL; the ID is extracted by `extract_screenscraper_id()` / `extract_thegamesdb_id()` / `extract_steam_app_id()` in `scraper.py`.

Implementation: `ScreenScraperClient.fetch()` and `TheGamesDBClient.fetch()` both check `get_game_override(system_name, game_name)` *before* doing any name-based lookup. If the relevant ID (`screenscraper_id` / `thegamesdb_id`) is set, they call their own `fetch_by_id()` directly and force `match_score = 1.0` — which makes `fetch_with_search()`'s existing `direct.match_score >= threshold` short-circuit accept it immediately, without ever reaching `search()` or the ambiguous-match picker. Each client only acts on the override key it owns (`screenscraper_id` for `ScreenScraperClient`, `thegamesdb_id` for `TheGamesDBClient`), so `CombinedMetadataClient` needs no override-handling code of its own — it already calls both sub-clients' `fetch()` and merges, and gets the override behavior for free for whichever source(s) the user configured.

Deliberately no fallback on a miss: if the forced ID itself fails to resolve (typo, deleted listing), that source returns `None` for the game rather than silently falling back to name search — an explicit override is a statement "I know the right game," and silently fuzzy-matching past a stale ID would be more confusing than just failing visibly. A `WARNING` log entry is emitted to `scraper.log` when this happens (message includes the override ID and the `screenscraper.fr` / `thegamesdb.net` URL to verify it).

**Cache bypass**: `_FetchWithSearchMixin.fetch_with_search()` skips both the cache read *and* cache write whenever `get_game_override(system_name, game_name)` is non-empty. This prevents a pre-override cached result from masking the forced ID on subsequent runs — a common failure mode where the override appears to have no effect because `fetch()` (where the override is applied) is never reached. Without the bypass, a game cached as "no media / screenscraper" before the override was set would continue returning that stale result on every run. With the bypass, every run re-queries the API using the forced ID, so the override takes effect immediately and changing the override later also takes effect on the next run. `fetch-media --verbose` displays the active override IDs (`override: ss=XXXX`) alongside the resolved source so the user can confirm the forced ID was used.

#### TheGamesDB image slots

TheGamesDB images are fetched in a separate `GET /v1/Games/Images?games_id=<id>` call after the main search. The `type` field of each image maps to a HyperSpin media slot:

| TGDB `type` | HyperSpin slot | Notes |
|---|---|---|
| `clearlogo` | `wheel` | Transparent PNG logo — ideal HyperSpin wheel image |
| `screenshot` | `snap` | In-game screenshot |
| `banner` | `background` | Header/banner image |
| `boxart` | `artwork` | Box front/back |

SpinDoctor only fills a slot from TGDB if ScreenScraper did not already find one, so ScreenScraper always wins when it has coverage.

#### TheGamesDB direct lookup must normalize the name like search() does

`TheGamesDBClient.fetch()` (the direct-lookup path tried before falling back to `search()`) and `search()` both hit the same `Games/ByGameName` endpoint, but `fetch()` used to send the raw ROM name while `search()` already normalized it (stripping region tags and romset punctuation). TheGamesDB's own titles never carry No-Intro-style tags, so a name like `Golden Sun - Dark Dawn (USA)` could miss entirely via `fetch()` while `search()` (sent `golden sun dark dawn`) would have matched `Golden Sun: Dark Dawn` just fine — and because `CombinedMetadataClient.fetch()` only calls `fetch()`, never `search()`, `--source both` runs never got the benefit of the better-normalized path. Both now normalize consistently.

#### Region preference for media selection

When ScreenScraper returns multiple candidates for the same slot (e.g. wheel images for US, EU, JP), SpinDoctor picks the best region using this priority order (defined in `_REGION_PREFERENCE`):

```
us → wor → eu → fr → de → es → it → au → br → ru → kr → jp → ss → (unknown)
```

`us` (USA) is always preferred. `wor` (world) is the next best. JP images are intentionally ranked near the bottom to avoid Japanese-only wheel art appearing on English-language cabinets.

### ScreenScraper API response shape variations

ScreenScraper's `/jeuInfos.php` endpoint returns game metadata in a `jeu` object whose fields are not consistently typed — the same field name can be a dict in one system's response and a list of `{region, text}` objects in another. Verified live against GameCube, DS, N64, and PC systems — `dates` is **always a list** in current API responses:

| Field | Observed shape | Notes |
|-------|---------------|-------|
| `dates` | list `[{"region": "us", "text": "YYYY-MM-DD"}, …]` | Always a list; never a dict in any system tested |
| `editeur` | dict `{"text": "Publisher Name"}` | |
| `joueurs` | dict `{"text": "2"}` or plain string `"2"` | Varies by game entry |

SpinDoctor's `_parse_screenscraper` uses `isinstance()` guards on each of these. When adding new field parsers, always guard against both dict and list forms.

### ScreenScraper search results can carry no media at all

`jeuRecherche.php` (the text-search endpoint, used whenever the direct `romnom`-based lookup in `jeuInfos.php` doesn't match) returns a much lighter `jeu` payload per result than `jeuInfos.php` does — it can omit the `medias` array entirely even for a game whose own ScreenScraper detail page has a full gallery. Confirmed live on a Nintendo DS title ("Golden Sun - Dark Dawn (USA)") that resolved correctly by name through search but reported `no URL` for every single requested media type.

`ScreenScraperClient.search()` now detects this: if the top-scoring result has no media candidates at all, it issues one follow-up `fetch_by_id()` call (`jeuInfos.php?gameid=<id>`) to backfill the full gallery before returning. Only the top result is enriched — not all `max_results` candidates — to avoid burning API quota on results that won't be used. This is best-effort: if the by-ID lookup also comes back empty, the game genuinely has no media for that source/account combination (e.g. a free ScreenScraper account hitting premium-only assets).

### ScreenScraper media URL format

All ScreenScraper media is served via PHP scripts (`mediaJeu.php`, `mediaVideoJeu.php`). The URL extension is always `.php` regardless of actual content type:

```
https://neoclone.screenscraper.fr/api2/mediaJeu.php?devid=…&systemeid=13&jeuid=4803&media=wheel(us)
```

The file content is a real PNG/JPEG/MP4. `MediaDownloader._download_to` must **not** use the URL path suffix (`.php`) to rename the destination — doing so saves `Pikmin.php` instead of `Pikmin.png` and HyperSpin cannot find it. The extension-override logic is restricted to known media extensions (`.png`, `.jpg`, `.mp4`, etc.) to prevent this.

**Windows NTFS and colons in game names** — Windows treats a colon in a filename as an Alternate Data Stream (ADS) separator: `Submachine: Legacy.png` is interpreted as the main-stream file `Submachine` (0 bytes) plus an ADS named ` Legacy.png`. `os.replace()` across an ADS boundary fails with `WinError 87 The parameter is incorrect`. HyperSpin resolves this by stripping all Windows-invalid filename characters (`\ / : * ? " < > |`) from the game name before doing media file lookups. `MediaDownloader.media_path()` now applies the same `_win_safe_stem()` function so the path SpinDoctor writes and the path HyperSpin reads always agree. Games with colons (`Submachine: Legacy`) resolve to `Submachine Legacy.png`, not `Submachine: Legacy.png`.

**Empty-body detection** — After the atomic `os.replace(part, dest)`, `_download_to` checks `dest.stat().st_size > 0`. A server that returns HTTP 200 with an empty body (CDN misconfiguration, transient auth failure surfaced as a 200) would otherwise leave a 0-byte file and return `success=True`. Instead, the empty file is removed and the attempt is counted as a failure — the retry loop re-attempts up to `max_retries` with exponential backoff before surfacing a descriptive error to the caller.

### Platform / system ID maps

SpinDoctor has two lookup dicts in `scraper.py`: `SCREENSCRAPER_SYSTEMS` and `THEGAMESDB_PLATFORMS`, covering the full system/platform catalogs of both APIs (verified against the live APIs on 2026-06-14).

Common cabinet systems for quick reference:

| System | ScreenScraper ID | TheGamesDB ID |
|---|---|---|
| MAME / Arcade | 75 | 23 |
| NES | 3 | 7 |
| SNES | 4 | 6 |
| Nintendo 64 | 14 | 3 |
| Nintendo GameCube | 13 | 2 |
| Nintendo Wii | 16 | 9 |
| Nintendo DS | 15 | 8 |
| Nintendo 3DS | 17 | 4912 |
| Game Boy | 9 | 4 |
| Game Boy Advance | 12 | 5 |
| Sega Genesis / Mega Drive | 1 | 18 |
| Sega Saturn | 22 | 17 |
| Sega Dreamcast | 23 | 16 |
| PlayStation | 57 | 10 |
| PlayStation 2 | 58 | 11 |
| PlayStation 3 | 59 | 12 |
| PSP | 61 | 13 |
| Xbox | 32 | 14 |
| Xbox 360 | 33 | 15 |
| Neo Geo / Neo Geo MVS | 142 / 68 | 24 |
| TurboGrafx-16 / PC Engine | 31 | 34 |
| Atari 2600 | 26 | 22 |
| PC / Windows (`PC GAMES`) | 138 | 1 |
| PC / DOS | 135 | 1 |
| Capcom Play System (CPS1) | 6 | — |
| Capcom Play System II (CPS2) | 7 | — |

ScreenScraper splits DOS/legacy PC (id=135, key `"pc"`) from PC Windows/exe (id=138, keys `"pc games"`, `"windows"`, `"steam"`). Use `system_overrides.screenscraper_id` in your project config to override any lookup for a specific system.

---

## RetroArch Input Architecture

### Input chain overview

Physical arcade buttons → **keyboard encoder (I-PAC-style)** → USB keystrokes → RetroArch reads them as keyboard input.

Simultaneously, the **Xbox 360 controller** connects over USB and is read by RetroArch via the `winxinput` joypad driver — independently of the keyboard encoder path. **Xpadder** is also running, but it only virtualises additional keyboard/mouse events for the controller; the raw controller is still visible to RetroArch through `winxinput`.

Both input sources can be bound in a single RetroArch system cfg. RetroArch fires an action if **either** the keyboard key **or** the controller button is pressed.

### System-level cfg files

RetroArch reads a per-system config file in addition to `retroarch.cfg`:

```
D:\Arcade\Emulators\RetroArch\config\<System Name>.cfg
```

These files override any key they define, leaving everything else inherited from the global `retroarch.cfg`.

### Hardware: Ultimarc Mini-PAC + PAC-LED64

The cabinet uses two Ultimarc boards over USB:

| Board | Purpose |
|-------|---------|
| **Mini-PAC** | Keyboard encoder — translates button presses, joystick directions, and trackball clicks into USB HID keyboard/mouse events |
| **PAC-LED64** | LED controller — drives the LEDs inside the buttons; entirely separate from input mapping |

> **This cabinet has two PAC-LED64 boards**, enumerated as `Id="1"` and `Id="2"` (see `LEDBlinkyInputMap.xml`). Full per-board RGB channel map: [LEDBlinky Animation Files (.lwax)](#ledblinky-animation-files-lwax) below.

The Mini-PAC is configured with **WinIPAC** (Ultimarc's free Windows utility). It reads and writes the board's EEPROM directly over USB — the mapping persists on the board with no software running. Config can be exported/imported as XML. Note: button nicknames (display labels) are stored in the XML file on disk, not in the EEPROM — they are lost if WinIPAC is closed without File → Save.

#### Physical button layout

```
 ┌─────────────────────────────────────────────────────────────────┐
 │                    PLAYER 1              PLAYER 2               │
 │                                                                 │
 │  Joystick            [↑]                    [N]                │
 │                   [←][↓][→]             [M][Q][O]              │
 │                                                                 │
 │  Coin / Start      [S]  [R]             [U]  [T]               │
 │                                                                 │
 │  Top row      [A] [B] [C] [V]      [G] [H] [I] [Y]            │
 │  Bottom row   [D] [E] [F] [W]      [J] [K] [L] [X]            │
 │                                                                 │
 │  Admin:  [Enter]  [Esc]  [/]  [P]                              │
 │  Trackball:  [Mouse L]  [Mouse M]                              │
 │                                                                 │
 │  Hold [S] (P1 Coin) +                                          │
 │    [↑] → Volume Up     [↓] → Volume Down    [Enter] → RetroArch Menu │
 └─────────────────────────────────────────────────────────────────┘
```

Letters in use: A B C D E F G H I J K L M N O P Q R S T U V W X Y  
Letters free: Z

#### Pin-to-key mapping

All 34 input pins decoded from the WinIPAC EEPROM export (USB HID keycodes → key names):

| Pin | Key | Logical function |
|-----|-----|-----------------|
| pin02 | Enter | Select / confirm |
| pin03 | Escape | Exit |
| pin04 | `/` | Search |
| pin05 | P | Pause |
| pin06 | X | P2 Button 8 |
| pin07 | L | P2 Button 7 |
| pin08 | K | P2 Button 6 |
| pin09 | J | P2 Button 5 |
| pin12 | Y | P2 Button 4 |
| pin13 | I | P2 Button 3 |
| pin14 | H | P2 Button 2 |
| pin15 | G | P2 Button 1 |
| pin16 | Q | P2 Down |
| pin17 | N | P2 Up |
| pin18 | M | P2 Left |
| pin19 | O | P2 Right |
| pin22 | U | P2 Coin |
| pin23 | S *(shift/swop key)* | P1 Coin |
| pin24 | T | P2 Start |
| pin25 | R | P1 Start |
| pin26 | W | P1 Button 8 |
| pin27 | F | P1 Button 7 |
| pin28 | E | P1 Button 6 |
| pin29 | D | P1 Button 5 |
| pin32 | V | P1 Button 4 |
| pin33 | C | P1 Button 3 |
| pin34 | B | P1 Button 2 |
| pin35 | A | P1 Button 1 |
| pin36 | ↓ Down Arrow | P1 Down |
| pin37 | ↑ Up Arrow | P1 Up |
| pin38 | ← Left Arrow | P1 Left |
| pin39 | → Right Arrow | P1 Right |
| pin42 | Mouse Middle Button | Trackball button |
| pin43 | Mouse Left Button | Trackball button |

Trackball movement is handled by the Mini-PAC's analog axes (Axis1/Axis2), not by pin-mapped keys.

#### Button function reference

**Swop (secondary) key functions**

Pin23 (P1 Coin, key `s`) acts as a shift/swop key. Hold it and press a second button to trigger its secondary function:

| Combination | Secondary key | Function |
|-------------|--------------|---------|
| P1 Coin + Joystick Up (pin37) | Volume Up | Windows system volume up (consumer HID control — visible in Windows mixer) |
| P1 Coin + Joystick Down (pin36) | Volume Down | Windows system volume down (consumer HID control — visible in Windows mixer) |
| P1 Coin + Select (pin02) | Tab | RetroArch Quick Menu (cabinet uses Tab instead of the default F1) |

**Admin buttons**

| Mini-PAC pin | Key | Function |
|-------------|-----|---------|
| pin02 | Enter | Select |
| pin03 | Escape | Exit |
| pin04 | `/` (Forward-Slash) | Search |
| pin05 | `p` | Pause |
| pin42 | Right Mouse Button | Right click |
| pin43 | Left Mouse Button | Left click |

**Player 1**

| Mini-PAC pin | Key | Function | RetroArch action |
|-------------|-----|---------|-----------------|
| pin23 | `s` | Coin | `input_player1_select` |
| pin25 | `r` | Start | `input_player1_start` |
| pin26 | `w` | Button 8 | — |
| pin27 | `f` | Button 7 | `input_player1_r` |
| pin28 | `e` | Button 6 | `input_player1_l` |
| pin29 | `d` | Button 5 | `input_player1_x` |
| pin32 | `v` | Button 4 | — |
| pin33 | `c` | Button 3 | `input_player1_y` |
| pin34 | `b` | Button 2 | `input_player1_a` |
| pin35 | `a` | Button 1 | `input_player1_b` |
| pin36 | `↓` (Down arrow) | Down | `input_player1_down` |
| pin37 | `↑` (Up arrow) | Up | `input_player1_up` |
| pin38 | `←` (Left arrow) | Left | `input_player1_left` |
| pin39 | `→` (Right arrow) | Right | `input_player1_right` |

**Player 2**

| Mini-PAC pin | Key | Function | RetroArch action |
|-------------|-----|---------|-----------------|
| pin06 | `x` | Button 8 | — |
| pin07 | `l` | Button 7 | `input_player2_r` |
| pin08 | `k` | Button 6 | `input_player2_l` |
| pin09 | `j` | Button 5 | `input_player2_x` |
| pin12 | `y` | Button 4 | — |
| pin13 | `i` | Button 3 | `input_player2_y` |
| pin14 | `h` | Button 2 | `input_player2_a` |
| pin15 | `g` | Button 1 | `input_player2_b` |
| pin16 | `q` | Down | `input_player2_down` |
| pin17 | `n` | Up | `input_player2_up` |
| pin18 | `m` | Left | `input_player2_left` |
| pin19 | `o` | Right | `input_player2_right` |
| pin22 | `u` | Coin | `input_player2_select` |
| pin24 | `t` | Start | `input_player2_start` |

RetroArch uses SNES button names (`a`, `b`, `x`, `y`, `l`, `r`) which map differently from physical layout — `input_player1_b` is the "first/primary" action button, `input_player1_a` is "second", and so on.

Buttons 4 and 8 for both players have no RetroArch binding yet — they send unique keys (`v`, `w`, `y`, `x`) and can be bound to any action in a system cfg.

### Xbox 360 button numbers (winxinput driver)

| Button | `_btn` value | Notes |
|--------|-------------|-------|
| A | `0` | Primary action |
| B | `1` | Secondary action |
| X | `2` | |
| Y | `3` | |
| LB | `4` | |
| RB | `5` | |
| Back | `6` | Maps to Select/Coin |
| Start | `7` | |
| D-pad Up | `h0up` | Hat switch |
| D-pad Down | `h0down` | Hat switch |
| D-pad Left | `h0left` | Hat switch |
| D-pad Right | `h0right` | Hat switch |

### Dual keyboard + controller binding in a single cfg

A single system cfg can hold both binding forms simultaneously. RetroArch fires the action if either input is triggered:

```ini
input_player1_up = "up"       # keyboard encoder → Up arrow
input_player1_up_btn = "h0up" # Xbox 360 d-pad up
```

This is the correct approach for this cabinet: do not maintain two separate profiles. Put both in one `.cfg` file.

### Critical: explicit `"nul"` bindings override autodetect

When a system cfg sets bindings to `"nul"`:

```ini
input_player1_up = "nul"
input_player1_up_btn = "nul"
```

RetroArch **actively disables** those inputs for that player. The explicit `"nul"` overrides:
- `input_autodetect_enable = "true"` — autodetect is suppressed for that binding
- `keyboard_gamepad_enable = "true"` — keyboard gamepad mode is suppressed for that binding

The result is that the entire control set is dead, even though autodetect and keyboard gamepad are nominally enabled. Controls working fine on other systems is not evidence against this — other systems either have no system cfg, or their system cfgs do not have explicit `"nul"` overrides.

**Symptom:** Controls are completely non-functional for one system while all other emulators on the same cabinet work fine.

**Fix:** Replace `"nul"` with the correct keyboard key string and/or controller button number.

### RetroArch Quick Menu access

The Quick Menu hotkey is system-cfg-controlled. The global `retroarch.cfg` default is `F1`, but a system cfg can override it:

```ini
input_menu_toggle = "tab"   # Quick Menu opens with Tab, not F1
```

The `Nintendo Game & Watch.cfg` on this cabinet uses `Tab`. The Xpadder profile for this system sends no `Tab` key, so Quick Menu requires a physical keyboard — it cannot be opened from the arcade controls alone.

### Nintendo Game & Watch — system notes

| Property | Value |
|----------|-------|
| System name (RL) | `Nintendo Game & Watch` |
| Emulator | RetroArch |
| Core | `gw_libretro` |
| RL module | `LibRetro_GW` |
| ROM extension | `.mgw` |
| ROM path | `J:\Games\Nintendo Game & Watch\` |
| RetroArch cfg | `D:\Arcade\Emulators\RetroArch\config\Nintendo Game & Watch.cfg` |
| Savefile dir | `:\saves\Nintendo Game & Watch` |
| Savestate dir | `:\states\Nintendo Game & Watch` |
| Quick Menu hotkey | `Tab` (keyboard only) |

The system cfg had all `input_player1_*` and `input_player2_*` bindings set to `"nul"`, making controls completely non-functional. Fixed by patching both keyboard encoder and Xbox 360 controller bindings into the cfg (see *Dual keyboard + controller binding* above).

No AHK keymapper profile exists for this system — `D:\Arcade\RocketLauncher\Profiles\AHK\Nintendo Game & Watch\RetroArch.ahk` and `_Default.ahk` are both absent. This is logged as a WARNING by RocketLauncher but is not an error.

---

## LEDBlinky

### Key files

| File | Purpose |
|------|---------|
| `C:\LEDBlinky\Settings.ini` | Main application settings — animation modes, emulator config paths, speech, audio |
| `C:\LEDBlinky\controls.ini` | Per-ROM button assignments (what buttons a game uses) |
| `C:\LEDBlinky\Colors.ini` | Per-ROM LED colors for each assigned button |
| `C:\LEDBlinky\LEDBlinkyControls.xml` | Per-emulator / per-ROM XML control map used by LedBlinky at runtime |
| `C:\LEDBlinky\Color-RGB.ini` | Master named color dictionary (R,G,B intensity 0-48) |
| `C:\LEDBlinky\*.lwa` | Animation files — played for idle / attract / in-game states |

### Filename casing — critical on Linux, invisible on Windows

LedBlinky is a Windows application and its filenames use mixed case. Windows filesystems are case-insensitive so `Colors.ini` and `colors.ini` resolve to the same file. Linux filesystems (including CI runners) are case-sensitive — a single wrong character silently breaks every path lookup with no error message other than "file not found."

**Authoritative filename spelling:**

| Constant in `ledblinky.py` | Exact filename | Notes |
|----------------------------|----------------|-------|
| `COLORS_INI_NAME` | `Colors.ini` | capital **C** |
| `CONTROLS_INI_NAME` | `controls.ini` | all lowercase |
| `CONTROLS_XML_NAME` | `LEDBlinkyControls.xml` | all-caps **LED** |
| `COLOR_RGB_NAME` | `Color-RGB.ini` | mixed case, hyphen |
| _(inline)_ | `Settings.ini` | capital **S** |
| _(inline)_ | `LEDBlinkyLog.txt` | all-caps **LED** |

**Rule for contributors:** never write a LedBlinky filename as a bare string literal anywhere in `spindoctor/ledblinky.py`. Use the named constants above. The test `test_filename_constants_exact_casing` and `test_no_bare_colors_ini_string_in_module` in `tests/test_ledblinky.py` will fail in CI if a constant is changed or a bare string literal is introduced.

> **History:** `Colors.ini` was accidentally written as `colors.ini` (lowercase) in four separate path constructions across `generate_for_roms`, `sync_player_colors`, and two helper functions. This was undetectable on any developer's Windows machine and only surfaced when CI ran on Linux (PR #248). The named-constant pattern was already used for `CONTROLS_XML_NAME` and `COLOR_RGB_NAME` but had not been applied to the two most-commonly referenced files. Fixed in the same PR by adding `COLORS_INI_NAME` and `CONTROLS_INI_NAME` and replacing all inline strings.

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
| Intro Video Randomizer (`introvideo add` / `introvideo remove`) | `config.backup_dir/IntroVideoRandomizer/` |

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

### `controls.ini` and `Colors.ini` — generation

`spindoctor ledblinky generate` reads MAME's `listxml` output and writes two files:

**`controls.ini`** — lists which controls each ROM uses. Each ROM section contains keys like `P1_BUTTON1=1`, `P1_JOYSTICK=1`, `P2_BUTTON1=1`, `P2_JOYSTICK=1`, etc. Multi-player ROMs get entries for every player that appears in MAME's input list. SpinDoctor pre-2.4.22 incorrectly wrote metadata keys (`P1_NUMBUTTONS`, `P1_CONTROLS`) instead of per-control keys; regenerate with `--overwrite --apply` if your controls.ini has that format.

**`Colors.ini`** — maps each control key to a color name from `Color-RGB.ini`. **`generate` only writes Player 1 keys** (`P1_BUTTON1`, `P1_JOYSTICK`, `P1_START`, `P1_COIN`). Player 2 and higher keys are left out of `Colors.ini` even when `controls.ini` correctly lists them. This means P2+ buttons illuminate with LedBlinky's XML fallback color (usually white) rather than the intended game color.

**`colors sync-players`** fills the P2+ gap as a post-generation step. It cross-references `controls.ini` (which has correct multi-player keys) against `Colors.ini` and, for every ROM where additional-player keys appear in `controls.ini` but are absent from `Colors.ini`, it inserts the missing keys mirroring the matching P1 color. Works for **any number of players** — P2, P3, P4, and beyond:

```
controls.ini: [4player]  P2_BUTTON1=1  P3_BUTTON1=1  P4_BUTTON1=1
Colors.ini:   [4player]  P1_BUTTON1=Red
              →  adds P2_BUTTON1=Red  P3_BUTTON1=Red  P4_BUTTON1=Red
```

Rules enforced by `sync-players`:
- Only adds keys explicitly listed in `controls.ini` — never invents controls.
- Never overwrites an existing `P{n≥2}` color entry unless `--override` is passed.
- With `--override`, existing P2+ entries are replaced with the current P1-mirrored color. P1 keys are never modified.
- Skips a key if the matching P1 color is absent in `Colors.ini` (no fallback invented).
- Single-player ROMs (no P2+ keys in `controls.ini`) are silently skipped.

```bat
spindoctor ledblinky generate --apply                                  :: write controls.ini + Colors.ini (P1 only)
spindoctor ledblinky colors sync-players                               :: preview additions
spindoctor ledblinky colors sync-players --apply                       :: write P2/P3/P4+ color entries
spindoctor ledblinky colors sync-players --apply --verbose             :: show every key added per ROM
spindoctor ledblinky colors sync-players --apply --override            :: replace existing P2+ entries too
```

### `Settings.ini` — idle animation and in-game behavior

Two keys control behaviors that aren't obvious in LedBlinky's configuration UI:

**`[GameOptions] GamePlayLWAFile=`**
Controls what happens to buttons **not used by the current game** while a game is running. The default value `<Random>` makes LedBlinky play a random animation on all unassigned buttons — which looks like random flashing on unused buttons.

- **`""` (empty)** — LedBlinky falls back to each button's `defaultInactive` color from `LEDBlinkyControls.xml`. The DEFAULT control group has `defaultInactive="0,0,0,0"`, so unused buttons go off. Recommended for a clean gameplay experience.
- **`lwa\MyAnim.lwa`** (relative path from `ledblinky_dir`) — LedBlinky plays that animation on all unused buttons during gameplay. This is a global setting; `Settings.ini` has no per-game or per-system override for this key.

`.lwa` animation files are stored under `<ledblinky_dir>\lwa\` and its subdirectories.

**`[FEOptions] FELWAFile=`**
Controls the animation played on buttons while actively browsing the HyperSpin frontend. `<Random>` picks a different animation file every time. Set to a specific animation filename (relative to the `lwa\` subdirectory inside `ledblinky_dir`, e.g. `Slow Fade.lwa` or `subdir\pattern.lwax`) for a consistent smooth effect, or empty for static colors. LedBlinky always prepends `lwa\` when resolving this value, so supplying `lwa\Slow Fade.lwa` would produce a double-prefix error (`lwa\lwa\Slow Fade.lwa`).

**`[FEOptions] FEScreenSaverLWAFile=`**
Controls the animation played during the HyperSpin screen saver. Uses the same filename convention as `FELWAFile` (relative to `lwa\`, no `lwa\` prefix). Set to a `.lwa` / `.lwax` filename for a specific animation, or empty to silence it.

SpinDoctor patches all three keys with `spindoctor ledblinky patch-settings`. A timestamped `.bak` copy of `Settings.ini` is written before any change.

```bat
spindoctor ledblinky patch-settings --apply                                                   :: fix in-game unused-button flash
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --apply                         :: set FE active animation
spindoctor ledblinky patch-settings --ss-lwa "Slow Fade.lwa" --apply                         :: set screen saver animation
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --ss-lwa "Slow Fade.lwa" --apply :: set both
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

5. **P2/P3/P4+ buttons light wrong color (white/fallback) while P1 is correct** — `Colors.ini` is missing additional-player entries. `ledblinky generate` only writes P1 keys; multi-player games need a second step. Run `spindoctor ledblinky colors sync-players --apply` to mirror P1 colors to all additional-player keys listed in `controls.ini` (supports any number of players). If P2+ entries already exist but show wrong colors, add `--override` to replace them.

### Diagnosing colors not applying at runtime

When game colors show as white despite correct `Colors.ini` entries, the most common causes are:

1. **Name mismatch** — the name RocketLauncher sends to LedBlinky does not match the `[romname]` section header in `Colors.ini`. Check `LEDBlinkyLog.txt` for the exact name received.
2. **Legacy hex format** — `Colors.ini` entries use `ledcolor1=FF0000` format that LedBlinky cannot read. Run `colors normalize --apply`.
3. **No `LEDBlinkyControls.xml` per-game entry** — LedBlinky uses its DEFAULT control group and may ignore `Colors.ini` overrides for that game.
4. **`Use Color File` disabled** — LedBlinky Settings UI has a toggle; if off, `Colors.ini` is never consulted.
5. **P2/P3/P4+ buttons show wrong color** — `Colors.ini` has P1 entries but is missing additional-player entries, or existing P2+ entries have stale colors. Run `spindoctor ledblinky colors sync-players --apply` to add missing entries; add `--override` to also replace existing ones. See *`controls.ini` and `Colors.ini` — generation* above.

```bat
spindoctor ledblinky inspect-rom 005   :: read Colors.ini, controls.ini, XML, listxml for ROM "005"
```

`inspect-rom` reports what LedBlinky would see for a specific ROM, flags any mismatches, and prints the path to `LEDBlinkyLog.txt` with instructions on what to search for.

---

## LEDBlinky Animation Files (.lwax)

> **Status: partially reverse-engineered, unresolved blocker on the signing step.** Everything below came from inspecting a folder of sample `.lwax` files (not this cabinet's own) plus this cabinet's `LEDBlinkyInputMap.xml` — not from LedBlinky's own documentation or source. The hardware/channel-map portion is high-confidence (read directly from a live config file). The file-format portion is medium-confidence (inferred from example files, not confirmed against LedBlinky's actual parser). Treat this section as provisional; correct or strip it once resolved.

### Hardware: two PAC-LED64 boards, RGB per control

Read from `D:\Arcade\LEDBlinky\LEDBlinkyInputMap.xml` (`<ledController type="3" id="…" name="PACLED64">`). Each physical control uses **3 consecutive output ports** (R, G, B in that order) — these are full RGB button LEDs, not single-color.

**Board `Id="1"`** (ports 1-42 used, 43-64 unwired):

| Ports | Control |
|---|---|
| 1-3 | TRACKBALL |
| 4-6 | SELECT |
| 7-9 | RMOUSE |
| 10-12 | LMOUSE |
| 13-15 | P1COIN |
| 16-18 | P1START |
| 19-21 | P1B7 |
| 22-24 | P1B3 |
| 25-27 | P1B2 |
| 28-30 | P1B1 |
| 31-33 | P1B8 |
| 34-36 | P1B6 |
| 37-39 | P1B5 |
| 40-42 | P1B4 |

**Board `Id="2"`** (ports 1-39 used, 40-64 unwired):

| Ports | Control |
|---|---|
| 1-3 | EXIT |
| 4-6 | SEARCH |
| 7-9 | PAUSE |
| 10-12 | P2START |
| 13-15 | P2COIN |
| 16-18 | P2B1 |
| 19-21 | P2B2 |
| 22-24 | P2B3 |
| 25-27 | P2B7 |
| 28-30 | P2B4 |
| 31-33 | P2B5 |
| 34-36 | P2B6 |
| 37-39 | P2B8 |

> **Sample `.lwax` files found online/in packs universally target `PACLED64 Id="0"`.** This cabinet has no board at `Id="0"` — it's `Id="1"` and `Id="2"`. Any downloaded pattern using `Id="0"` needs its Device/Id rewritten to match, in addition to the signing problem below.

### File format (inferred from example files, not confirmed authoritative)

`.lwax` is plain UTF-8 XML, CRLF line endings:

```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- (40-hex-char signature) -->
<!-- DO NOT EDIT THIS FILE MANUALLY -->
<LEDAnimation>
  <Frame Number="1" Duration="35">
    <Intensity Device="PACLED64" Id="1" Value="48,0,0,...(64 values, 0-48 brightness)"/>
    <State Device="PACLED64" Id="1" Value="1,1,1,...(64 values, 0/1 on-off)"/>
  </Frame>
  <Frame Number="2" Duration="35">
    ...
  </Frame>
</LEDAnimation>
```

- `Frame Duration` is milliseconds the frame holds.
- `Intensity` = per-port brightness, 0-48 (not 0-255).
- `State` = per-port on/off. Only present on `LEDWiz` in the sample files; absent for `PACDrive`/`PACLED64` (LedWiz-only hardware pulse-profile selector).
- **Values persist frame-to-frame unless redeclared** — confirmed by example: a frame can omit `Intensity` entirely and the previous frame's values carry forward. `slowfadeupdown.lwax` (this cabinet's current, confirmed-working `FELWAFile`/`FEScreenSaverLWAFile`) sets `State=1` once and then only re-declares `Intensity` on each subsequent frame to ramp brightness — this is how a smooth fade is distinguished from a hard on/off chase in the same format.
- Other devices seen in example files (not present on this cabinet): `LEDWiz` (32 ports), `PACDrive` (16 ports, on/off only, no `Intensity`).

### Blocker: `.lwax` files carry a signature LedBlinky validates at load time

A hand-built `.lwax` (well-formed XML, correct channel map, no other errors) fails to load in LedBlinky Config with:

> Animation File has a missing or invalid signature or an error occurred loading the Animation File. See LBC_Errors.Log for details

`LBC_Errors.log` logs it as `Missing Signature [<filename>]`. This is a real check, not cosmetic — every sample `.lwax` opens with a `<!-- (40-hex-char string) -->` comment on line 2 that looks like a checksum but does not match SHA-1/MD5/SHA-224/256/384/512/RIPEMD-160 of the file content under any canonicalization tried (raw bytes, UTF-16LE, comment stripped, whitespace-compacted, numeric-values-only, CRLF vs LF). Confirmed **not machine/install-specific**: `slowfadeupdown.lwax` is unmodified from its original pattern pack (not authored on this cabinet) and loads fine, while a different pack file (`PatternRelax.lwax`) previously hit the identical `Missing Signature` error. So the signature is portable and content-derived by some algorithm — just not one recoverable from the visible XML alone. Most likely a keyed signature (HMAC or similar) baked into LedBlinky's binary.

**Practical implication:** `.lwax` files cannot be hand-authored or edited outside LedBlinky's own tooling. To create a new animation, it must be built with LedBlinky's own **Animation Editor** (part of LedBlinky Config / `LEDBlinkyConfigWizard.exe`) so the tool signs its own output. This is unresolved/untested as of this writing — next step is confirming that editor's location and workflow on this cabinet.
