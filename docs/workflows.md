# Workflows

Common end-to-end flows. Each one is a recipe — copy, paste, edit paths to match your setup.

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

Schedule the three wheel rebuilds at user log-on so HyperSpin always boots with fresh Favorites / Recently Played / Most Played:

```bat
schtasks /create /sc onlogon /tn "SpinDoctor Wheels" ^
  /tr "cmd /c spindoctor-fav rebuild --apply && spindoctor-recent rebuild --apply && spindoctor-stats build-wheel --apply"
```

Or use `spindoctor install-tools` to write `.bat` files into HyperSpin's Tools menu so the cabinet user can refresh from inside the UI. See [Standalone tools](standalone-tools.md) for the full wiring options.

---

## Weekly maintenance

A periodic sweep that touches everything: integrity, curation, playtime, and a fresh visual snapshot.

```bat
:: 1. Snapshot first so anything below is reversible.
spindoctor backup create --target E:\Backups --label weekly --include settings,databases --apply

:: 2. Health pass.
spindoctor stats
spindoctor doctor --apply
spindoctor find-dupes --all --by-content
spindoctor verify --system NES --dat "C:\Dats\NES.dat"

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

### Scenario A — same drive moves to a new PC

Easiest case. Drive plugs in at the same letters on the new PC.

1. Install Python, then `pip install -e .[all]` from the SpinDoctor source.
2. `spindoctor config init` — point at the existing folders on the moved drive.
3. `spindoctor doctor` to verify.

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

### Things `migrate` does *not* move

Be aware before assuming the new drive / PC is fully wired up:

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

Most also accept `--list-manifests` to show every run on disk.

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

```bat
spindoctor verify --system NES --dat "C:\Dats\Nintendo - NES - No-Intro.dat"
spindoctor verify --system "Sony Playstation" --dat "C:\Dats\Sony - PS - Redump.dat"
```

Each ROM is classified `good` / `renamed` / `bad` / `unknown`. Pass `--show-good` to also list verified-good files; `--match wrapper` for TOSEC-style DATs. See [Command reference → verify](commands.md#verify).

---

## Adding a Favorite

```bat
spindoctor fav add "Super Nintendo" "Chrono Trigger"
spindoctor fav rebuild --apply
```

After this the cabinet user sees Chrono Trigger inside the `Favorites` system in HyperSpin, with its original SNES wheel art and snap mirrored across. The wheel is sorted alphabetically by display title.

To pull HyperSpin's per-system F-key favorites into the cross-system store: `spindoctor fav sync` followed by `spindoctor fav rebuild --apply`.
