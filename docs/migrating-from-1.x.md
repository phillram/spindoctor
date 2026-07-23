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

If you have muscle memory for the old order, the keyboard shortcut `Ctrl+1`–`Ctrl+9` still jumps to the Nth tab — just the Nth has changed.

### First-run wizard (opt-in)

A 3-step modal (Welcome → pick `roms_dir` + `hyperspin_dir` → run `doctor`) is available from the **Setup tab → Run first-run wizard** button and from **Help → First-run setup**. It does NOT auto-fire at launch (an early 2.0 build did; cabinet owners didn't need a modal between them and the Setup tab). Existing 1.x installs see nothing on first launch — open the wizard manually whenever you like.

### New GUI config keys

Seven new keys in `config.json`:

| Key | Default | Purpose |
|---|---|---|
| `gui_window_geometry` | unset | Last `WIDTHxHEIGHT+X+Y` the GUI window was at when it closed. Restored on the next launch. |
| `gui_last_active_tab` | unset | Index of the tab that was open the last time the GUI closed. Restored on the next launch. |
| `gui_meta_subset` | `[]` | Last-picked subset of systems for the Metadata & Media tab's "Pick subset" picker. Restored on next launch. |
| `gui_curate_regions` | `[]` | Curate-tab region tickboxes (USA, Japan, Europe, …). Empty list = use the top-level `region_preferences`. |
| `gui_meta_auto_best` | `true` | Persisted state of the Metadata & Media tab's "Auto-pick best match" checkbox. |
| `gui_meta_all_games` | `false` | Persisted state of the "Refresh complete entries too" checkbox. |
| `gui_meta_no_cache` | `false` | Persisted state of the "Skip cache, hit the API every game" checkbox. |

All seven are managed by the GUI; hand-editing them is fine but not necessary. **Apply / dry-run toggles for destructive operations are deliberately NOT persisted** — those re-arm to OFF on every launch so cabinet owners always make an explicit per-run opt-in. See [Configuration → Most-used keys](configuration.md#most-used-keys) for full descriptions.

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
- **One-click "Download"** button in the status-bar update notification.
- **Determinate progress bar** for chained workflows (Refresh all wheels, Full metadata refresh, etc.).
- **Single-instance lock** — a second `spindoctor-gui` on the same machine refuses to start so two windows can't race on the same HyperSpin XML. Override with `SPINDOCTOR_DISABLE_SINGLETON=1` if you genuinely need both open.
- **Help → Keyboard shortcuts** dialog — in-app reference for the shortcut map; no more digging through docs.
- **Safe-to-Stop long operations** — interrupting a backup, move-mode migrate, or curate-archive run now leaves a *partial manifest* describing what completed before the interrupt. The backup is still visible in the Restore picker; the migrate is reversible via `Logs → Browse manifests / undo → Undo`. See `docs/gui.md → Stopping a long-running command` for the full story.
- **`fetch-meta --skip-ambiguous`** wired into the GUI — unticking "Auto-pick best match" no longer hangs the subprocess on an interactive `input()` prompt; ambiguous matches are logged for the next `audit` pass instead.
- **Migrate confirm dialog** — Apply now pops a confirmation modal before shelling out, with distinct wording for `--keep-source` (copy, originals stay) and the destructive move (warns explicitly that originals will be removed and points at the undo-manifest escape hatch). Cancel and nothing runs.
- **Main Menu.xml parse errors surface as a modal** — previously the failure was a single line in the Output pane and the Treeview kept showing stale rows from the last successful load. Now the table empties on failure and a modal names the file path + the parser's error so you can't miss it.
- **Async startup** — the GUI window paints immediately, then runs the library scan (system combo population) and the startup health checks in the background. Status bar shows "Scanning library" while it works. On a slow NAS-mounted Databases directory this avoids the "is it frozen?" beat the old synchronous behaviour had.
- **Fresh-install Setup focus** — on first launch (no `config.json` yet) the GUI auto-selects the Setup tab so a brand-new cabinet owner lands on the form that needs filling. Existing users' `gui_last_active_tab` is restored as usual.
- **Routine popups demoted to the status bar** — "Saved", "Removed", "Up to date", "No subset picked", "Nothing to apply", etc. now flash in the status bar (auto-reverts to "Ready." after 6 s; validation prompts also ring the system bell) instead of forcing a click-through modal. Multi-line result modals (Preflight passed, Curate done with manifest path, Scheduled with reboot instructions) and destructive-action confirmations stay as modals.
- **Curate delete confirmation rewritten** — the final destructive-confirm now lists the target system, the regions kept, and the revision preference up front so you can re-verify intent at a glance. Explicit "no undo for delete mode" wording with an archive-mode pointer.
- **Re-review-titles form (was "Rename") for PC systems** — the Systems tab's pc-rename form is now a single system dropdown with hint text explaining the command *re-runs the title picker for an existing PC system*. Earlier 2.0 builds shipped a misleading two-field "Old/New" form that wasn't wired to the CLI; that's been fixed.
- **Friendly Task Scheduler errors** — the Custom Wheels tab's Schedule auto-refresh button now translates `schtasks.exe` failures into one-line actionable messages: "access denied" → run as Administrator; "already exists" → use the Remove button first; "specified task does not exist" → there's nothing registered yet; anything else falls back to raw `schtasks` output for power-user diagnosis.

### New CLI commands and flags

Additive only:

- **`spindoctor self-doctor`** — diagnoses SpinDoctor's own state (orphan corrupt-config rescue copies, oversized manifest dirs, expired metadata cache size, broken `config.json` / `favorites.json`, stray `.part` files under `<HyperSpin>/Media/`). Read-only by default; `--fix` performs only safe deletions of rescue copies and stale `.part` files. Manifests are never auto-deleted. See [Commands → Maintenance](commands.md#maintenance).
- **`spindoctor audit --no-media`** — skip the (slow) media checks for faster runs.
- **`spindoctor audit --detailed`** — append a per-file breakdown (path, size, dimensions, video length) for every game that needs attention.
- **`spindoctor audit --report path.csv`** — write the audit report as CSV.
- **`spindoctor fetch-meta --skip-ambiguous`** — log ambiguous matches and move on, instead of either auto-picking the top candidate (`--auto-best`) or prompting (`--interactive`). Required from non-TTY contexts (the GUI uses this by default when "Auto-pick best match" is unticked); useful for cron / CI runs that shouldn't block on stdin.
- **`spindoctor fetch-media --skip-ambiguous`** — same idea for the per-media-slot picker (regions, artwork variants). Required when running from a GUI subprocess or a cron / CI shell.
- **`spindoctor add-pc-system --no-interactive`** and **`spindoctor pc-rename --no-interactive`** — auto-accept every proposed title without prompting. Required from non-TTY contexts; the GUI passes `--no-interactive` automatically when adding a PC system, where the interactive review path would otherwise hang the subprocess on stdin.

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
- **All 1.x on-disk manifests** under `~/.spindoctor/{migrations,curation,edits,renames,media_imports,themes}/` — plus the `_spindoctor-misplaced-*.json` / `_spindoctor-restructure-*.json` manifests in the ROM tree — are unchanged; your existing undo paths still work.
- **All 1.x integration patterns** (HyperSpin Tools menu, in-cabinet wheel system, Task Scheduler auto-refresh) still work without any changes.
- **The Windows-binary install layout** (`spindoctor.exe`, `spindoctor-gui.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, `spindoctor-stats.exe` together in one folder) is unchanged. Drop the new zip on top of the old install folder.

## Rollback

If something looks wrong after the upgrade, you can roll back any time without losing data — neither config nor manifests have changed schema:

- **Binary install**: re-extract the 1.x release zip over the install folder. `~/.spindoctor/` is untouched.
- **pip install**: `pip install spindoctor==1.9.1` (or any 1.x tag) replaces the wheel.

[Open an issue](https://github.com/phillram/spindoctor/issues) if you hit a regression — knowing whether 1.x worked on the same cabinet narrows the blame substantially.
