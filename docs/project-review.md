# Whole-project review

## Scope and confidence

This review inventoried the package and tests, ran the existing suite, and
used separate correctness, reuse, and efficiency reviews to identify problems.
Verified findings received focused regression tests before or alongside fixes.
A second set of reviews examined the complete implementation patch.
A follow-up pass on the merged stack added the rename-undo recovery,
bulk-matching, and media-inventory work noted below, with no new runtime
dependencies.

This is not a proof of correctness or an exhaustive semantic review of every
line in the large CLI and GUI modules. Tests use temporary libraries and mocked
services. They do not replace testing on a real cabinet.

## Changes implemented

### Backup, migration, and recovery

- Rename/clone, media import, curation, misplaced-ROM moves, migration, and
  restructure now atomically checkpoint each file intent before changing it.
  Records include an interrupted in-flight operation, not just operations that
  returned successfully. Batch-edit snapshots also precede database writes.
  Undo reconciles pending intents with the paths on disk; ambiguous partial
  cross-drive moves retain both paths and the record for investigation.
- Media import backs up overwritten targets beside its manifest and restores
  them on undo. Duplicate target imports are skipped within one run.
- Relocated backups restore from the selected backup, not its old absolute path.
- Backup and migration reject destinations nested inside their source.
  Backup application also validates manually constructed plans.
- Restore rechecks sources before deleting existing destinations.
- Settings backups and restores exclude lock files. Overwrite restores merge
  settings in place, preserving live locks and files absent from the snapshot;
  other components retain their remove-and-replace behavior.
- Migration verification detects missing destination files. The undo manifest
  is written before the final configuration update.
- Migration, restructure, curation, misplaced-ROM, and media-import undo refuse
  occupied original paths and retain unfinished work for retry.
- Rename undo now uses the same occupied-path protection and partial-progress
  persistence. File failures leave the database unchanged; database read/write
  failures retain a database-only retry without replaying completed file work.
- Rename undo restores launcher sections, including in-place
  filename-preserving renames, and rename application rechecks database target
  collisions before moving files.
- Restructure undo also removes completed playlist deletions from its recovery
  record, so retrying cannot delete a subsequently recreated playlist.
- Timestamp collisions no longer overwrite the affected backups or manifests.
  Numbered manifest counters sort numerically, including counters above nine.
- Restructure ignores its own manifests, records interrupted work, and lists
  each physical disc once in playlists, preferring descriptors over raw tracks.

### Media and synthetic wheels

- Owned synthetic-wheel rebuilds refresh changed hardlinks, copies, and theme
  folders. Replacements are staged before switching the destination; ordinary
  mirrors still preserve conflicting targets. Copy comparison checks bytes,
  not just file size and timestamps.
- Favorites and recent-wheel pruning share a bounded traversal that preserves
  retained theme contents, default themes, wheel-click sounds, and letter art.
- Wheel builders and clear operations validate target names and reject source
  collisions. New synthetic databases receive an ownership marker; marked
  custom wheels are excluded from source statistics.
- Media lookup, orphan detection, removal, and rename use the shared
  Windows-safe filename convention. Fade artwork is recognized.
- Rename matches literal ROM stems rather than interpreting glob characters,
  validates the source database before moving files, and preserves custom game
  attributes when renaming or cloning.
- Theme-pack round trips retain system/bucket identity rather than selecting
  another system's identically named asset.
- HTTP partial downloads carry a hashed URL identity and available validators.
  Different candidate URLs cannot share partial bytes. Invalid ranges, changed
  validators, and unknown range totals restart rather than promote bad data.
  Streaming responses are closed, without cleanup errors hiding the result.

### Storage, matching, GUI, and builds

- XML loading rejects duplicate game names (after trimming) before edits can discard
  an entry. Serialized game templates preserve unmodeled children, comments,
  processing instructions, and attributes through rename, clone, undo, and
  synthetic-wheel generation. The stdlib parser also preserves comments and
  processing instructions inside the root. Unchanged field text is retained.
- GUI run history keeps at most 200 records, each retaining at most 256 Ki
  characters and 4,096 fragments. The Output widget keeps at most 1 Mi
  characters and 10,000 lines. Truncated buffers display a notice, including
  in saved logs. A bounded 256-item subprocess queue and 8,192-character reads
  limit backlogs and newline-free output without dropping completion markers.
- Shared unique-temp atomic writes handle short writes and do not let temporary
  file cleanup mask the original failure.
- JSON caches reject malformed shapes while preserving valid empty entries.
  Metadata cache filenames include the full source/system/stem identity hash.
- RocketLauncher path/application edits and lightgun hook edits preserve
  UTF-8, UTF-8 BOM, UTF-16 byte order/BOM, CP1252 text, and existing newlines.
- Cleanup filters categories before scanning and treats misplaced-ROM manifests
  as recovery data, not disposable reports. Partial-download cleanup includes
  identity sidecars, including those left without a partial file.
