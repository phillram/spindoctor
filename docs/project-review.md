# Whole-project review

## Scope and confidence

This review inventoried the package and tests, ran the existing suite, and
used separate correctness, reuse, and efficiency reviews to identify problems.
Verified findings received focused regression tests before or alongside fixes.
A second set of reviews examined the complete implementation patch.

This is not a proof of correctness or an exhaustive semantic review of every
line in the large CLI and GUI modules. Tests use temporary libraries and mocked
services. They do not replace testing on a real cabinet.

## Changes implemented

### Backup, migration, and recovery

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
- Restructure undo also removes completed playlist deletions from its recovery
  record, so retrying cannot delete a subsequently recreated playlist.
- Timestamp collisions no longer overwrite the affected backups or manifests.
  Numbered manifest counters sort numerically, including counters above nine.
- Restructure ignores its own manifests, records interrupted work, and lists
  each physical disc once in playlists, preferring descriptors over raw tracks.

### Media and synthetic wheels

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
- Keep old metadata cache files readable only when their persisted
  source/system/stem fields prove the requested identity. The old format
  existed before this change.
- Require an ownership marker before replacing an existing custom wheel.
  A PCLauncher folder alone is not proof: real PC game wheels have one too.
  Older unmarked custom wheels are refused rather than risking their contents.
- Preserve Python 3.8 and Windows 7 as supported targets. Syntax checks are
  useful evidence, but are not equivalent to running on that platform.

## Remaining risks and follow-up work

- Multi-file rename/import and several other writers are not fully
  transactional. Some failures or interruptions can leave partial changes
  without a complete recovery record. Rename undo has not received the shared
  partial-success treatment. Keep an independent backup for these operations.
- Missing undo destinations remain errors requiring investigation. Recovery
  manifests are retained rather than guessing whether files were restored,
  moved elsewhere, or lost.
- Atomic replacement protects against partial writes, but the shared writer
  does not provide an `fsync`-based power-loss durability guarantee.
- `move_no_replace` rejects an already occupied destination, but its precheck
  and move are not one concurrency-atomic operation. Do not run competing
  filesystem writers against the same library.
- Synthetic-wheel hardlinks/copies can remain stale after a source file is
  replaced. Ownership markers do not solve synchronization.
- Duplicate XML game-name handling and preservation of unmodeled child
  elements still need deeper review.
- Not every preview/media path or LEDBlinky/lightgun/CLI text writer was
  converted to the shared normalization and lossless-writing helpers.
- Centralized sidecar-backup discovery and LEDBlinky backup-name handling need
  a separate cross-CLI/GUI consistency pass.
- LEDBlinky raw section boundaries attach trailing comments to the preceding
  section. Pruning can remove those comment banners, and restoring sections
  can normalize boundary spacing. Use the file backup for byte-identical
  reversal, rather than relying on library regeneration for that guarantee.
- Cleanup category safety flags and default synthetic-wheel names still have
  duplicated declarations. They agree today; consolidation is deferred.
- GUI run records and output widgets remain unbounded. Large wheel-table
  refreshes and the size of the CLI/GUI modules remain refactoring candidates.
- HTTP servers without validators cannot provide strong same-resource proof
  across interrupted requests, even when the URL matches.
- No live scraping, hardware integration, frozen-executable build, Python 3.8
  runtime, or Windows 7 runtime validation was performed.

## Validation

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
