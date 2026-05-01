# Troubleshooting

Common problems and their fixes. For deeper recovery (rolling back a migration, restoring an XML, reversing a curate), see [Workflows → Recovery](workflows.md#recovery-from-mistakes).

## Install / startup

### `spindoctor: command not found`

The console scripts didn't end up on PATH. Re-run `pip install -e .` from the repo root and confirm Python's `Scripts\` directory is on your `Path` environment variable. As a fallback, `python -m spindoctor.cli ...` works without the entry point.

If you're using the prebuilt Windows binaries (no Python install), make sure the folder containing `spindoctor.exe` is on `PATH`, or invoke by full path (`C:\spindoctor\spindoctor.exe systems`).

### Windows 7: "The procedure entry point ... could not be located in api-ms-win-core-..."

The `.exe` was built against a Windows SDK newer than Win 7 supports. The official binaries ship from a Python 3.8.10 + PyInstaller 5.x build environment specifically to avoid this — that pairing (not the runner OS) is what keeps the bootloader Win 7-compatible. If you self-built and hit this, downgrade your build environment to those versions — see [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md). Also confirm your Win 7 install has Service Pack 1 — the RTM (un-patched) release isn't supported.

### Windows SmartScreen blocks the .exe

Releases aren't code-signed yet, so Windows 10/11 may flag the binaries as unrecognised. Click **More info** → **Run anyway**. (Code signing is on the roadmap.)

### `config init` rejects a path

Folders must exist before they can be configured. Create the folder first, then re-run.

### `spindoctor systems` shows `Database: ✗` next to a folder

That system has ROMs but no HyperSpin database yet. Run `spindoctor add-system "<exact folder name>"` to bootstrap it (dry-run first; re-run with `--apply`).

### `add-system` reports "no ROMs found, drop ROMs in and re-run"

Either the ROM folder is empty, or the file extensions aren't in SpinDoctor's recognized set for that system. Either drop ROMs in or teach SpinDoctor about a custom extension:

```bat
spindoctor config system set "<System>" --rom-extensions ext1,ext2
```

See [Configuration → Per-system overrides](configuration.md#per-system-overrides).

## Metadata / scraping

### ScreenScraper rate-limiting

SpinDoctor caps itself at 1 request/second. The free tier allows 500/day — wait until midnight UTC or upgrade your account.

### Wrong metadata picked during `fetch-meta`

```bat
spindoctor match clear --system MAME
spindoctor fetch-meta --system MAME --apply
```

Cached match decisions live at `~/.spindoctor/match_cache/<system>.json`; clearing them only resets the cached choice — the previous XML edits aren't rolled back. To undo the writes too, restore the `.bak` next to the XML or use `git diff` if your library is under version control.

### ROM filenames have region tags like `(USA)` — will they match?

Yes — region/version/revision tags are stripped before searching. Ambiguous matches prompt with a review link to the metadata source. See [ROM variant handling](commands.md#rom-variant-handling).

## Wheels

### Can I edit favorites from inside HyperSpin?

HyperSpin's built-in F-key writes per-system favorite lists. Run `spindoctor fav sync` to merge those into the cross-system Favorites store, then `spindoctor fav rebuild --apply`. For explicit add/remove, use `spindoctor-fav add` / `remove`.

### Does favoriting a game double its disk usage?

No — by default media is hardlinked from the source system into `Media/Favorites/`. Both pathnames point at the same bytes on NTFS. Pass `--media-mode copy` if you're on a filesystem that doesn't support hardlinks (FAT32, exFAT). See [Configuration → Filesystem considerations](configuration.md#filesystem-considerations).

### How is "Most Played" different from "Recently Played"?

Both read the same RocketLauncher `Statistics.ini` files. **Recently Played** sorts by `Last_Played` and shows the last N games launched. **Most Played** sorts by `Total_Time_Played` and shows where you've actually spent the most hours. Build it with `spindoctor stats-report build-wheel --apply`.

### How do I get cross-system "Recently Played" working?

Automatic — `spindoctor recent rebuild --apply` reads RocketLauncher's `Statistics.ini` files (which RocketLauncher writes on every game launch). Schedule it at log-on or run from the Tools menu — see [Standalone tools](standalone-tools.md).

## Light guns

### `spindoctor lightgun detect` reports "DemulShooter not found"

DemulShooter must be on disk somewhere spindoctor scans. The auto-detected roots are `<HyperSpin>/Tools`, `<RocketLauncher>/Modules`, `<RocketLauncher>/Plugins`, `<emulators_dir>`, plus `Program Files` and the Start Menu. If yours lives elsewhere:

```bat
spindoctor config set demulshooter_path "C:\arcade\DemulShooter\DemulShooter.exe"
spindoctor lightgun detect
```

### `lightgun configure` says "No DemulShooter target known for system"

The system name doesn't match any auto-target rule (MAME, Naomi, Atomiswave, Dreamcast, Model 2, Model 3, Flycast, ChiHiro, Triforce, Lindbergh, …). Pass the target explicitly:

```bat
spindoctor lightgun configure --system "My System" --target supermodel --apply
```

See DemulShooter's own readme for the full list of `-target` values.

### After `lightgun configure --apply`, the gun does nothing in-game

Three usual causes:

1. **DemulShooter never started.** Run `spindoctor lightgun audit` and confirm `Pre_Launch_App` is wired. If it is, launch the game from RocketLauncher's command line directly — RL prints the pre/post-launch app output, so any error will surface there.
2. **Wrong target for that emulator.** A Naomi game running under Flycast needs `-target flycast`, not `-target demul07a`. Re-run `lightgun configure --system <name> --target flycast --apply`.
3. **The Sinden software isn't running.** DemulShooter expects an active Sinden Lightgun instance. Start the Sinden software (or set it to autostart on boot) before launching games.

### DemulShooter stays running after the emulator exits

`Post_Launch_App` is missing or wrong. Re-run `lightgun configure --system <name> --apply` — it always (re)writes the standard `taskkill /IM "DemulShooter.exe" /F` post-launch hook.

### How do I revert lightgun wiring for a system?

Open `RocketLauncher\Settings\<System>.ini` in any editor and delete the `Pre_Launch_App` and `Post_Launch_App` lines, then set `"lightgun": false` under the system in `~/.spindoctor/config.json` (or run `spindoctor lightgun audit` to confirm the change took).

## Cross-system search

### How do I find a game when I'm not sure which system has it?

```bat
spindoctor find-global "metal slug"
spindoctor find-global "Pac-Man" --exact
```

Searches every configured system's HyperSpin database. Substring match by default; `--exact` for a single best hit.

## Auditing other tools

### How do I list every arcade utility installed alongside spindoctor?

```bat
spindoctor tools-audit
```

Read-only. Scans `<HyperSpin>/Tools`, `<RocketLauncher>/Modules`, the emulators tree, Program Files, and the Start Menu for ~25 known tools (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, HyperT00ls, Don's HyperTools, Hypersearch, Sinden, DemulShooter, XPadder, JoyToKey, DS4Windows, XOutput, …) and reports which spindoctor command replaces each one.

Add `--extra-path "C:\custom-tools"` for non-standard install locations. Pass `--show-unknown` to list `.exe` files the registry doesn't recognise — useful for telling the project what to add next.

## LEDBlinky

### HyperSpin's Search menu crashes when LEDBlinky is enabled

Known issue with LEDBlinky's per-menu hooks. Diagnose and patch:

```bat
spindoctor ledblinky check
spindoctor ledblinky fix             :: dry-run preview
spindoctor ledblinky fix --apply     :: commit the patch
```

The fix is reversible — `.bak` files are written and disabled lines are commented out (not deleted) and tagged.

## Migration / drives

### After a migration, wheel art is missing

Run `spindoctor doctor` to see which paths failed validation. If you migrated with `--keep-source` and later removed the originals, restore the missing component from a `backup`. Hardcoded absolute paths inside HyperSpin XML are not rewritten by `migrate` (rare in practice — most XMLs reference games by name, not path).

### Drive letter changed after restoring a backup

```bat
spindoctor backup restore --backup E:\Backups\... --use-current-paths --apply
```

`--use-current-paths` writes restored files to whatever paths `config.json` currently has, instead of where the backup originally came from.

### My new drive is FAT32 / exFAT and the wheel rebuild is slow

`fav rebuild` and `stats-report build-wheel` default to hardlinks, which need NTFS / ext4 / APFS. On FAT32 / exFAT they fall back to copy automatically (via `auto` mode), which doubles disk use. Either pass `--media-mode copy` explicitly to make the fallback intentional, or move the wheel target to an NTFS volume.

## General

### Will SpinDoctor overwrite my data?

Every XML write makes a `.YYYYMMDD_HHMMSS.bak` first (toggle via `backup_before_modify`). Use `--output-dir` to write to a staging folder. For larger snapshots, use [`spindoctor backup create`](workflows.md#backup--restore).

### Does it work with RocketUI?

Yes — RocketUI uses the same HyperSpin `Databases/` and `Media/` structure.

### Recovering from any apply

Almost every destructive command writes a manifest under `~/.spindoctor/<category>/` and supports `--undo`. Full recovery flows and the manifest map live at [Workflows → Recovery](workflows.md#recovery-from-mistakes).
