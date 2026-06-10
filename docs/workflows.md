# Workflows

Common end-to-end flows. Each one is a recipe — copy, paste, edit paths to match your setup.

**Where to start:**

- Standing up a brand-new cabinet? Jump to [New cabinet build](#new-cabinet-build) (then [Adding your first system](#adding-your-first-system)).
- Already running, looking for daily / weekly maintenance? [Daily wheel refresh](#daily-wheel-refresh) and [Weekly maintenance](#weekly-maintenance).
- Need to undo something? Skip straight to [Recovery from mistakes](#recovery-from-mistakes) — every destructive command writes a manifest, almost everything is reversible.
- One-off task (backup, drive migration, finding a game, replacing controller glyphs, wiring a lightgun)? Pick from the ToC below.

## Contents

- [New cabinet build](#new-cabinet-build)
- [Adding your first system](#adding-your-first-system)
- [Daily wheel refresh](#daily-wheel-refresh)
- [Weekly maintenance](#weekly-maintenance)
- [Backup & restore](#backup--restore)
- [Migration](#migration)
- [Recovery from mistakes](#recovery-from-mistakes)
- [ROM integrity sweep](#rom-integrity-sweep)
- [Adding a Favorite](#adding-a-favorite)
- [Searching across systems](#searching-across-systems)
- [Auditing legacy arcade tools](#auditing-legacy-arcade-tools)
- [Replacing controller-glyph art](#replacing-controller-glyph-art)
- [Wiring light guns](#wiring-light-guns)

---

## New cabinet build

End-to-end first-time bring-up. Stages everything to a side folder so you can review before copying in. See [First-time setup](setup.md) for the prerequisite OS / HyperSpin / emulator install.

```bat
spindoctor config init
spindoctor systems
spindoctor generate-config                                                 :: preview
spindoctor generate-config --output-dir D:\SpinDoctorOutput --apply
spindoctor update-db --all --output-dir D:\SpinDoctorOutput --apply
spindoctor fetch-meta --all --output-dir D:\SpinDoctorOutput --apply
spindoctor fetch-media --all --types wheel,background ^
    --output-dir D:\SpinDoctorOutput --apply
```

Once `D:\SpinDoctorOutput` looks right, copy its contents over your live `hyperspin_dir` (or re-run without `--output-dir` to write in place — every XML write leaves a `.bak`).

---

## Adding your first system

> **GUI alternative:** the **Systems** tab wraps `add-system`, `add-pc-system`, and `pc-rename` with a system-name field, optional skip-media toggles, and a dry-run-by-default Apply checkbox.

You've got ROMs in `C:\Games\Nintendo Entertainment System\` but the cabinet doesn't show NES yet. Walk:

```bat
spindoctor systems
:: → "Nintendo Entertainment System"  Database: ✗

spindoctor add-system "Nintendo Entertainment System"
:: dry-run output:
::   would add Main Menu entry
::   would create Databases/Nintendo Entertainment System/
::   would scaffold Media/Nintendo Entertainment System/
::   would create 142 game stubs from ROMs
::   would fetch system-level wheel art

spindoctor add-system "Nintendo Entertainment System" --apply
:: walks the metadata + media fetch flow interactively

spindoctor generate-config --apply
spindoctor doctor
```

For PC / Windows / Steam libraries replace `add-system` with `add-pc-system` — it scans nested folders and prompts a title-picker.

If `add-system` reports "no ROMs found", the file extension isn't in SpinDoctor's recognized set for that system. See [Configuration → Per-system overrides](configuration.md#per-system-overrides).

---

## Daily wheel refresh

Three integration patterns, in roughly increasing order of "how invisible to the cabinet user":

1. **From inside HyperSpin** (HyperHQ → Tools menu, or as games inside an existing wheel) — GUI Tools tab → "Install for HyperHQ → Tools menu" *or* "Install into an existing wheel system" (e.g. a `Toolkit` wheel). CLI equivalents: `spindoctor install-tools` and `spindoctor install-tools --add-to-system Toolkit`. See [Standalone tools → Wiring into HyperSpin Tools menu](standalone-tools.md#wiring-into-hyperspin-tools-menu).
2. **Auto-refresh on cabinet startup** — GUI Tools tab → "Auto-refresh on cabinet startup" → Schedule auto-refresh (Windows-only — wraps `schtasks.exe`, Schedule / Remove / Check Status buttons). Configurable post-log-on delay so HyperSpin / RocketLauncher settle before the rebuild kicks in.
3. **Manual `schtasks` (Windows)** if you'd rather skip the GUI — see [Standalone tools → Wiring into Windows startup](standalone-tools.md#wiring-into-windows-startup) for the `schtasks /create` invocation, plus the macOS (`launchd` / `crontab @reboot`) and Linux (`systemd --user` / `crontab`) equivalents.

---

## Weekly maintenance

A periodic sweep that touches everything: integrity, curation, playtime, and a fresh visual snapshot.

> **GUI alternative:** the **Diagnostics** tab in `spindoctor-gui` surfaces every read-only check in this section as a one-click button — `find-dupes`, `find-misplaced`, `find-orphan-media`, `check-discs`, `lint`, `report`, `preview`, `stats`, plus a Global Search box and a Verify-against-DAT mini-form. Snapshot first via the **Backup & Restore** tab.

```bat
:: 1. Snapshot first so anything below is reversible.
spindoctor backup create --target E:\Backups --label weekly --include settings,databases --apply

:: 2. Health pass.
spindoctor stats
spindoctor doctor --apply
spindoctor find-dupes --all --by-content
spindoctor verify --system NES --dat "C:\Dats\NES.dat"
spindoctor tools-audit             :: re-inventory third-party utilities (read-only)
spindoctor lightgun audit          :: confirm DemulShooter wiring still intact (lightgun cabs only)

:: 3. Thin out duplicates by region preference (archives losers, fully reversible).
spindoctor curate --all
spindoctor curate --system NES --apply

:: 4. Refresh playtime stats and the Most Played wheel.
spindoctor stats-report
spindoctor stats-report build-wheel --limit 25 --apply
spindoctor recent rebuild --apply
spindoctor fav rebuild --apply

:: 5. Generate a visual contact sheet so you can spot missing/wrong art at a glance.
spindoctor preview --all --output-dir D:\Preview --open
```

---

## Backup & restore

Backups copy any combination of library components into a dated folder on a different drive. They're plain folders — you can browse, copy, or zip them with any file explorer — with a `manifest.json` describing what was copied and where it came from.

> **GUI alternative:** the **Backup & Restore** tab in `spindoctor-gui` covers all four subcommands (create / list / info / restore) with per-component checkboxes, dry-run-by-default, and a separate restore panel with `--use-current-paths` and `--overwrite` toggles.

### Quick reference

| Component | What it covers |
|---|---|
| `roms` (alias `games`) | `roms_dir` |
| `databases` (alias `db`) | `<hyperspin_dir>/Databases/` |
| `media` | `<hyperspin_dir>/Media/` |
| `hyperspin` (alias `hs`) | composite — `databases,media` |
| `emulators` | `emulators_dir` |
| `rocketlauncher` (alias `rl`) | `rocketlauncher_dir` |
| `ledblinky` (alias `led`) | `ledblinky_dir` |
| `settings` (alias `config`) | `~/.spindoctor/` (config, favorites, ignore lists, caches) |
| `all` | every component above |

### Common flows

```bat
:: Full backup (everything)
spindoctor backup create --target E:\Backups --apply

:: Just the small stuff (settings + databases — no huge media folder)
spindoctor backup create --target E:\Backups --include settings,databases --apply

:: Tag a backup before doing something risky
spindoctor backup create --target E:\Backups --label pre-migration --apply

:: Inspect what's there
spindoctor backup list --target E:\Backups
spindoctor backup info --backup E:\Backups\spindoctor-backup-20260428_120000

:: Restore everything
spindoctor backup restore --backup E:\Backups\spindoctor-backup-20260428_120000 --apply

:: Restore just settings (e.g. after a fresh install on a new PC)
spindoctor backup restore --backup E:\Backups\... --include settings --apply

:: Drive letters changed? Restore to whatever paths config.json now has.
spindoctor backup restore --backup E:\Backups\... --use-current-paths --apply

:: Clobber non-empty target folders (default refuses)
spindoctor backup restore --backup E:\Backups\... --overwrite --apply
```

The pre-flight plan reports total bytes to copy and free space at the target, and aborts the apply if there isn't enough room.

### When to back up what

- **Before any `migrate` or large `fetch-meta`/`fetch-media` run** — `--label pre-<thing>` so you can find it later.
- **Weekly** — `--include settings,databases` is small and fast (no media), captures everything that's hard to regenerate.
- **Monthly or before drive swaps** — `--include all` to a separate physical drive.

---

## Migration

`migrate` moves the entire library — or specific components — to a new drive in one shot, then updates `config.json` so the next command finds everything. See [Command reference → migrate](commands.md#migrate) for all flags.

> **GUI alternative:** the **Migrate** tab in `spindoctor-gui` wraps every flag and exposes a separate Undo panel that pre-fills `latest` and surfaces `--list-manifests` — useful when you want to roll back a migration without scrolling through `~/.spindoctor/migrations/`.

### Scenario A — same drive moves to a new PC

Easiest case. Drive plugs in at the same letters on the new PC.

1. Install SpinDoctor on the new PC — either `pip install -e .[all]` from a checkout, or extract the [Windows binaries zip](windows-binaries.md) if you'd rather skip Python entirely.
2. Run the configuration wizard: `spindoctor-gui` → Setup tab → Save (or `spindoctor config init` from `cmd.exe`). Point at the existing folders on the moved drive.
3. `spindoctor doctor` (or the **Diagnostics** tab in the GUI) to verify.

No data move needed.

### Scenario B — copy everything to a fresh PC (network or external drive)

`migrate` only moves files between drives within one PC, so use `backup` to bridge.

**On the old PC:** snapshot to an external drive.

```bat
spindoctor backup create --target E:\Backups --label cabinet-move --include all --apply
```

**On the new PC:**

1. Do steps 1–8 of [First-time setup](setup.md) — Python, HyperSpin, RocketLauncher, emulators, BIOS, SpinDoctor itself. **Don't drop in ROMs yet** — the restore brings them.
2. Run `spindoctor config init` and point at where you *want* things on the new PC. Folders need to exist; create empty ones first.
3. Restore, rerouting paths to match the new PC's config:

   ```bat
   spindoctor backup restore ^
       --backup E:\Backups\spindoctor-backup-YYYYMMDD_HHMMSS-cabinet-move ^
       --use-current-paths --apply
   ```

   `--use-current-paths` writes restored files to whatever paths `config.json` currently has — drive letters and folder names can differ from the old PC.
4. `spindoctor doctor` to verify.

### Scenario C — moving to a new drive on the same PC

The `migrate` command's bread and butter.

```bat
:: 1. Plug in the new drive (e.g. E:) and dry-run the plan.
spindoctor migrate --target E:\Cab

:: 2. (Recommended) Copy first, verify hashes, keep the originals as a fallback.
spindoctor migrate --target E:\Cab --apply --keep-source --verify

:: 3. Smoke-test from the new drive.
spindoctor config set roms_dir E:\Cab\Games
spindoctor config set hyperspin_dir E:\Cab\HyperSpin
spindoctor config set emulators_dir E:\Cab\Emulators
spindoctor config set rocketlauncher_dir E:\Cab\RocketLauncher
spindoctor doctor

:: 4. Once happy, delete the old folders by hand.
::    Or skip 2-3 and do a one-shot move that updates config automatically:
spindoctor migrate --target E:\Cab --apply

:: To keep original folder names (e.g. D:\MyArcade\GameFiles stays "GameFiles"):
spindoctor migrate --target E:\Cab --apply --preserve-names
```

If something goes wrong: `spindoctor migrate --undo latest` puts everything back and restores the previous config.

### Moving only your ROMs to a new drive

The most common single-component migration — moving `D:\Arcade\Games` to `J:\Games` while leaving HyperSpin and RocketLauncher in place:

```bat
:: 1. Dry-run to confirm the plan.
spindoctor migrate --target J:\ --include roms

:: 2. Move and update SpinDoctor's roms_dir automatically.
spindoctor migrate --target J:\ --include roms --apply

:: 3. Regenerate RocketLauncher's per-system INIs with the new Rom_Path.
::    Each Settings\<SystemName>.ini is rewritten to point at J:\Games\<system>.
spindoctor generate-config --apply
```

GUI path: **Migrate tab** → set Target root to `J:\`, untick everything except `roms`, tick Apply, click **Run migration**. When it finishes, go to **Metadata & Media tab** → tick Apply → click **Run generate-config**.

> **Why the extra step?** `migrate` moves files and updates SpinDoctor's own `config.json`, but RocketLauncher keeps its own per-system settings at `<RocketLauncher>\Settings\<SystemName>.ini`. Each of those files contains a hardcoded `Rom_Path=D:\Arcade\Games\<SystemName>`. `generate-config --apply` rewrites them all in one shot with the new path. Without this step RocketLauncher can't find your games and HyperSpin will show an empty wheel.

### Already moved your ROMs manually (without using migrate)

If you moved your games folder yourself — dragged it in Explorer, used robocopy, etc. — and didn't use `spindoctor migrate`, you just need two commands:

```bat
:: 1. Tell SpinDoctor where the games now live.
spindoctor config set roms_dir J:\Games

:: 2. Rewrite RocketLauncher's per-system INIs to match.
spindoctor generate-config --apply
```

GUI path: **Setup tab** → update the "ROMs directory" field and click Save. Then **Metadata & Media tab** → tick Apply → click **Run generate-config**.

`generate-config --apply` writes `<RocketLauncher>\Settings\<SystemName>.ini` for every system configured in SpinDoctor with the updated `Rom_Path`. HyperSpin and RocketLauncher can find your games immediately after.

> **No undo for generate-config?** `generate-config` rewrites plain text INI files. It does not create `.bak` sidecar files. If you need to roll back: re-run `generate-config --apply` after correcting `roms_dir`, or restore your RocketLauncher `Settings\` folder from a `spindoctor backup`.

### Things `migrate` does *not* move

Be aware before assuming the new drive / PC is fully wired up:

- **RocketLauncher per-system INIs (`Settings\<SystemName>.ini`).** Each file hardcodes `Rom_Path`. After migrating the `roms` component, run `spindoctor generate-config --apply` (or GUI: Metadata & Media tab → Run generate-config) to rewrite them with the new path. Without this step RocketLauncher can't find any games.
- **Emulator-internal paths.** RetroArch's `retroarch.cfg`, PCSX2's INI, Dolphin's user folder, etc. often hardcode absolute paths to BIOS, save folders, or shaders. SpinDoctor moves the emulator's files but does not rewrite those internal configs. Re-test each emulator and adjust.
- **BIOS files outside `emulators_dir`.** Only included if they live under `<emulators_dir>` and you `--include emulators`.
- **Hardcoded paths inside HyperSpin XML.** SpinDoctor preserves `<game>` content verbatim. If a previous tool wrote absolute Windows paths into the XML, those are not rewritten.
- **API credentials.** Live in `~/.spindoctor/config.json` — covered by `backup --include settings` (or `all`). Make sure your backup includes settings or you'll re-enter them on the new PC.

---

## Recovery from mistakes

Almost everything SpinDoctor writes is reversible. The mechanics:

### `.bak` files (XML round-trips)

Every XML write leaves a `.YYYYMMDD_HHMMSS.bak` next to the original. Toggle via `backup_before_modify` (default `true`). To restore, copy the `.bak` over the live file. To clear old `.bak`s once you're confident: `spindoctor cleanup run --include db-backups --keep-recent 5 --apply`.

### Manifests + `--undo`

Every destructive command writes a JSON manifest to `~/.spindoctor/<category>/`. Re-running the same command with `--undo` reverses the most recent run.

| Command | Manifest dir | Undo flag |
|---|---|---|
| `migrate` | `~/.spindoctor/migrations/` | `--undo latest` or `--undo <path>` |
| `backup create` | `<target>/spindoctor-backup-…/manifest.json` | n/a — restore via `backup restore` |
| `find-misplaced --apply` | `~/.spindoctor/misplaced/` | `--undo` |
| `organize --restructure --apply` | `~/.spindoctor/restructure/` | `--undo` |
| `curate --apply --action archive` | `~/.spindoctor/curation/` | `--undo` |
| `media-scan --apply` | `~/.spindoctor/media_imports/` | `--undo` |
| `batch-edit --apply` | `~/.spindoctor/edits/` | `--undo <path>` |
| `rename` / `clone --apply` | `~/.spindoctor/renames/` | `--undo <path>` |
| `theme-apply --apply` | `~/.spindoctor/themes/theme-apply-<stamp>/manifest.json` | `--undo latest` or `--undo <path>` |

Most also accept `--list-manifests` to show every run on disk.

> **GUI alternative:** **`File → View logs & manifests…`** in `spindoctor-gui` lists every manifest above (categorised, newest first) and has an **Undo this run** button that runs the matching `--undo` command for the selected row. For commands that always reverse the most recent run (curate, media-scan), the button warns you if you pick an older row so you don't accidentally reverse the wrong one.

`curate --action delete` is permanent (no manifest). `find-orphan-media --apply` is permanent (prompts first).

### Common recovery patterns

**Wrong metadata picked during `fetch-meta`:**

```bat
spindoctor match clear --system MAME
spindoctor fetch-meta --system MAME --apply
```

The cached match decision is cleared; previous XML edits are not rolled back. Restore an XML `.bak` if you need to undo the writes too.

**Restoring a corrupted XML:**

```bat
:: Find the most recent backup
dir "<hyperspin_dir>\Databases\MAME\*.bak"

:: Roll back
copy "<hyperspin_dir>\Databases\MAME\MAME.20260428_120000.xml.bak" ^
     "<hyperspin_dir>\Databases\MAME\MAME.xml"
```

**Migrate went wrong:**

```bat
spindoctor migrate --undo latest
```

Files move back, config snapshot restores. For `--keep-source` migrations, undo just removes the copied destinations (originals were never touched).

**Lost a Favorite mid-rebuild:** the store is in `~/.spindoctor/favorites.json` — open it in any editor.

---

## ROM integrity sweep

> **GUI alternative:** the **Diagnostics** tab has a Verify-against-DAT mini-form (System + DAT-path picker + Verify button) and a Global Search box for finding a title across every database without typing the command.

```bat
spindoctor verify --system NES --dat "C:\Dats\Nintendo - NES - No-Intro.dat"
spindoctor verify --system "Sony Playstation" --dat "C:\Dats\Sony - PS - Redump.dat"
```

Each ROM is classified `good` / `renamed` / `bad` / `unknown`. Pass `--show-good` to also list verified-good files; `--match wrapper` for TOSEC-style DATs. See [Command reference → verify](commands.md#verify).

---

## Adding a Favorite

> **GUI alternative:** the **Tools** tab (Steps 1–3) covers the full favorites lifecycle: **Step 1** refreshes the Favorites wheel, **Step 2** registers it in the Main Menu, **Step 3** (Manage favorites) has inline Add / Remove / List buttons. Install-Tools helpers and auto-refresh scheduling are in the same tab. CLI remains the fastest path for scripted or batch adds.

```bat
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav rebuild --apply
```

After this the cabinet user sees Chrono Trigger inside the `Favorites` system in HyperSpin, with its original SNES wheel art and snap mirrored across. The wheel is sorted alphabetically by display title.

To pull HyperSpin's per-system F-key favorites into the cross-system store: `spindoctor fav sync` followed by `spindoctor fav rebuild --apply`.

---

## Searching across systems

Find every system that has a given title — replaces standalone Hypersearch utilities.

```bat
spindoctor find-global "house of the dead"
:: → MAME           hotd       House of the Dead
::   Sega Naomi     hotd2      House of the Dead 2
::   Sega Dreamcast hotd2dc    House of the Dead 2 (Dreamcast)

spindoctor find-global "Pac-Man" --exact
spindoctor find-global "1942" --limit 10
```

`--exact` matches only when the query equals the entry name or description (case-insensitive). Otherwise substring. `--limit` caps results per system (default 50).

---

## Auditing legacy arcade tools

A typical HyperSpin cabinet accumulates 20+ third-party utilities over time — Tur-RemoveDupes, FatMatch, FuzzyRename 3, HyperSync, HyperT00ls, Don's HyperTools, the CUE Renamer, Hypersearch, plus drivers and mappers (XPadder, JoyToKey, DS4Windows, XOutput) and lightgun gear (Sinden, DemulShooter, Arcade Guns).

```bat
spindoctor tools-audit
```

The report groups everything found by category and lists which spindoctor command replaces each one (or notes "no spindoctor equivalent" for drivers and mappers that should stay installed). Read-only — never uninstalls anything.

```bat
spindoctor tools-audit --extra-path "C:\arcade-utils"     :: include a custom location
spindoctor tools-audit --show-unknown                     :: list .exe files we don't recognise
```

Use `--show-unknown` when you've installed something not in the registry — paste the list into a spindoctor issue and the registry can grow. Once you've confirmed each replacement command works on your library (most often `audit`, `find-dupes`, `verify`, `fetch-meta`, `fetch-media`, `rename`), the listed ROM/media tools are safe to uninstall by hand. See [Standalone tools → Tools audit](standalone-tools.md#tools-audit--what-other-arcade-utilities-does-this-cabinet-already-have).

---

## Replacing controller-glyph art

The Xbox glyphs at the bottom of the HyperSpin frontend annoying you on a PlayStation-themed cabinet? Or want arcade button hints instead? SpinDoctor swaps overlay PNGs for any community pack with full undo support.

> **GUI alternative:** **`File → Browse HyperSpin themes…`** opens a sortable inventory; the **Apply replacement pack…** button on that window opens a Plan/Apply window that wraps the same flow.

```bat
:: 1. See what's currently on disk — narrow with --keyword to find
::    "the Xbox glyphs" before guessing which file to swap.
spindoctor theme-scan --keyword xbox
spindoctor theme-scan --keyword controller --output D:\theme_audit.csv

:: 2. Drop a community pack folder (PNGs/JPGs with the same filenames
::    your cabinet uses) onto disk, then dry-run to preview the swaps.
spindoctor theme-apply C:\Packs\PS-Buttons

:: 3. Commit. Every overwritten file is backed up first.
spindoctor theme-apply C:\Packs\PS-Buttons --apply

:: 4. Don't like it? Reverse the most recent run.
spindoctor theme-apply --undo latest
```

`--target` narrows the swap pool: `frontend` (only `Media/Frontend/Images`), a system name (only that system's Special A/B), or the default `all`. If `theme-scan` returns no results but the cabinet clearly *has* glyphs at the bottom of the screen, those glyphs likely live inside a Flash `.swf` in `Media/Main Menu/Themes/default.zip` — SpinDoctor can't edit SWFs (they need a Flash authoring tool). The `theme-scan` report flags this case at the bottom.

Reversibility: each applied run writes `~/.spindoctor/themes/theme-apply-<timestamp>/manifest.json` plus a `backup/` mirror of every overwritten file. Undo via the CLI (`theme-apply --undo latest|<path>`) or the GUI's Logs & Manifests viewer (Theme swaps category → Undo this run).

---

## Wiring light guns

For cabinets with Sinden (or compatible) light guns + DemulShooter. Full walkthrough at [Light guns](lightgun.md).

> **GUI alternative:** the **Lightgun** tab in `spindoctor-gui` has buttons for Detect (with optional `--apply`), Audit, and Configure (with optional `--target` / extra-args overrides) — so most cabinet owners never need to type these commands by hand.

```bat
:: 1. Confirm the gear is installed.
spindoctor lightgun detect

:: 2. Pull any pre-wired systems into spindoctor config.
spindoctor lightgun detect --apply

:: 3. Wire a new system.
spindoctor lightgun configure --system "Sega Naomi"             :: dry-run preview
spindoctor lightgun configure --system "Sega Naomi" --apply

:: 4. Periodically check that wiring is still intact (also part of weekly maintenance).
spindoctor lightgun audit
```

Auto-targeted systems include MAME, Sega Naomi/Atomiswave/Dreamcast, Model 2, Model 3 (Supermodel), Flycast, ChiHiro, Triforce, Lindbergh. Pass `--target <name>` to override for anything else.

The wiring lives in `RocketLauncher\Settings\<System>.ini` as `Pre_Launch_App` (start DemulShooter) and `Post_Launch_App` (taskkill DemulShooter on exit). Module `.ahk` files are never modified, so a stock Tur build remains intact.
