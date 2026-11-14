# Software architecture

This is the package map for contributors. For HyperSpin/RocketLauncher file formats
and hardware examples, use the separate [example cabinet reference](cabinet-architecture-reference.md).
For user-facing behavior, start with the [command reference](commands.md).

## Entry points and data flow

```text
Tkinter GUI (gui.py) ── subprocess arguments ──┐
                                             v
Terminal ────────────────────────────────> Click CLI (cli.py)
                                             |
Standalone wheel wrappers ───────────────┐    |
                                        v    v
                                   Domain modules
                                        |
                    Config, databases, ROMs, media and external services
```

- `cli.py` defines the Click command groups, options, progress and summaries. It
  coordinates domain operations and applies command-specific dry-run rules.
- `gui.py` builds forms and invokes CLI/standalone commands as subprocesses. It
  also reads configuration and library data directly to populate controls.
  Noninteractive flags prevent subprocesses from waiting on terminal input.
- `scripts/` contains source-checkout shims and Windows wrappers. The standalone
  Favorites, Recent and Stats entry points reuse domain functions rather than
  maintaining separate wheel-building implementations.

Favorites and the ranked Recent/Most Played builders share the wheel writer in
`favorites._write_synthetic_wheel`. Callers retain their selection, validation,
dry-run and ordering policies. The writer receives the caller's summary and
source-database cache, and writes replacements before pruning orphan media or
launchers. Keep this ordering when changing the common pipeline.

Both interfaces share `~/.spindoctor/config.json`. There is no background service
or database server. Long-lived caches must not be confused with an operation's
temporary view of the filesystem.

## Module boundaries

| Area | Main modules | Responsibility |
|---|---|---|
| Configuration and discovery | `config`, `database`, `rl_rom_paths`, `rocketlauncher` | Config validation, XML records, RocketLauncher settings and ROM lookup |
| Library inspection | `audit`, `fileinfo`, `lint`, `health`, `self_doctor`, `verify` | ROM/database/media comparisons, cabinet checks and integrity reports |
| Metadata and downloads | `scraper`, `matcher`, `media`, `media_scan` | Provider clients, cached match decisions, downloads and local media import |
| Game and wheel editing | `edit`, `mainmenu`, `wheel_start`, `organize`, `curate`, `misplaced`, `orphan_media` | Metadata edits, ordering, where wheels start, ROM moves and cleanup |
| Synthetic wheels | `favorites`, `recent`, `playtime`, `medialink` | Favorites/Recent/Most Played composition and mirrored media |
| Backup and migration | `backup`, `migrate`, `cleanup` | Snapshots, relocation, restoration and cleanup policies |
| Hardware and frontend integration | `ledblinky`, `ledblinky_library`, `ledblinky_profiles`, `lightgun`, `rl_user_functions`, `introvideo`, `autostart` | Lighting, gun hooks, User Functions inspection and startup integration |
| Assets and previews | `themes`, `preview`, `lwax`, `lwax_patterns` | Theme operations, previews and unsigned LED animation generation |

Helpers stay narrow:

- `_utils` owns shared filesystem primitives, Windows-safe filename stems,
  unique-path counters and byte formatting.
- `_undo` persists unfinished recovery work for consumers that use it.
- `_wheels` validates synthetic targets and tracks ownership markers.
- `_net` constructs HTTP sessions; `_compat` holds platform compatibility helpers.
- `_errors` translates OS errors, and `_singleton` provides the GUI lock.

Keep domain policy with the owning module, not in a generic helper simply because
two functions look similar.

## Matching and filesystem snapshots

`romutils.find_best_match` is the public fuzzy-matching entry point. Bulk consumers
can reuse its normalized scoring core without changing score direction or
first-candidate tie behavior.

`audit.MediaIndex` takes a per-system media snapshot for bulk operations.
Single-game checks probe directly. Rebuild snapshots between operations so a
download or edit is visible on the next run.

Metadata cache filenames include a hash of the complete source/system/ROM identity.
The LEDBlinky library is different: it preserves pruned custom entries and is not
a disposable response cache. See [Storage locations](spindoctor-files.md).

## Write and recovery boundaries

Dry-run is a command policy, not a property of every domain function. Cabinet
writers generally require `--apply`; settings/list commands can save immediately.
Follow the owning command's existing convention when adding a caller.

The shared atomic writer creates a unique temporary file on the destination's
filesystem and replaces one file only after its bytes are written. This does not
make a multi-file operation transactional or guarantee power-loss durability.
`move_no_replace` checks for occupied destinations, but is not a concurrency-atomic
reservation. Do not run competing writers against one library.

Some operations create sidecar backups, others write manifests, and permanent
deletion modes have no undo. Partial-undo consumers retain unfinished work after
recoverable errors. Normal interrupts, abrupt process termination and failed
checkpoint writes are different failure cases. See
[Recovery from mistakes](workflows.md#recovery-from-mistakes) and the dated
[project review](project-review.md#remaining-risks-and-follow-up-work).

Existing custom synthetic-wheel targets require `.spindoctor-synthetic` ownership
evidence; a PCLauncher directory alone is not proof that SpinDoctor may replace a
real game wheel.

## Compatibility and validation

Python 3.8 and Windows 7 remain supported targets. Avoid newer syntax and APIs,
and retain encoding-aware handling for legacy Windows INIs. macOS/Linux testing
does not validate cabinet hardware or Windows-only behavior.

Run focused tests for changed modules, then the appropriate broader checks from
the repository root. The `dev` extra does not include `pytest-xdist` (for
`-n 4`) or Ruff; install them first with `python -m pip install pytest-xdist ruff`:

```text
python -m pytest -q -n 4 --ignore=tests/test_gui.py --tb=short -rs
python -m pytest -q tests/test_gui.py --tb=short
python -m ruff check .
git diff --check
```

See [Windows builds](../build/README.md) for frozen-executable validation.
Never put real credentials, user configurations or unreviewed cabinet logs into
tests or documentation; follow [Privacy and sharing diagnostics](privacy.md).
