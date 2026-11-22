# Files and storage

User state lives in `%USERPROFILE%\.spindoctor\` on Windows, `~/.spindoctor/`
elsewhere. **File → Open ~/.spindoctor** and **View logs & manifests** provide
GUI access. The EXE's folder is not the configuration directory.

## Settings, logs and caches

| Path under `.spindoctor` | Contents / retention |
|---|---|
| `config.json` | Paths, scraper credentials, overrides and GUI preferences; keep private |
| `config.corrupt-*.json` | Rescue copies of invalid configuration; can contain old secrets |
| `favorites.json` | Cross-system favorites; deleting loses the saved list |
| `scraper.log[.1/.2]` | Provider diagnostics, 512 KB rotation with two backups |
| `toolkit.log[.1]` | Cabinet actions and idle tour, 256 KB rotation with one backup |
| `metadata_cache/` | Provider responses, default TTL 30 days; safe to rebuild |
| `match_cache/` | Saved match decisions; deleting re-prompts, does not undo XML edits |
| `media_pick_cache/`, `pc_titles_cache/` | Media/title choices; deleting re-prompts |
| `mame_listxml_cache/` | Shared per-MAME controls dump; safe to regenerate |
| `ledblinky_library/` | Preserved custom/pruned controls and colors, **not disposable cache** |
| `gui.lock` | OS-backed single-instance lock; remaining file after a crash is harmless |

Metadata-cache filenames hash the full source/system/game identity to avoid
sanitized-name collisions. Listxml caches refresh when the MAME binary is newer.
Use `cleanup categories`, `cleanup audit`, then a narrowly scoped cleanup plan.
Do not bulk-delete `.spindoctor` to clear a cache.

## Recovery records

| Directory | Owner |
|---|---|
| `curation/` | Archived region/revision variants |
| `edits/` | Batch metadata edits |
| `renames/` | Rename/clone |
| `migrations/` | Drive migration |
| `media_imports/` | Local media import |
| `themes/` | Theme-swap manifests and overwritten-file backups |
| `tests/` | Launch-test runs and active recovery journal |

Misplaced-file manifests live at the ROM root; restructure manifests live in
the system ROM folder. Snapshot manifests live inside the backup destination.
Keep incomplete manifests until recovery is resolved.
[Undo commands](workflows.md#recovery-from-mistakes).

### Launch-test runs

`tests/<run>/` holds `report.html`, `results.csv/json`, the plan, logs,
screenshots, statistics backup, cleanup report/baseline and recovery journal.
`test_results_dir` overrides the root. Do not delete `active.json` to bypass an
unfinished run: use `spindoctor test --recover`. Remove old runs only after
recovery and retention needs are settled. Screenshots may show the whole monitor.

## Configured destinations

### `output_dir`

Used by supporting commands and saved GUI logs, not every writer. Check each
command's `--output`/`--output-dir` behavior before treating it as staging.

### `backup_dir`

Default snapshot root and supported automatic backup mirror. Some writers leave
timestamped `.bak` files beside originals instead. Inspect `backup sidecar` to
locate/restore individual versions. A sidecar is not a full snapshot.

### `atomic_tmp_dir`

Optional scratch folder for supporting atomic writers. It must share the target
filesystem; otherwise they fall back beside the destination. Per-file replacement
is not a multi-file transaction or a power-loss durability guarantee.

### `auto_audit_export_dir`

Optional automatic post-write audit exports where supported; reports contain
library names and paths.

## Cabinet files

SpinDoctor reads/writes HyperSpin `Databases`, `Media` and selected `Settings`;
RocketLauncher settings, PCLauncher INIs and helper scripts; LEDBlinky
controls/colors/settings; ROMs selected for rename, movement or curation.

Intro pool files live in `intro_randomizer_dir` (retired files in `Disabled`);
swap replaces `intro_video_target`. Generated autorun scripts and Task Scheduler
entries reference your SpinDoctor installation. One-file runtime extraction is
temporary, not library storage.

See [cabinet formats](cabinet-architecture-reference.md) and
[privacy before sharing files](privacy.md).