- Exact normalized matching short-circuits fuzzy scoring. Media imports index
  normalized database names and reuse results across repeated media stems,
  preserving the first-candidate tie rule.
- Bulk fuzzy matching normalizes candidates once and uses SequenceMatcher's
  upper bounds to avoid full scoring when a candidate cannot improve the best
  result. Argument order, thresholds, and first-candidate ties are preserved.
- Audit no longer marks database entries without ROMs as already claimed,
  which previously prevented fuzzy suggestions. A database entry can still
  be claimed only once, with exact matches taking precedence.
- Bulk audit and fetch-media inventory list each media folder once per system,
  then use case-insensitive in-memory lookups. Single-game checks keep direct
  probes. Snapshots are operation-local, not a global cache that could go stale.
- Cleanup safety flags are regression-tested against CLI keys and GUI defaults.
- A cached metadata choice below a newly requested threshold is reconsidered.
- GUI output is batched with a per-tick budget and preserves completion order.
  Backlogs re-arm promptly instead of waiting for the normal idle interval.
  Write-command classification includes theme filling and self-doctor fixes.
- The `cmd`-based Windows build-smoke loops propagate an executable build's
  failure instead of letting a later successful command hide it.

## Simplification and compatibility decisions

- Keep filesystem primitives in `_utils`; serialization and policy stay with
  their callers. `numbered_path_key` composes with existing `unique_path`.
- Keep partial-undo persistence in `_undo`, synthetic-wheel policy in `_wheels`,
  and mirror pruning in `medialink`, rather than generalizing them into one
  unrelated abstraction.
- Keep the encoding-aware INI primitive and compose it with individual edits.
  Read-only diagnostics replace undefined ANSI bytes for printable output;
  editing preserves their original bytes.
- Keep cache-file validation inside `cache`, shared by loading and listing;
  distinguish a valid empty cache from a malformed one.
- Keep existing private filename/atomic helper import aliases for callers.
- Keep `find_best_match` as the existing public entry point and use its shared
  normalized scoring core for bulk consumers. `MediaIndex` stores only names,
  uses the same slot/extension definitions as single-game checks, and is rebuilt
  per operation.
- Keep old metadata cache files readable only when their persisted
  source/system/stem fields prove the requested identity. The old format
  existed before this change.
- Require an ownership marker before replacing an existing custom wheel.
  A PCLauncher folder alone is not proof: real PC game wheels have one too.
  Older unmarked custom wheels are refused rather than risking their contents.
- Preserve Python 3.8 and Windows 7 as supported targets. Syntax checks are
  useful evidence, but are not equivalent to running on that platform.

## Remaining risks and follow-up work

- Multi-file changes are not fully transactional. The checkpointed writers
  above record in-flight work before mutation, but an interrupted cross-drive
  move can leave both source and destination partially populated. Undo refuses
  to guess how to merge them. Other writers and undo checkpoints still cannot
  guarantee recovery across a process crash or a failed checkpoint write.
  Keep an independent backup for these operations.
- Missing undo destinations remain errors requiring investigation. Recovery
  manifests are retained rather than guessing whether files were restored,
  moved elsewhere, or lost.
- Atomic replacement protects against partial writes, but the shared writer
  does not provide an `fsync`-based power-loss durability guarantee.
- `move_no_replace` rejects an already occupied destination, but its precheck
  and move are not one concurrency-atomic operation. Do not run competing
  filesystem writers against the same library.
- Synthetic-wheel media refreshes on rebuild, not immediately when a source
  changes. Interrupted theme-folder replacement can leave a staging directory;
  rebuilding regenerates the derived target.
- XML preservation is structural, not byte-identical. Formatting, declarations,
  and header dates can change. The stdlib parser does not retain document-level
  comments outside the root or doctypes; lxml remains recommended.
- Preview media lookup uses the shared Windows-safe filename stem. LEDBlinky,
  lightgun, PCLauncher-module and preview writes that edit existing files keep
  their encoding, BOM, line endings, undefined ANSI bytes and unrelated lines,
  and write atomically. Whole-file generators (for example `emit_ini`) still
  write their own fresh layout.
- `backup sidecar list/restore` (and the GUI picker that calls it) finds both
  `<stem>.<stamp>.bak` and LEDBlinky's `<name>.<stamp>.bak` backups, beside
  the file and in `backup_dir`'s HyperSpin, RocketLauncher and LEDBlinky
  folders, ordered by stamp and numeric counter. HyperSpin and LEDBlinky
  central folders are flat, so two different files with the same name share
  one list there; check the path before restoring.
- LEDBlinky raw section edits keep comment banners between sections when the
  section before them is pruned or replaced. Spacing around newly inserted
  sections can still change; use the file backup for byte-identical reversal.
- Cleanup category safety flags still have duplicated declarations across the
  category reports, CLI keys, and GUI defaults, now pinned by a regression
  test. Synthetic-wheel names share one declaration.
