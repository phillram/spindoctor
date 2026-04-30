# Troubleshooting

Common problems and their fixes. For deeper recovery (rolling back a migration, restoring an XML, reversing a curate), see [Workflows → Recovery](workflows.md#recovery-from-mistakes).

## Install / startup

### `spindoctor: command not found`

The console scripts didn't end up on PATH. Re-run `pip install -e .` from the repo root and confirm Python's `Scripts\` directory is on your `Path` environment variable. As a fallback, `python -m spindoctor.cli ...` works without the entry point.

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
