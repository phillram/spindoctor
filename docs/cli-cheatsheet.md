# CLI cheatsheet

Quick, copy-paste-friendly index of the most-used SpinDoctor commands, grouped by intent. Each section names the command, what it's for, the canonical invocation, and the flags you'll reach for most often.

> **Looking for every flag?** This page is the fast index. The full reference — every command, every flag, every edge case — lives at [Command reference](commands.md). The deep cross-links below jump straight to the relevant section there.

> **Don't want to type any of this?** The GUI's [Console tab](gui.md#tab-tour) has all of these in a curated preset dropdown. Pick, edit the `<PLACEHOLDER>` tokens, click Run.

> **Dry-run by default.** Commands that modify files preview their plan unless invoked with `--apply`. Most destructive commands also write a manifest under `~/.spindoctor/` and accept `--undo` to roll back. See [Recovery from mistakes](workflows.md#recovery-from-mistakes).

## Contents

- [Discover & diagnose](#discover--diagnose)
- [Edit & curate](#edit--curate)
- [Metadata & media](#metadata--media)
- [Backup, diff, migrate](#backup-diff-migrate)
- [Custom wheels](#custom-wheels)
- [Intro Video Randomizer](#intro-video-randomizer)
- [Resetting cabinet data](#resetting-cabinet-data)
- [Themes & art](#themes--art)
- [LEDBlinky](#ledblinky)
- [Light guns](#light-guns)
- [Config](#config)
- [Tips](#tips)

---

## Discover & diagnose

Read-only commands — safe to run any time, never modify files.

### See every command and what it does

```bat
spindoctor --help
spindoctor audit --help          :: per-command help
```

### `tools-audit` — inventory third-party arcade tools

Scans common install paths for HyperSpin / RocketLauncher / HyperHQ / RocketLauncherUI / DemulShooter / Sinden / etc. Useful right after standing up a cabinet.

```bat
spindoctor tools-audit
spindoctor tools-audit --report D:\tools_audit.csv    :: save CSV (category, tool, replaced-by, path)
```

Reference: [Command reference → tools-audit](commands.md#tools-audit).

### `doctor` — self-diagnose paths, binaries, DB integrity

Validates `config.json`, walks `roms_dir` / `hyperspin_dir`, probes scraper credentials, checks for orphan databases. Run after any config change.

```bat
spindoctor doctor
```

Reference: [Command reference → doctor](commands.md#doctor).

### `audit` — compare ROMs vs the HyperSpin DB

```bat
spindoctor audit --system MAME
spindoctor audit --all                            :: every system
spindoctor audit --all --no-media                 :: skip media-presence checks
spindoctor audit --system MAME --detailed         :: per-file sizes + image dims
spindoctor audit --all --report D:\audit.csv      :: write a spreadsheet
```

Reference: [Command reference → audit](commands.md#audit).

### `verify` — ROM integrity vs No-Intro / Redump / TOSEC DAT

```bat
spindoctor verify --system NES --dat path\to\nointro-nes.dat
```

Reference: [Command reference → verify](commands.md#verify).

### `find-global` — search every system for a game

```bat
spindoctor find-global "house of the dead"
spindoctor find-global zelda --limit 20
```

Reference: [Command reference → find-global](commands.md#find-global).

### `find-dupes` / `find-misplaced` / `find-orphan-media`

```bat
spindoctor find-dupes --all
spindoctor find-dupes --cross-systems            :: ROMs that exist under 2+ systems
spindoctor find-misplaced --all                  :: ROMs whose extension/format doesn't match the folder system
spindoctor find-orphan-media --all               :: Media/ files with no DB entry
```

Reference: [find-dupes](commands.md#find-dupes), [find-misplaced](commands.md#find-misplaced), [find-orphan-media](commands.md#find-orphan-media).

### `check-discs` — multi-disc M3U sanity

```bat
spindoctor check-discs --all
spindoctor check-discs --system "Sony Playstation"
```

Reference: [Command reference → check-discs](commands.md#check-discs).

### `check-archive-ext` — detect ROM format mismatches before launch

Peeks inside `.zip` / `.7z` / `.rar` archives and reports inner file extensions that are
not in the emulator's configured `Rom_Extension=` list. Catches `.rvz`, `.nkit.iso`, and
other non-standard formats that cause RocketLauncher's *"No valid roms found in the
archive"* error.

```bat
spindoctor check-archive-ext --system "Nintendo Gamecube"
spindoctor check-archive-ext --all
```

Reference: [Command reference → check-archive-ext](commands.md#check-archive-ext).

### `inspect` — per-file deep-dive for one game

```bat
spindoctor inspect --system MAME --game 1942
spindoctor inspect --system SNES --no-path
spindoctor inspect --system MAME --all --format csv --output D:\manifest.csv
```

Reference: [Command reference → inspect](commands.md#inspect).

---

## Edit & curate

Modify the library — every command below is dry-run by default; add `--apply` to commit.

### `batch-edit` — change metadata for many games at once

```bat
:: Preview first
spindoctor batch-edit --system MAME --filter genre=Action --set rating=5
:: Commit
spindoctor batch-edit --system MAME --filter genre=Action --set rating=5 --apply

:: Multi-field, multi-filter
spindoctor batch-edit --system SNES --filter manufacturer=Nintendo --set genre=Platformer --set rating=4 --apply
```

Reference: [Command reference → batch-edit](commands.md#batch-edit).

### `rename` / `clone` — single-game ROM + XML edits in one shot

```bat
spindoctor rename --system "Sony Playstation" --game "Final Fantasy VII" --to "Final Fantasy 7" --apply
spindoctor clone  --system "Sony Playstation" --game "Resident Evil" --to "Resident Evil (clone)" --apply
```

Reference: [rename](commands.md#rename), [clone](commands.md#clone).

> **GUI:** Games tab → Step 2. The system is set by the shared picker at the top of the tab — the game dropdown auto-populates from the database. ↻ refreshes the list.

### `curate` — region / revision thinning

Picks the canonical ROM per game from a multi-version dump (USA / Europe / Japan / World / rev0 / rev1 / …) and archives or deletes the rest.

```bat
spindoctor curate --all                         :: preview only
spindoctor curate --all --regions USA,World     :: regional preference
spindoctor curate --all --prefer-revision latest :: prefer the latest rev
spindoctor curate --all --action archive --apply
spindoctor curate --all --action delete --apply :: DESTRUCTIVE, no undo
spindoctor curate --undo latest --apply         :: roll back the last archive run
```

Reference: [Command reference → curate](commands.md#curate).

### `cleanup` — safe-cache + lifecycle housekeeping

```bat
spindoctor cleanup categories         :: list disk-space hogs SpinDoctor manages
spindoctor cleanup audit              :: same in summary form
spindoctor cleanup audit --report D:\cleanup_audit.csv    :: save CSV (category, count, size, dates)
spindoctor cleanup run --apply
```

Reference: [Command reference → cleanup](commands.md#cleanup).

### `add-pc-system` — sync an existing PC system wheel with what's on disk

```bat
:: First time — full bootstrap of a new PC system
spindoctor add-pc-system "PC Games"                                      :: dry-run preview
spindoctor add-pc-system "PC Games" --verbose                            :: dry-run + per-game exe paths, DB status, and INI paths
spindoctor add-pc-system "PC Games" --no-interactive --apply             :: commit (auto-accept all titles)
spindoctor add-pc-system "PC Games" --verbose --no-interactive --apply   :: commit + full per-game detail

:: After installing or uninstalling games — adds new, removes stale (XML + INIs)
:: (this is what the GUI "Add / Refresh Games" button does)
spindoctor add-pc-system "PC Games" --no-menu --no-system-media --no-game-media --no-interactive --apply
spindoctor add-pc-system "PC Games" --no-menu --no-system-media --no-game-media --no-interactive --overwrite-pclauncher --apply  :: also rewrite ALL existing INIs (fixes stale paths + wrong exes)
```

The scanner enforces **one entry per install folder** — if a folder contains both `Game.exe` and `Game Launcher.exe`, only the best candidate is picked. Website `.url` shortcuts and root-level "Launch X" `.lnk` shortcuts are silently dropped.

Re-running on an existing system is fully idempotent: new games are added and uninstalled games are removed from both the HyperSpin XML database and the `Modules/PCLauncher/<system>/` INI folder. `Settings/<system>/Emulators.ini` and `Settings/<system>.ini` are also written (or corrected) with `Default_Emulator=PCLauncher`, `Rom_Path=Modules/PCLauncher/<system>`, and `Rom_Extension=ini`. The dry-run preview shows `would add:` for new games and `would remove (stale):` for games no longer on disk.

`--verbose` adds a per-game breakdown after the title review and PCLauncher INI steps: each game is labelled `new` (not yet in the HyperSpin XML) or `existing` (already present), its resolved executable path is printed, and any DB titles not found in the current ROM scan are flagged as `will be removed`. In the INI step each INI is listed as `would write` / `would skip` (dry-run) or the full written path (apply), and stale INIs are listed under `would delete … stale INI(s)`. Full paths are never truncated.

Reference: [Command reference → add-pc-system](commands.md#add-pc-system).

### `pc-rename` — regenerate PCLauncher INIs only (does not update the wheel XML)

```bat
spindoctor pc-rename "PC Games"                                          :: dry-run preview
spindoctor pc-rename "PC Games" --verbose                                :: show each game's resolved exe + status (full paths, no truncation)
spindoctor pc-rename "PC Games" --apply                                  :: write new / missing PCLauncher INIs
spindoctor pc-rename "PC Games" --overwrite-pclauncher --apply           :: rewrite ALL INIs (fixes stale paths + wrong exes)
```

Use this when you only want to fix or regenerate `.ini` files without changing what appears in the wheel. To add new games to the wheel, use `add-pc-system --no-menu --no-system-media --no-game-media` instead (see above).

Reference: [Command reference → pc-rename](commands.md#pc-rename).

> **GUI:** Games tab → Step 3 (**Add new PC games / refresh the wheel**) — select the PC system using the shared picker at the top, tick **Overwrite existing PCLauncher INIs** if needed, then click **Scan & add new games**.

### `pc-fix-exe` — fix a PC game launching the wrong executable

```bat
spindoctor pc-fix-exe "PC GAMES" "ElecHead"                               :: preview auto-detect
spindoctor pc-fix-exe "PC GAMES" "ElecHead" --apply                       :: auto-detect and fix
spindoctor pc-fix-exe "PC GAMES" "ElecHead" --exe "J:\Games\...\ElecHead.exe" --apply
spindoctor pc-fix-exe "Taito Type X" "Battle Fantasia" --exe "J:\Games\Taito Type X\Battle Fantasia\CleanLaunch.ahk" --apply
spindoctor pc-fix-exe "PC GAMES" "ElecHead" --list-candidates             :: show all candidates ranked
```

Auto-detection scans the game folder and all subfolders. Candidates are ranked: non-excluded `.exe` files first (shallower paths above deeper), then `.ahk` scripts, then `.bat` scripts, then excluded `.exe` files (uninstallers, `vcredist*`, `chromedriver.exe`, `nwjc.exe`, etc.). For NW.js/RPGMaker games, `Game.exe` is selected over `chromedriver.exe`. `.ahk` launchers (e.g. Taito Type X `CleanLaunch.ahk`) now appear in the candidate list automatically.

Reference: [Command reference → pc-fix-exe](commands.md#pc-fix-exe).

> **GUI:** Games tab → Step 4 (**Fix a game that launches the wrong executable**) — select the system and game using the pickers, choose the correct candidate from the ranked list (or Browse…), then click **Apply fix**.

### `game` — list, reorder, or remove games in a wheel

```bat
spindoctor game list --system "Nintendo 64"                           :: games in wheel order
spindoctor game list --system MAME --verbose                          :: full metadata per game

spindoctor game remove --system MAME "1942"                           :: dry-run: show what would be removed
spindoctor game remove --system MAME "1942" --apply                   :: remove from database (ROM untouched)
spindoctor game remove --system MAME "1942" --apply --verbose         :: full metadata + file path
spindoctor game remove --system "PC Games" "Peglin" --remove-pclauncher --apply   :: also delete PCLauncher INI

spindoctor game move --system "Nintendo 64" "Zelda" 1 --apply         :: move to wheel position 1
spindoctor game move-up   --system MAME "1942" --apply                :: shift one slot earlier
spindoctor game move-down --system MAME "1942" --apply                :: shift one slot later

spindoctor game sort --system "Nintendo 64" --apply                   :: A→Z by title (The/A/An stripped)
spindoctor game sort --system MAME --by name --apply                  :: A→Z by ROM filename
spindoctor game sort --system MAME --apply --verbose                  :: print sorted list before saving

spindoctor game save-order --system MAME --order-file order.txt       :: dry-run: show custom order
spindoctor game save-order --system MAME --order-file order.txt --apply :: write custom order to XML
```

All write commands are dry-run without `--apply`. `--output-dir` writes outside the live HyperSpin tree.

> **GUI:** Games tab → Step 1 (**Manage the game wheel**) — shared system picker at the top, then Move Up/Down/Jump to #/Sort/Remove Game/Save Order controls. Tick **Also remove PCLauncher INI** when removing from a PC system.

Reference: [Command reference → game](commands.md#game).

### `ignore` / `match` — taming the matcher

```bat
spindoctor ignore list
spindoctor ignore add "neogeo.zip" --system MAME
spindoctor ignore remove "neogeo.zip" --system MAME

spindoctor match list                            :: cached match decisions
spindoctor match clear --system MAME --yes       :: forget MAME decisions
spindoctor match clear --yes                     :: forget everything
```

Reference: [ignore](commands.md#ignore), [match](commands.md#match).

---

## Metadata & media

ScreenScraper / TheGamesDB pulls.

### `fetch-meta` — download text metadata

```bat
spindoctor fetch-meta --system MAME              :: preview
spindoctor fetch-meta --system MAME --apply
spindoctor fetch-meta --all --apply
spindoctor fetch-meta --system NES --source thegamesdb --apply
spindoctor fetch-meta --all --auto-best --apply  :: skip the ambiguous-match prompt
spindoctor fetch-meta --all --skip-ambiguous --apply  :: same, but log skips for next audit
spindoctor fetch-meta --all --no-cache --apply   :: bypass the 30-day disk cache
```

Reference: [Command reference → fetch-meta](commands.md#fetch-meta).

### `fetch-media` — download wheel art / boxart / videos / etc.

```bat
spindoctor fetch-media --system MAME --apply
spindoctor fetch-media --all --apply
spindoctor fetch-media --all --types wheel,artwork --apply
spindoctor fetch-media --all --pick-media --apply              :: per-slot picker
spindoctor fetch-media --all --skip-ambiguous --apply          :: cron-friendly
spindoctor fetch-media --all --apply --report D:\audit.csv     :: post-fetch audit CSV
```

Reference: [Command reference → fetch-media](commands.md#fetch-media).

### `fetch-steam-media` — Steam Store media for one PC game

```bat
spindoctor fetch-steam-media -s "PC Games" -g "Hades" --steam-id 1145360 --apply
spindoctor fetch-steam-media -s "PC Games" -g "Hades" \
    --steam-id "https://store.steampowered.com/app/1145360/Hades/" --apply
spindoctor fetch-steam-media -s "PC Games" -g "Hades" \
    --steam-id 1145360 --video-index 2 --snap-index 4 --apply        :: non-interactive
spindoctor fetch-steam-media -s "PC Games" -g "Hades" \
    --steam-id 1145360 --types video --apply                          :: just the video
spindoctor fetch-steam-media -s "PC Games" -g "Hades" \
    --steam-id 1145360 --types background --background-index 2 --apply :: 2nd screenshot as background
spindoctor fetch-steam-media -s "PC Games" -g "Hades" \
    --steam-id 1145360 --types wheel --wheel-index 1 --apply          :: header image as wheel art
spindoctor fetch-steam-media -s "PC Games" -g "Hades" \
    --steam-id 1145360 --types video --hls-quality 480p --apply       :: 480p (~10× smaller)
```

No auth required. Use when SS/TGDB don't have media for an obscure PC game. `--types` default is `video,snap,background,artwork`; pass fewer types to skip what you don't need. The `background` slot uses the same screenshot list as `snap` — the first screenshot is written to `Images\Backgrounds\` so it shows as the per-game background in HyperSpin; use `--background-index` to pick a different screenshot. `wheel` must be requested explicitly. Wheel/artwork/snap/background are always saved as `.png` (HyperSpin requirement) — Steam's JPEG source is converted automatically (Pillow) or stored as JPEG-under-.png (works on Windows without Pillow). HLS video candidates show their duration as `M:SS` in the dry-run listing and interactive picker. After download, SpinDoctor prints the file size and duration (`52.3 MB, 1:19`) and warns if the output is under 30 s or 5 MB. Use `--hls-quality 480p` (or `720p`) to select a smaller quality variant — 480p is typically sufficient for arcade cabinet screens and produces files ~10× smaller than the default 1080p.
Reference: [Command reference → fetch-steam-media](commands.md#fetch-steam-media).

### `media-add` / `media-scan` — manual + drift detection

```bat
spindoctor media-add --system MAME --game 1942 --type wheel --file D:\1942-wheel.png          :: dry-run preview
spindoctor media-add --system MAME --game 1942 --type wheel --file D:\1942-wheel.png --apply   :: commit
spindoctor media-scan --all
spindoctor media-scan --system MAME --report D:\media-status.csv
```

Reference: [media-add](commands.md#media-add), [media-scan](commands.md#media-scan).

### `update-db` — sync HyperSpin XML to the ROM folder

```bat
spindoctor update-db --system MAME --apply
spindoctor update-db --all --remove-orphans --apply
spindoctor update-db --system SNES --strip-variant-tags --apply
```

When run with `--all`, a grand total is printed at the end of output (`+N added  −M removed  K already in sync`).

Reference: [Command reference → update-db](commands.md#update-db).

### `generate-config` — bootstrap RocketLauncher per-system configs

```bat
spindoctor generate-config --apply
```

Synthetic wheels (Favorites, Recently Played, Most Played) are never touched by generate-config — their settings are managed by `fav rebuild` / `recent rebuild` / `stats build-wheel`. Any synthetic wheels already in `Main Menu.xml` are preserved across generate-config runs.

On `--apply`, any system INI write failures are repeated as an "Actionable items" section at the very end of output — visible without scrolling back through the per-system table.

Reference: [Command reference → generate-config](commands.md#generate-config).

---

## Backup, diff, migrate

### `backup` — snapshot before risky work

```bat
spindoctor backup create --target E:\Backups               :: preview
spindoctor backup create --target E:\Backups --apply
spindoctor backup list --target E:\Backups
spindoctor backup info --backup E:\Backups\spindoctor-backup-20260101_120000
spindoctor backup restore --backup E:\Backups\spindoctor-backup-20260101_120000 --apply
spindoctor backup restore --backup ... --include databases --apply   :: partial restore

:: Per-file sidecar rollback (undo a single bad edit without restoring the whole library)
spindoctor backup sidecar list "D:\HyperSpin\Databases\Main Menu\Main Menu.xml"
spindoctor backup sidecar restore "D:\...\Main Menu.xml" --from "D:\...\Main Menu.20260519_153045.bak"
spindoctor backup sidecar restore "D:\...\Main Menu.xml" --from "D:\...\Main Menu.20260519_153045.bak" --apply
```

Reference: [Command reference → backup](commands.md#backup).

### `diff` — see what changed since a backup

```bat
spindoctor diff E:\Backups\spindoctor-backup-20260101_120000
spindoctor diff E:\Backups\spindoctor-backup-20260101_120000 --component databases
```

Reference: [Command reference → diff](commands.md#diff).

### `migrate` — move the whole library to a new drive

```bat
spindoctor migrate --target E:\Cab                         :: preview
spindoctor migrate --target E:\Cab --apply                 :: move (default — source removed after verify)
spindoctor migrate --target E:\Cab --keep-source --apply   :: copy, leave source in place
spindoctor migrate --list-manifests
spindoctor migrate --undo latest --apply
```

Reference: [Command reference → migrate](commands.md#migrate).

### `repath-system` — re-prefix game paths after a manual drive change

For systems like **Taito Type X** that were moved to a different drive outside of a full `migrate` run. Updates `Application=` in the PCLauncher system INI and `Rom_Path=` in the RL Emulators INI; all other per-game keys are left untouched. Backs up the system INI before writing.

```bat
spindoctor repath-system "Taito Type X" --rom-path "J:\Games\Taito Type X"          :: preview
spindoctor repath-system "Taito Type X" --rom-path "J:\Games\Taito Type X" --apply  :: commit
```

Games whose paths couldn't be rewritten automatically are listed at the end of output as "Actionable items" with suggested `pc-fix-exe` commands for manual correction.

> **GUI:** Migration tab → Step 6.

Reference: [Command reference → repath-system](commands.md#repath-system).

---

## Custom wheels

Cross-system Favorites / Recently Played / Most Played wheels.

```bat
:: Favorites
spindoctor fav list
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav remove "Super Nintendo" "Chrono Trigger"
spindoctor fav sync                                    :: pull HyperSpin per-system F-key favorites
spindoctor fav sync --verbose                          :: show each console as it is scanned
spindoctor fav rebuild                                 :: dry-run preview
spindoctor fav rebuild --apply
spindoctor fav rebuild --apply --verbose               :: live per-console scan + each media file mirrored
spindoctor fav rebuild --media-mode copy --apply       :: FAT32 thumb drives (no hardlinks)
spindoctor fav clear                                   :: dry-run preview
spindoctor fav clear --apply                           :: empty store + remove Favorites wheel from disk
```

> **GUI:** Tools tab → Step 4 (Manage favorites). Select a system — game dropdown auto-populates from the database. ↻ refreshes the list. Run Step 2 (Favorites checked) to push into HyperSpin.

```bat
:: Recently Played
spindoctor recent list
spindoctor recent rebuild                              :: dry-run preview
spindoctor recent rebuild --apply
spindoctor recent rebuild --apply --verbose            :: print each media file mirrored
spindoctor recent rebuild --limit 10 --apply
spindoctor recent clear                                :: dry-run preview
spindoctor recent clear --apply                        :: remove Recently Played wheel from disk

:: Most Played
spindoctor stats-report build-wheel --limit 25         :: dry-run preview
spindoctor stats-report build-wheel --limit 25 --apply
spindoctor stats-report build-wheel --limit 25 --apply --verbose  :: print each media file mirrored
spindoctor stats-report clear-wheel                    :: dry-run preview
spindoctor stats-report clear-wheel --apply            :: remove Most Played wheel from disk

:: Refresh all three back-to-back
spindoctor fav rebuild --apply && spindoctor recent rebuild --apply && spindoctor stats-report build-wheel --apply
```

> **Note:** `spindoctor-fav`, `spindoctor-recent`, and `spindoctor-stats` console-script aliases are still supported for backwards compatibility — the subcommands above under `spindoctor fav …` / `spindoctor recent …` / `spindoctor stats-report …` are the canonical form.

Reference: [Standalone tools](standalone-tools.md), [fav](commands.md#fav), [recent](commands.md#recent), [stats-report](commands.md#playtime-stats).

### `install-tools` / `uninstall-tools` — wire wheels into HyperSpin

```bat
:: Install .bat helpers into HyperSpin's Tools menu
spindoctor install-tools                               :: write to default HyperLaunch Tools dir
spindoctor install-tools --output-dir D:\Tools
spindoctor install-tools --add-to-system Toolkit       :: add as games in a Toolkit wheel
:: ↑ also writes Modules\PCLauncher\Toolkit.ini (required for PCLauncher to launch)

:: Remove them again
spindoctor uninstall-tools                             :: dry-run preview
spindoctor uninstall-tools --apply
spindoctor uninstall-tools --add-to-system Toolkit     :: dry-run for Toolkit variant
spindoctor uninstall-tools --add-to-system Toolkit --apply
```

Reference: [install-tools](commands.md#install-tools), [uninstall-tools](commands.md#uninstall-tools), [Standalone tools](standalone-tools.md#wiring-into-hyperspin-tools-menu).

---

## Intro Video Randomizer

Manage which videos a third-party boot-time randomizer script picks from (`Random.ini`). Requires `intro_randomizer_dir` to be configured first.

```bat
spindoctor introvideo list                                        :: on disk / registered / size
spindoctor introvideo add "C:\Downloads\Capcom Intro.mp4"         :: dry-run preview
spindoctor introvideo add "C:\Downloads\Capcom Intro.mp4" --apply :: copy + register
spindoctor introvideo remove "Capcom Intro.mp4"                   :: dry-run preview
spindoctor introvideo remove "Capcom Intro.mp4" --apply           :: unregister only — file stays on disk
```

> **GUI:** Intro Video tab — table of every video with on-disk/registered status; **Add video…** (file picker) and **Remove selected** wrap the commands above.

Reference: [introvideo](commands.md#intro-video-randomizer), [Cabinet Architecture Reference → Intro Video Randomizer](cabinet-architecture-reference.md#intro-video-randomizer).

---

## Resetting cabinet data

```bat
:: Preview what would be deleted (safe — nothing touched)
spindoctor scrub

:: Full scrub with built-in backup — backs up then deletes in one step
spindoctor scrub --backup-dir E:\Backups --apply

:: Clear only the favorites store and Favorites wheel
spindoctor scrub --favorites --apply

:: Delete Statistics.ini files + clear Recently Played / Most Played wheels
spindoctor scrub --stats --backup-dir E:\Backups --apply

:: Clear per-system HyperSpin favorites so fav sync starts fresh
spindoctor scrub --hs-favorites --backup-dir E:\Backups --apply

:: Restore from a scrub backup (dry-run first, then commit)
spindoctor scrub-restore E:\Backups\scrub-20260526_143012
spindoctor scrub-restore E:\Backups\scrub-20260526_143012 --apply
```

`--backup-dir` copies affected files to `DIR/scrub-<timestamp>/` before deleting and creates a `manifest.json` index. `scrub-restore` reads that manifest and copies each file back to its original location. `--hs-favorites` clears the F-key favorites HyperSpin writes per console (`<System>_Favorites.ini`, `favorites.txt`, `favorite="1"` in XML) — useful when you want `fav sync` to start from a blank slate. See [Command reference → scrub](commands.md#scrub) for the exact list of files backed up and removed.

Reference: [Command reference → scrub](commands.md#resetting-cabinet-data).

---

## Emulator window-title corrections

```bat
:: List all effective FadeTitle mappings (built-in + user corrections)
spindoctor emulator-title list

:: Add a correction for an emulator whose window title doesn't contain its name
spindoctor emulator-title set "Supermodel" "Supermodel 3"

:: Remove a correction
spindoctor emulator-title remove "Supermodel"
```

Most emulators work automatically — SpinDoctor uses the emulator's registered name as `FadeTitle` by default. Only add a correction when the window title has no overlap with the name. See [Command reference → emulator-title](commands.md#emulator-title).

Reference: [Command reference → emulator-title](commands.md#emulator-title).

---

## Themes & art

### `theme-scan` — inventory frontend controller-glyph art

```bat
spindoctor theme-scan
spindoctor theme-scan --keyword xbox
spindoctor theme-scan --system "Sony Playstation"
spindoctor theme-scan --output D:\theme-inventory.csv
```

Reference: [Command reference → theme-scan](commands.md#theme-scan).

### `theme-apply` — replace controller glyphs with a community pack

```bat
spindoctor theme-apply C:\Packs\PS-Buttons                            :: preview
spindoctor theme-apply C:\Packs\PS-Buttons --apply
spindoctor theme-apply C:\Packs\PS-Buttons --target frontend --apply
spindoctor theme-apply C:\Packs\PS-Buttons --systems "Sony Playstation,Sony Playstation 2" --apply
spindoctor theme-apply --undo latest
spindoctor theme-apply --undo latest --revert-system "Sony Playstation"
spindoctor theme-apply --list-manifests
```

Reference: [Command reference → theme-apply](commands.md#theme-apply).

### `theme-pack-create` — bundle your own pack

```bat
spindoctor theme-pack-create D:\my-pack
spindoctor theme-pack-create D:\my-pack --target frontend
```

Reference: [Command reference → theme-pack-create](commands.md#theme-pack-create).

### `theme-fill` — fill missing per-game theme zips

Installs a blank full-screen theme zip for every game that has a video or background screenshot but no per-game theme zip. Shows background from `Images\Backgrounds\` and overlays the video on top. Existing themes are never overwritten.

```bat
spindoctor theme-fill --system MAME                    :: dry-run: list missing for one console
spindoctor theme-fill --all                            :: dry-run: per-console summary across all systems
spindoctor theme-fill --system MAME --apply            :: write blank themes for MAME
spindoctor theme-fill --all --apply                    :: write blank themes for every system
spindoctor theme-fill --system MAME --default --apply  :: install one console-level default.zip fallback
spindoctor theme-fill --all --default --apply          :: backfill default.zip for every system
spindoctor theme-fill --all --verbose                  :: dry-run with per-game detail, not just counts
```

Reference: [Command reference → theme-fill](commands.md#theme-fill).

---

## LEDBlinky

```bat
:: ── Quick start: Full MAME setup in one step ─────────────────────────────────
:: Chains generate + sync-players. Run once after initial setup, then again
:: whenever you add new MAME ROMs.
spindoctor ledblinky setup                                                :: dry-run preview
spindoctor ledblinky setup --apply                                        :: commit generate + sync-players
spindoctor ledblinky setup --apply --verbose                              :: also show per-step detail
spindoctor ledblinky setup --overwrite --apply                            :: replace all existing entries too

:: ── Step 3a: Generate MAME control + color data (individual step) ─────────────
:: Since 2.4.22: controls.ini uses LedBlinky runtime keys (P1_BUTTON1=1).
:: Since 2.4.21: Colors.ini uses native named format (P1_BUTTON1=Red).
spindoctor ledblinky generate                                             :: dry-run preview
spindoctor ledblinky generate --apply                                     :: commit
spindoctor ledblinky generate --overwrite --apply                         :: replace existing entries (required after upgrading from <=2.4.21)

:: ── Step 3b: Normalize (individual step) ────────────────────────────────────
:: Only needed if you have an older Colors.ini in legacy ledcolor= format.
:: Converts ledcolor1=FF0000 → P1_BUTTON1=Red so LedBlinky can read it.
spindoctor ledblinky colors normalize                                     :: preview
spindoctor ledblinky colors normalize --apply                             :: commit
spindoctor ledblinky colors normalize --apply --verbose                   :: also show per-section key mapping

:: ── Step 3c: Sync player colors (individual step) ────────────────────────────
:: Mirror P1 colors to ALL additional players (P2, P3, P4, …) based on controls.ini.
:: generate only writes P1 keys; sync-players adds P2_BUTTON1=Red, P3_BUTTON1=Red, etc.
:: Only adds keys listed in controls.ini — never overwrites existing keys without --override.
spindoctor ledblinky colors sync-players                                  :: preview
spindoctor ledblinky colors sync-players --apply                          :: commit
spindoctor ledblinky colors sync-players --apply --verbose                :: show each key added per ROM
spindoctor ledblinky colors sync-players --apply --override               :: also replace existing P2+ entries

:: ── Step 4: Fill gaps for non-MAME ROMs ─────────────────────────────────────
spindoctor ledblinky fill-defaults --apply                                                  :: all systems incl. Favorites
spindoctor ledblinky fill-defaults --players 2 --buttons 8 --apply                         :: 2-player, 8 buttons each
spindoctor ledblinky fill-defaults --players 2 --admin-buttons 6 --admin-color Green --apply :: + 6 admin buttons in Green
spindoctor ledblinky fill-defaults --color Purple --apply                                   :: Purple for all unmapped ROMs
spindoctor ledblinky fill-defaults --system "Super Nintendo" --apply                        :: one system only
spindoctor ledblinky fill-defaults --color White --override-uniform --apply                 :: re-color existing uniform entries
spindoctor ledblinky fill-defaults --color White --override-uniform --no-add-keys --apply   :: override values only, don't add new keys
spindoctor ledblinky fill-defaults --apply --verbose                                        :: list each ROM added/overridden/skipped

:: ── Step 5: Randomize — unique color per game ────────────────────────────────
:: Only existing P*_BUTTON*/JOYSTICK/COIN/START keys are updated — dark buttons stay dark.
:: Requires normalized format (Step 3b). If many sections are skipped, run normalize first.
spindoctor ledblinky colors randomize                                     :: preview (dry-run)
spindoctor ledblinky colors randomize --apply                             :: commit fresh shuffle
spindoctor ledblinky colors randomize --seed 42 --apply                   :: reproducible run
spindoctor ledblinky colors randomize --apply --verbose                   :: show per-game colors assigned

:: ── Step 6: Admin/cabinet button overrides ───────────────────────────────────
spindoctor ledblinky admin-buttons set --colors "Red,Blue,Green,White,White,Yellow" --apply   :: per-button
spindoctor ledblinky admin-buttons set --color Green --count 6 --apply                         :: uniform
spindoctor ledblinky admin-buttons set --player 3 --colors "Red,Blue,Green,White,White,Yellow" :: preview
:: (default player=3 for 2-player cabinet; use --player 2 for 1-player cabinet)

:: ── Step 7: Brightness ────────────────────────────────────────────────────────
:: 100% = every color at maximum brightness; dim colors are boosted up
:: 50% = half brightness; 10% = night mode; 0% = all off
spindoctor ledblinky colors brightness --scale 100 --apply               :: maximum brightness
spindoctor ledblinky colors brightness --scale 50  --apply               :: half brightness / dim room
spindoctor ledblinky colors brightness --scale 10  --apply               :: night mode
spindoctor ledblinky colors brightness --scale 75  --verbose             :: preview 75% with per-color before/after

:: ── Step 2: Settings.ini — animation behavior (one-time setup) ───────────────
spindoctor ledblinky patch-settings --apply                                                   :: silence in-game unused-button flash (dark/off)
spindoctor ledblinky patch-settings --game-lwa "Slow Fade.lwa" --apply                       :: play animation on unused buttons instead
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --apply                         :: set FE active animation
spindoctor ledblinky patch-settings --fe-lwa "" --apply                                       :: static colors while browsing
spindoctor ledblinky patch-settings --ss-lwa "Slow Fade.lwa" --apply                         :: set screen saver animation
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --ss-lwa "Slow Fade.lwa" --apply :: set both FE active and screen saver animations
spindoctor ledblinky patch-settings --apply --verbose                                         :: show each key changed with old→new value

:: ── Step 1: Overlay Hook Fix (one-time setup) ────────────────────────────────
:: Fixes HyperSpin Search/Genre/Favorites overlay hang caused by LEDBlinky hooks.
:: Always writes in-place to ledblinky_dir / hyperspin_dir.
spindoctor ledblinky check                                                :: scan only (read-only)
spindoctor ledblinky fix                                                  :: preview
spindoctor ledblinky fix --apply                                          :: commit
spindoctor ledblinky fix --menus Search,Genre,Favorites --apply           :: all overlay menus

:: ── Diagnostic — when colors aren't applying ────────────────────────────────
:: Run this when games still show white/default colors after completing steps above.
:: Reports what's in Colors.ini, controls.ini, LEDBlinkyControls.xml, and MAME
:: listxml for a specific ROM, and tells you what to look for in LEDBlinkyLog.txt.
spindoctor ledblinky inspect-rom 005
spindoctor ledblinky inspect-rom 1942

:: ── Audit / coverage ─────────────────────────────────────────────────────────
spindoctor ledblinky audit
spindoctor ledblinky audit --report D:\ledblinky_audit.csv    :: save CSV (rom, status, coverage flags)

:: ── Color-RGB.ini — named color palette management ───────────────────────────
spindoctor ledblinky colors list
spindoctor ledblinky colors edit Blue                                     :: inspect
spindoctor ledblinky colors edit Blue --name Turquoise --hex 06BEE1 --apply
spindoctor ledblinky colors edit Orange --name Amber --apply              :: rename only

:: ── Backup / restore LEDBlinky files only ────────────────────────────────────
spindoctor backup create --include ledblinky --target D:\Backups --apply
spindoctor backup restore --backup D:\Backups\spindoctor-backup-... --include ledblinky --apply
```

Reference: [Command reference → LEDBlinky](commands.md#ledblinky), [Cabinet architecture → LEDBlinky](cabinet-architecture-reference.md#ledblinky).

---

## Light guns

```bat
spindoctor lightgun detect                                                :: find DemulShooter + Sinden
spindoctor lightgun audit                                                 :: list systems flagged as lightgun
spindoctor lightgun configure --system "Sega Naomi" --apply
spindoctor lightgun configure --system "My System" --target supermodel --apply
```

Reference: [Light guns](lightgun.md), [Command reference → lightgun](commands.md#light-guns).

---

## Config

```bat
spindoctor config show
spindoctor config init                       :: interactive wizard
spindoctor config set roms_dir "D:\Games"
spindoctor config set hyperspin_dir "C:\HyperSpin"
spindoctor config set screenscraper_user your_username
spindoctor config set screenscraper_pass your_password
spindoctor config set thegamesdb_key your_api_key

:: Advanced — override ScreenScraper's per-app developer credential pair.
:: Only needed if HTTP 403 verify failures point at devid (see Troubleshooting).
spindoctor config set screenscraper_devid <your-devid>
spindoctor config set screenscraper_devpassword <your-devpassword>

:: Per-system overrides
spindoctor config system list
spindoctor config system set "Sony Playstation 7" --screenscraper-id 999 --rom-extensions ps7,iso --layout per-game-folder --emulator RPCS7

:: Fix emulator + ROM path for a system SpinDoctor doesn't natively know
spindoctor config system set "Panasonic 3DO"       --emulator RetroArch      --rom-path "J:\Games\3DO"
spindoctor config system set "Daphne"              --emulator Daphne         --rom-path "J:\Games\Daphne"
spindoctor config system set "American Laser Games" --emulator "Daphne Singe" --rom-path "J:\Games\Daphne"
spindoctor config system set "MAME (Vector)"       --rom-path "J:\Games\MAME"
spindoctor config system clear "Sony Playstation 7"

:: Test credentials without saving — useful before committing new values
spindoctor config verify-credentials
spindoctor config verify-credentials --ss-user alice --ss-pass secret
```

Reference: [Configuration](configuration.md).

---

## Tips

- **Always preview first.** Run the command without `--apply` to see what would happen, then re-run with `--apply` to commit. The dry-run output is the exact plan that will be executed.
- **`--undo` exists for almost everything destructive.** Look for "writes a manifest under `~/.spindoctor/<category>/`" in [Command reference](commands.md); those commands all accept `--undo latest --apply` to roll back. The GUI's *File → View logs & manifests…* window has a one-click Undo for any selected run.
- **GUI parity.** Anything on this page works identically from the GUI's [Console tab](gui.md#tab-tour); the dropdown lists the canonical invocations above. Pick → edit `<PLACEHOLDER>` tokens → Run.
- **Output formats.** Most read-only commands accept `--report <path>` or `--format csv|json` so you can dump results to a spreadsheet or pipe to another tool.
- **Long runs are interruptible.** Hitting `Ctrl+C` mid-`backup` / `migrate` / `curate` is safe — the partial manifest survives and the run is replayable / undoable. See [Workflows → Interrupting a long run](workflows.md#recovery-from-mistakes).
- **403 from ScreenScraper or TheGamesDB?** The verify dialog now includes the upstream error body, and every request is logged (with secrets redacted) to `~/.spindoctor/scraper.log`. See [Troubleshooting → 403 from ScreenScraper or TheGamesDB](troubleshooting.md#403-from-screenscraper-or-thegamesdb).

For anything not covered above, start with `spindoctor --help` and drill in with `spindoctor <command> --help`. The full per-command reference is at [Command reference](commands.md).