- GUI retained output is bounded and saved logs contain the retained tail,
  not a full stream after truncation. Large wheel-table refreshes and the size
  of the CLI/GUI modules remain refactoring candidates.
- HTTP servers without validators cannot provide strong same-resource proof
  across interrupted requests, even when the URL matches.
- No live scraping, cabinet hardware, Windows 7 runtime, or power-loss
  validation was performed. Python 3.8 runtime and frozen-executable builds are
  covered by CI only (see Validation).

## Validation

### Continuous integration

GitHub Actions passed every check on PRs #509–#512 and on the follow-up fixes
pushed to them: tests on Ubuntu with Python 3.8 and 3.12 and on Windows with
Python 3.12, Ruff, the legacy and modern PyInstaller frozen-build smoke tests,
Bandit, and the pip-audit dependency scan. The legacy build and the 3.8 tests
are the evidence for Python 3.8 compatibility; neither runs on Windows 7 or on
cabinet hardware.

### Storage consistency follow-up

`tests/test_storage_consistency.py` covers settings, color, hook, profile and
XML edits in UTF-8, UTF-8 with BOM, ANSI (including undefined bytes), and
UTF-16 LE/BE files; atomic-write failure; LEDBlinky comment banners around
pruned and replaced sections; Windows-safe preview names; and sidecar discovery
across both backup name styles and the configured backup folders. The full
suite passed on Windows 10 and Python 3.14.0 with Ruff and `git diff --check`.

### Recorded-risk follow-up

Regression coverage includes write-ahead intent checks before and after
interrupted filesystem moves, failed checkpoint writes, database-save failure,
a child process exiting during media import, overwrite restoration, both XML
parsers, custom-wheel rebuild refreshes, stale hardlinks/copies with unchanged
size and timestamp, failed mirror staging, and GUI character/fragment/line
limits and completion ordering. These are synthetic and fault-injection tests,
not cabinet or power-loss validation.

Validated on Windows 10 and Python 3.14.0: **2,089 non-GUI tests and 176 GUI
tests passed (2,265 total), with 7 skipped** (four need unavailable `ffprobe`;
three test non-Windows guards). The forced stdlib XML test emits the expected
fallback warning. Ruff, the single-Unreleased changelog check,
`git diff --check`, and the Python 3.8 grammar scan (180 files) passed.
Python 3.8/Windows 7 runtimes and frozen builds were not tested.

### PR integration follow-up

The PR review added regressions and fixes for sanitized clone-name collisions
and legacy clone undo, config sharing violations, lightgun hook line endings,
damaged UTF-16 diagnostics, legacy Windows relative-path overlap checks,
numeric backup ordering, real PCLauncher wheel ownership, and community
theme-pack layouts. Tests now redirect the home directory before package
imports, rather than relying on every fixture to patch every per-user path.

The combined tree with the documentation PR and LEDBlinky library/prune PR
passed **1,947 non-GUI tests and 172 GUI tests, with 7 skipped** on Windows 10
and Python 3.13. Ruff, the single-Unreleased changelog check, and
`git diff --check` passed. Changed Python sources passed the Python 3.8
grammar/API scan (the only API hit was `copytree(dirs_exist_ok=...)`, which
Python 3.8 supports). This did not run the CI matrix or frozen builds locally.

### Review follow-up validation

The rebased follow-up branch (`refactor/review-followup`, on top of `e6130c2`)
passed **2,052 non-GUI tests and 172 GUI tests (2,224 total), with 7 skipped**
on Windows 10 and Python 3.14.0. Ruff, `git diff --check`, and the Python 3.8
grammar scan (178 files) passed. On a 1,000-game synthetic library, bulk fuzzy
matching ran 5.3x faster and bulk media inventory 69.8x faster than the
previous implementation, with identical outputs.

### Original stack validation

Validated on Windows 10 with an isolated Python 3.13.7 environment:

| Check | Result |
| --- | --- |
| Non-GUI suite, four workers | 1,876 passed, 7 skipped |
| GUI suite, serial | 172 passed |
| Combined | **2,048 passed, 7 skipped** |
| Ruff | Passed |
| `git diff --check` | Passed |
| Python 3.8 grammar parsing | 166 Python files passed |

The initial baseline was 1,856 passed and 7 skipped. Main advanced during PR
preparation; the final stack was reapplied to `d77b839` and revalidated on
2026-11-04, including the newly merged upstream tests. The audit adds 76 passing
test cases. Four skips require unavailable `ffprobe`; three exercise
non-Windows guards and are intentionally skipped on Windows.

Test commands, using the isolated environment's Python:

```text
python -m pytest -q -n 4 --ignore=tests/test_gui.py --tb=short -rs
python -m pytest -q tests/test_gui.py --tb=short
python -m ruff check .
git diff --check
```

The Python 3.8 check parses package, test, and script files with
`ast.parse(..., feature_version=(3, 8))`. It is a grammar check, not runtime
or dependency validation on Python 3.8.
