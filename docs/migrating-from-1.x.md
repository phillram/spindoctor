# Migrating from SpinDoctor 1.x

Short answer: **nothing breaks**. SpinDoctor 2.0 is a non-breaking polish release for existing cabinets — every CLI command, flag, config key, and on-disk manifest behaves the same as in 1.9.x. Drop the new binaries in place of the old ones (or `pip install -U` on a source install) and you're done. Your `config.json`, favorites, ignore lists, cached scraper responses, and per-run manifests under `~/.spindoctor/` are all preserved.

This page documents the *visible* differences so 1.x muscle memory transfers cleanly.

## What changed for end users

### GUI is the primary surface

The 2.0 cycle leaned hard on the GUI. The README, [setup walkthrough](setup.md), and [installation guide](installation.md) now lead with the GUI, with CLI listed as the equivalent "power user" path. If you've been a CLI-first cabinet owner, **nothing forces you to change** — the CLI is still the canonical surface and every GUI button shells out to it. The reordering is a signpost for new cabinet owners landing cold on the docs.

A new canonical GUI walkthrough lives at [`docs/gui.md`](gui.md). Previously the tab tour lived inside `docs/windows-binaries.md`, which made sense for binary users but read awkwardly for pip / source installs. `gui.md` is platform-neutral.

### Tab order in the GUI

Tabs have been reordered into workflow sequence — setup first, then read-only diagnostics, then curation, then composition, then peripherals, then infrastructure, then logs / custom:

```
Setup → Audit & Doctor → Diagnose → Metadata & Media → Curate →
Wheels → Main Menu → Systems → LEDBlinky → Lightgun →
Backup & Restore → Tools → Migrate → Logs → Custom Command
```

If you have muscle memory for the old order, the keyboard shortcut `Ctrl+1`…`Ctrl+9` still jumps to the Nth tab — just the Nth has changed.

### First-run wizard

A 3-step modal (Welcome → pick `roms_dir` + `hyperspin_dir` → run `doctor`) opens automatically on a fresh cabinet, or any time the GUI detects placeholder defaults in `config.json`. The wizard sets a new `first_run_complete` flag so it never auto-opens again. Existing 1.x installs with a valid config silently flip the flag on first launch of the 2.0 GUI — you won't see it unless you re-open it manually via **Help → First-run setup…**.

### New GUI config keys

Three new keys in `config.json`:

| Key | Default | Purpose |
|---|---|---|
| `first_run_complete` | `false` → flipped to `true` on 2.0 first launch | Suppresses the auto-opening first-run wizard. |
| `gui_window_geometry` | unset | Last `WIDTHxHEIGHT+X+Y` the GUI window was at when it closed. Restored on the next launch. |
| `gui_last_active_tab` | unset | Index of the tab that was open the last time the GUI closed. Restored on the next launch. |

All three are managed by the GUI; hand-editing them is fine but not necessary. Delete any of them to reset that piece of state. See [Configuration → Most-used keys](configuration.md#most-used-keys) for full descriptions.

### New GUI affordances

None of these change existing behaviour — they're additive:

- **Per-tab health badges** (⚠/✗) next to tab names whose area `doctor` flagged.
- **Find bar** above the Output panel — `Ctrl+F` to open.
- **System quick-filter** — `Ctrl+Shift+F` to narrow every system combobox across every tab.
- **Drag-and-drop** — drop a folder from Explorer / Finder onto any Setup path field to fill it.
- **Multi-system `fetch-meta` selector** — refresh a hand-picked subset of systems in one click from the Metadata & Media tab.
- **Per-system overrides form** on the Systems tab — surfaces `config system set` as a form instead of CLI flags.
- **Preflight check** button on Audit & Doctor — chains `doctor` → `tools-audit` → `audit --all` with a verdict messagebox.
- **Persistent window geometry + last-active tab** — see config keys above.
- **One-click "Download…"** button in the status-bar update notification.
- **Determinate progress bar** for chained workflows (Refresh all wheels, Full metadata refresh, etc.).

### New CLI commands and flags

Additive only:

- **`spindoctor self-doctor`** — diagnoses SpinDoctor's own state (orphan corrupt-config rescue copies, oversized manifest dirs, expired metadata cache size, broken `config.json` / `favorites.json`, stray `.part` files under `<HyperSpin>/Media/`). Read-only by default; `--fix` performs only safe deletions of rescue copies and stale `.part` files. Manifests are never auto-deleted. See [Commands → Maintenance](commands.md#maintenance).
- **`spindoctor audit --no-media`** — skip the (slow) media checks for faster runs.
- **`spindoctor audit --detailed`** — append a per-file breakdown (path, size, dimensions, video length) for every game that needs attention.
- **`spindoctor audit --report path.csv`** — write the audit report as CSV.

### Humanized OSError messages

When a write fails because HyperSpin is open (Windows error 32), out of disk, or read-only-flagged, SpinDoctor now prints a one-sentence actionable message instead of the raw `[WinError 32] The process cannot access the file …`. Affects the GUI's Main Menu save worker, the GUI's "Could not launch" subprocess-spawn failure path, and the four CLI commands that historically printed `str(e)` verbatim (`backup create`, `backup restore`, `migrate`, `rename` / `clone`).

## What changed internally (only relevant if you've imported `spindoctor` as a library)

These are not user-visible — but if you've ever written a script that imports from the `spindoctor` package directly, two things to know:

- **`spindoctor._utils.format_bytes` / `free_bytes`** is the single source of truth for the byte-formatting and free-space helpers. `spindoctor.backup.format_bytes`, `spindoctor.migrate.format_bytes`, and `spindoctor.cleanup.format_size` are still importable — they're now re-exports of the shared implementation, not separate definitions.
- **`spindoctor._net.make_session()`** is the new way to build a `requests.Session` with a TLS 1.2 floor. Used internally by `scraper.py` and `media.py` so Win7 + OpenSSL 1.0.2u binaries don't negotiate TLS 1.0/1.1 against scraper / media endpoints that have dropped those protocols. If you've been building your own `requests.Session()` against the same APIs from a custom script, consider switching to `make_session()` for the same floor.

Neither change affects anything that wasn't internal-only.

## What didn't change

- **All 1.x CLI commands and flags** behave identically — same arguments, same output structure, same exit codes.
- **All 1.x `config.json` keys** are still honoured. New keys default to their 1.x-equivalent behaviour.
- **All 1.x on-disk manifests** under `~/.spindoctor/{migrations,curation,edits,renames,media_imports,themes,misplaced,restructures}/` are unchanged — your existing undo paths still work.
- **All 1.x integration patterns** (HyperSpin Tools menu, in-cabinet wheel system, Task Scheduler auto-refresh) still work without any changes.
- **The Windows-binary install layout** (`spindoctor.exe`, `spindoctor-gui.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, `spindoctor-stats.exe` together in one folder) is unchanged. Drop the new zip on top of the old install folder.

## Rollback

If something looks wrong after the upgrade, you can roll back any time without losing data — neither config nor manifests have changed schema:

- **Binary install**: re-extract the 1.x release zip over the install folder. `~/.spindoctor/` is untouched.
- **pip install**: `pip install spindoctor==1.9.1` (or any 1.x tag) replaces the wheel.

[Open an issue](https://github.com/phillram/spindoctor/issues) if you hit a regression — knowing whether 1.x worked on the same cabinet narrows the blame substantially.
