# Migrating from SpinDoctor 1.x

SpinDoctor 2.x continues to use `~/.spindoctor/` for settings, favorites, caches and recovery records. Back up that directory and your cabinet before upgrading. Later 2.x releases include safety and behavior changes beyond the original 2.0 GUI refresh; read the intervening [release notes](../CHANGELOG.md), rather than assuming every default is unchanged.

For binaries, extract the new release into a separate folder and keep the old bundle intact, including its runtime files. For a source checkout, update to the release you want and reinstall with `pip install -e .[all]`. Follow the current [Windows binary guide](windows-binaries.md#updating) or [installation guide](installation.md) for your route.

This page summarizes the original 2.0 transition and points to the current references. It is not an exhaustive list of all subsequent 2.x changes.

## What changed for end users

### GUI is the primary surface

The 2.0 cycle leaned hard on the GUI. The README, [setup walkthrough](setup.md), and [installation guide](installation.md) now lead with the GUI, with CLI listed as the equivalent "power user" path. If you've been a CLI-first cabinet owner, **nothing forces you to change** — the CLI is still the canonical surface and every GUI button shells out to it. The reordering is a signpost for new cabinet owners landing cold on the docs.

A new canonical GUI walkthrough lives at [`docs/gui.md`](gui.md). Previously the tab tour lived inside `docs/windows-binaries.md`, which made sense for binary users but read awkwardly for pip / source installs. `gui.md` is platform-neutral.

### Tab order in the GUI

The current tabs follow the setup-to-maintenance workflow. Older labels such as **Audit & Doctor**, **Curate**, **Wheels**, **Logs** and **Custom Command** have been regrouped under **Diagnostics**, **Maintenance**, **Custom Wheels**, **History** and **Console**.

Use the [GUI walkthrough](gui.md#tab-tour) for the current order and controls, including **Games** and **Intro Video**, rather than an old 2.0 screenshot. `Ctrl+1`–`Ctrl+9` still jumps to the Nth tab.

### First-run wizard (opt-in)

A 3-step modal (Welcome → pick `roms_dir` + `hyperspin_dir` → run `doctor`) is available from the **Setup tab → Run first-run wizard** button and from **Help → First-run setup**. It does NOT auto-fire at launch (an early 2.0 build did; cabinet owners didn't need a modal between them and the Setup tab). Existing 1.x installs see nothing on first launch — open the wizard manually whenever you like.

### New GUI config keys

The GUI remembers window geometry and maximized state, the last active tab, region choices and metadata preferences. See [Configuration → Most-used keys](configuration.md#most-used-keys) for the current `gui_*` fields and defaults.

These settings are managed by the GUI. **Apply / dry-run toggles for destructive operations are deliberately NOT persisted**; re-enable Apply for each session only after checking the plan.

### New GUI affordances

None of these change existing behaviour — they're additive:

- **Find bar** above the Output panel — `Ctrl+F` to open.
- **System quick-filter** — `Ctrl+Shift+F` to narrow every system combobox across every tab.
- **Drag-and-drop** — drop a folder from Explorer / Finder onto any Setup path field to fill it.
- **Multi-system `fetch-meta` selector** — refresh a hand-picked subset of systems in one click from the Metadata & Media tab.
- **Per-system overrides form** on the Systems tab — surfaces `config system set` as a form instead of CLI flags.
- **Preflight check** button on Diagnostics — chains `doctor` → `tools-audit` → `audit --all` with a verdict messagebox.
- **Persistent window geometry + last-active tab** — see config keys above.
- **One-click "Download"** button in the status-bar update notification.
- **Determinate progress bar** for chained workflows (Refresh all wheels, Full metadata refresh, etc.).
- **Single-instance lock** — a second `spindoctor-gui` on the same machine refuses to start so two windows can't race on the same HyperSpin XML. Override with `SPINDOCTOR_DISABLE_SINGLETON=1` if you genuinely need both open.
- **Help → Keyboard shortcuts** dialog — in-app reference for the shortcut map; no more digging through docs.
- **Partial recovery after interruption** — backup, move-mode migrate and curate-archive handle a normal interrupt by recording completed work. Open **File → View logs & manifests** to inspect recovery options. This is not a guarantee against process crashes or failed manifest writes; see [Stopping a long-running command](gui.md#stopping-a-long-running-command).
- **`fetch-meta --skip-ambiguous`** wired into the GUI — unticking "Auto-pick best match" no longer hangs the subprocess on an interactive `input()` prompt; ambiguous matches are logged for the next `audit` pass instead.
- **Migrate confirm dialog** — Apply now pops a confirmation modal before shelling out, with distinct wording for `--keep-source` (copy, originals stay) and the destructive move (warns explicitly that originals will be removed and points at the undo-manifest escape hatch). Cancel and nothing runs.
- **Main Menu.xml parse errors surface as a modal** — previously the failure was a single line in the Output pane and the Treeview kept showing stale rows from the last successful load. Now the table empties on failure and a modal names the file path + the parser's error so you can't miss it.
- **Async startup** — the GUI window paints immediately, then runs the library scan (system combo population) and the startup health checks in the background. Status bar shows "Scanning library" while it works. On a slow NAS-mounted Databases directory this avoids the "is it frozen?" beat the old synchronous behaviour had.
- **Fresh-install Setup focus** — on first launch (no `config.json` yet) the GUI auto-selects the Setup tab so a brand-new cabinet owner lands on the form that needs filling. Existing users' `gui_last_active_tab` is restored as usual.
- **Routine popups demoted to the status bar** — "Saved", "Removed", "Up to date", "No subset picked", "Nothing to apply", etc. now flash in the status bar (auto-reverts to "Ready." after 6 s; validation prompts also ring the system bell) instead of forcing a click-through modal. Multi-line result modals (Preflight passed, Curate done with manifest path, Scheduled with reboot instructions) and destructive-action confirmations stay as modals.
- **Curate delete confirmation rewritten** — the final destructive-confirm now lists the target system, the regions kept, and the revision preference up front so you can re-verify intent at a glance. Explicit "no undo for delete mode" wording with an archive-mode pointer.
- **Re-review-titles form (was "Rename") for PC systems** — the Systems tab's pc-rename form is now a single system dropdown with hint text explaining the command *re-runs the title picker for an existing PC system*. Earlier 2.0 builds shipped a misleading two-field "Old/New" form that wasn't wired to the CLI; that's been fixed.
- **Friendly Task Scheduler errors** — the Custom Wheels tab's Enable auto-run button now translates `schtasks.exe` failures into one-line actionable messages: "access denied" → run as Administrator; "already exists" → use the Disable auto-run button first; "specified task does not exist" → there's nothing registered yet; anything else falls back to raw `schtasks` output for power-user diagnosis.

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

- **CLI access** remains available alongside the GUI. Use `spindoctor <command> --help` for the installed release's flags.
- **Settings and favorites** stay under `~/.spindoctor/`. Review [Configuration](configuration.md) for current defaults and automatic migrations, including metadata-source selection.
- **Recovery records** retain their established locations. See [Recovery from mistakes](workflows.md#recovery-from-mistakes) for command-specific undo support and limitations.
- **Tools-menu and Task Scheduler integration** remains supported. Update configured executable paths if the installation folder changes.
- **Windows binaries** remain available. v3 ships two independent single-file EXEs (`spindoctor-gui.exe` and `spindoctor.exe`), each embedding all workers and bundled deployment media. Either works alone; use `--run-tool` for the wheel builders (see [Windows binaries](windows-binaries.md#upgrading-from-v2)).

## Rollback

Keep the old release and a **pre-upgrade snapshot** of `~/.spindoctor/` and the cabinet files. Downgrading the executable alone does not reverse file edits, restore deleted ROMs or guarantee that an old release understands newer recovery records.

- **Binary install:** return to the intact old bundle. Do not mix executables or runtime files from different bundles.
- **Source install:** reinstall the old release from its checkout or tag.
- Restore the matching data snapshot if needed, with both releases closed. Keep newer manifests and backups separately until recovery is complete.

[Open an issue](https://github.com/phillram/spindoctor/issues) if you hit a regression — knowing whether 1.x worked on the same cabinet narrows the blame substantially.
