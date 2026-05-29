# CLI cheatsheet

Quick, copy-paste-friendly index of the most-used SpinDoctor commands, grouped by intent. Each section names the command, what it's for, the canonical invocation, and the flags you'll reach for most often.

> **Looking for every flag?** This page is the fast index. The full reference — every command, every flag, every edge case — lives at [Command reference](commands.md). The deep cross-links below jump straight to the relevant section there.

> **Don't want to type any of this?** The GUI's [Custom Command tab](gui.md#tab-tour) has all of these in a curated dropdown (~70 presets). Pick, edit the `<PLACEHOLDER>` tokens, click Run.

> **Dry-run by default.** Commands that modify files preview their plan unless invoked with `--apply`. Most destructive commands also write a manifest under `~/.spindoctor/` and accept `--undo` to roll back. See [Recovery from mistakes](workflows.md#recovery-from-mistakes).

## Contents

- [Discover & diagnose](#discover--diagnose)
- [Edit & curate](#edit--curate)
- [Metadata & media](#metadata--media)
- [Backup, diff, migrate](#backup-diff-migrate)
- [Custom wheels](#custom-wheels)
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
```

Reference: [Command reference → tools-audit](commands.md#tools-audit).

### `doctor` — self-diagnose paths, binaries, DB integrity

Validates `config.json`, walks `roms_dir` / `hyperspin_dir`, probes scraper credentials, checks for orphan databases. Run after any config change.

```bat
spindoctor doctor
spindoctor doctor --verbose      :: include passing checks too
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
spindoctor verify --system NES --dat path\to.dat --report D:\verify.csv
```

Reference: [Command reference → verify](commands.md#verify).

### `find-global` — search every system for a game

```bat
spindoctor find-global "house of the dead"
spindoctor find-global zelda --fuzzy
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
spindoctor rename "Sony Playstation" "Final Fantasy VII" "Final Fantasy 7" --apply
spindoctor clone  "Sony Playstation" "Resident Evil"     "Resident Evil (clone)" --apply
```

Reference: [rename](commands.md#rename), [clone](commands.md#clone).

### `curate` — region / revision thinning

Picks the canonical ROM per game from a multi-version dump (USA / Europe / Japan / World / rev0 / rev1 / …) and archives or deletes the rest.

```bat
spindoctor curate --all                         :: preview only
spindoctor curate --all --regions USA,World     :: regional preference
spindoctor curate --all --revision newest       :: prefer the latest rev
spindoctor curate --all --action archive --apply
spindoctor curate --all --action delete --apply :: DESTRUCTIVE, no undo
spindoctor curate --undo latest --apply         :: roll back the last archive run
```

Reference: [Command reference → curate](commands.md#curate).

### `cleanup` — safe-cache + lifecycle housekeeping

```bat
spindoctor cleanup categories         :: list disk-space hogs SpinDoctor manages
spindoctor cleanup audit              :: same in summary form
spindoctor cleanup run --apply
```

Reference: [Command reference → cleanup](commands.md#cleanup).

### `ignore` / `match` — taming the matcher

```bat
spindoctor ignore list
spindoctor ignore add --system MAME --rom "neogeo.zip"
spindoctor ignore remove --system MAME --rom "neogeo.zip"

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
spindoctor fetch-media --all --pick-media --apply       :: per-slot picker
spindoctor fetch-media --all --skip-ambiguous --apply   :: cron-friendly
```

Reference: [Command reference → fetch-media](commands.md#fetch-media).

### `media-add` / `media-scan` — manual + drift detection

```bat
spindoctor media-add --system MAME --game 1942 --type wheel --file D:\1942-wheel.png
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

Reference: [Command reference → update-db](commands.md#update-db).

### `generate-config` — bootstrap RocketLauncher per-system configs

```bat
spindoctor generate-config --apply
```

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
spindoctor migrate --target E:\Cab                  :: preview
spindoctor migrate --target E:\Cab --apply          :: COPY, keep source
spindoctor migrate --target E:\Cab --move --apply   :: DESTRUCTIVE move
spindoctor migrate --list-manifests
spindoctor migrate --undo latest --apply
```

Reference: [Command reference → migrate](commands.md#migrate).

---

## Custom wheels

Cross-system Favorites / Recently Played / Most Played wheels.

```bat
:: Favorites
spindoctor fav list
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav remove "Super Nintendo" "Chrono Trigger"
spindoctor fav sync                                    :: pull HyperSpin per-system F-key favorites
spindoctor fav rebuild                                 :: dry-run preview
spindoctor fav rebuild --apply
spindoctor fav rebuild --media-mode copy --apply       :: FAT32 thumb drives (no hardlinks)
spindoctor fav clear                                   :: dry-run preview
spindoctor fav clear --apply                           :: empty store + remove Favorites wheel from disk

:: Recently Played
spindoctor recent list
spindoctor recent rebuild                              :: dry-run preview
spindoctor recent rebuild --apply
spindoctor recent rebuild --limit 10 --apply
spindoctor recent clear                                :: dry-run preview
spindoctor recent clear --apply                        :: remove Recently Played wheel from disk

:: Most Played
spindoctor stats-report build-wheel --limit 25         :: dry-run preview
spindoctor stats-report build-wheel --limit 25 --apply
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

:: Remove them again
spindoctor uninstall-tools                             :: dry-run preview
spindoctor uninstall-tools --apply
spindoctor uninstall-tools --add-to-system Toolkit     :: dry-run for Toolkit variant
spindoctor uninstall-tools --add-to-system Toolkit --apply
```

Reference: [install-tools](commands.md#install-tools), [uninstall-tools](commands.md#uninstall-tools), [Standalone tools](standalone-tools.md#hyperspin-tools-menu).

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

---

## LEDBlinky

```bat
:: Generate controls.ini + colors.ini from MAME -listxml (local, no quota)
spindoctor ledblinky generate                                             :: dry-run preview
spindoctor ledblinky generate --apply                                     :: commit
spindoctor ledblinky generate --overwrite --apply                         :: replace community entries too

:: Audit coverage — which ROMs have / lack control data
spindoctor ledblinky audit

:: Fix HyperSpin Search/Genre/Favorites overlay crash caused by LEDBlinky hooks
spindoctor ledblinky check
spindoctor ledblinky fix --apply

:: Patch Settings.ini — silence unused-button flash + improve idle animation
spindoctor ledblinky patch-settings                                               :: preview
spindoctor ledblinky patch-settings --apply                                       :: silence in-game unused-button flash (dark/off)
spindoctor ledblinky patch-settings --game-lwa "lwa\Slow Fade.lwa" --apply       :: play animation on unused buttons instead
spindoctor ledblinky patch-settings --fe-lwa "lwa\Slow Fade.lwa" --apply         :: swap idle animation too
spindoctor ledblinky patch-settings --fe-lwa "" --apply                           :: static colors while browsing

:: Fill default Colors.ini entries for ROMs with no LED mapping (console games, synthetic wheels)
spindoctor ledblinky fill-defaults                                                          :: preview
spindoctor ledblinky fill-defaults --apply                                                  :: commit (all systems incl. Favorites)
spindoctor ledblinky fill-defaults --players 2 --buttons 8 --apply                         :: 2-player, 8 buttons each
spindoctor ledblinky fill-defaults --players 2 --admin-buttons 6 --admin-color Green --apply :: + 6 admin buttons in Green
spindoctor ledblinky fill-defaults --color Purple --apply                                   :: Purple for all unmapped ROMs
spindoctor ledblinky fill-defaults --system "Super Nintendo" --apply                        :: one system only
spindoctor ledblinky fill-defaults --color White --override-uniform --apply                 :: re-color existing uniform entries
spindoctor ledblinky fill-defaults --color White --override-uniform --no-add-keys --apply   :: override values only, don't add new keys

:: Color-RGB.ini — rename/recolor named colors and propagate throughout
spindoctor ledblinky colors list
spindoctor ledblinky colors edit Blue                                     :: inspect
spindoctor ledblinky colors edit Blue --name Turquoise --hex 06BEE1 --apply
spindoctor ledblinky colors edit Orange --name Amber --apply              :: rename only

:: Normalize hex-format Colors.ini entries to named format (run before rename)
spindoctor ledblinky colors normalize                                     :: preview
spindoctor ledblinky colors normalize --apply                             :: commit

:: Set uniform brightness for all colors (normalizes to max first, then scales)
:: 100% = every color at maximum brightness; dim colors are boosted up
:: 50% = half brightness; 10% = night mode; 0% = all off
spindoctor ledblinky colors brightness --scale 100 --apply               :: maximum brightness
spindoctor ledblinky colors brightness --scale 50  --apply               :: half brightness / dim room
spindoctor ledblinky colors brightness --scale 10  --apply               :: night mode
spindoctor ledblinky colors brightness --scale 75                        :: preview 75% (dry-run)

:: Set fixed per-button admin/cabinet button colors across ALL Colors.ini sections
spindoctor ledblinky admin-buttons set --colors "Red,Blue,Green,White,White,Yellow" --apply   :: per-button
spindoctor ledblinky admin-buttons set --color Green --count 6 --apply                         :: uniform
spindoctor ledblinky admin-buttons set --player 3 --colors "Red,Blue,Green,White,White,Yellow" :: preview
:: (default player=3 for 2-player cabinet; use --player 2 for 1-player cabinet)

:: Backup / restore LEDBlinky files only
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
spindoctor config system clear "Sony Playstation 7"
```

Reference: [Configuration](configuration.md).

---

## Tips

- **Always preview first.** Run the command without `--apply` to see what would happen, then re-run with `--apply` to commit. The dry-run output is the exact plan that will be executed.
- **`--undo` exists for almost everything destructive.** Look for "writes a manifest under `~/.spindoctor/<category>/`" in [Command reference](commands.md); those commands all accept `--undo latest --apply` to roll back. The GUI's *File → View logs & manifests…* window has a one-click Undo for any selected run.
- **GUI parity.** Anything on this page works identically from the GUI's [Custom Command tab](gui.md#tab-tour); the dropdown lists ~70 of the canonical invocations above. Pick → edit `<PLACEHOLDER>` tokens → Run.
- **Output formats.** Most read-only commands accept `--report <path>` or `--format csv|json` so you can dump results to a spreadsheet or pipe to another tool.
- **Long runs are interruptible.** Hitting `Ctrl+C` mid-`backup` / `migrate` / `curate` is safe — the partial manifest survives and the run is replayable / undoable. See [Workflows → Interrupting a long run](workflows.md#recovery-from-mistakes).
- **403 from ScreenScraper or TheGamesDB?** The verify dialog now includes the upstream error body, and every request is logged (with secrets redacted) to `~/.spindoctor/scraper.log`. See [Troubleshooting → 403 from ScreenScraper or TheGamesDB](troubleshooting.md#403-from-screenscraper-or-thegamesdb).

For anything not covered above, start with `spindoctor --help` and drill in with `spindoctor <command> --help`. The full per-command reference is at [Command reference](commands.md).
