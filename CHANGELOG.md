# Changelog

All notable changes to SpinDoctor are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added — Supply-chain hardening

- `.github/workflows/security.yml` — runs Bandit (static analysis) and pip-audit (CVE scan) on every PR, every push to `main`, and weekly on Mondays.
- `.github/dependabot.yml` — weekly Dependabot scans for both pip dependencies and GitHub Actions versions.
- Release workflow now generates `SHA256SUMS.txt` next to the zip so users can verify their download with `sha256sum -c SHA256SUMS.txt`.
- Release workflow now publishes a [SLSA build provenance attestation](https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds). Verify with `gh attestation verify spindoctor-windows-vX.Y.Z.zip --repo phillram/spindoctor`.
- `[tool.bandit]` in `pyproject.toml` documents which Bandit rules are skipped and why (non-cryptographic SHA-1 / MD5 use, locally-controlled XML inputs).

### Changed

- `requests` floor bumped from `2.28` to `2.33.0` to ship the fix for [CVE-2026-25645](https://github.com/advisories/GHSA-) (HTTP request smuggling on chunked responses).
- All GitHub Actions in `ci.yml`, `release.yml`, `security.yml` are now pinned to commit SHAs (with the version in a comment) so a tag-rewrite supply-chain attack cannot silently swap action code. Dependabot keeps these current.

### Fixed

- Removed five unused imports surfaced by `spindoctor lint` (`shutil` in `cleanup.py`, `asdict` in `curate.py` / `media_scan.py`, `field` and `DEFAULT_LIMIT` in `playtime.py`).

## [1.0.0] - 2026-04-30

First public release. SpinDoctor is a command-line librarian for [HyperSpin](http://www.hyperspin-fe.com/) + [RocketLauncher](https://rocketlauncher.net/) arcade cabinets — it audits ROMs, syncs HyperSpin XML, fetches metadata and media, manages cross-system Favorites / Recently Played / Most Played wheels, wires Sinden / DemulShooter for light-gun systems, and migrates entire libraries between drives.

### Highlights

- **Standalone Windows binaries** — `spindoctor.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, `spindoctor-stats.exe` ship attached to the GitHub Release. No Python install needed on the cabinet. Compatible with Windows 7 SP1, 8, 8.1, 10, and 11.
- **Dry-run by default** — every command that modifies files previews its plan unless invoked with `--apply`. Read-only commands (`audit`, `inspect`, `report`, `systems`, `find-dupes`, `verify`, `check-discs`, `stats`, `doctor`, `tools-audit`, `find-global`, `lightgun detect`, `lightgun audit`) need no flag.
- **Reversible writes** — every destructive command writes a JSON manifest under `~/.spindoctor/<category>/` and accepts `--undo`. XML writes leave a `.YYYYMMDD_HHMMSS.bak` next to the original.
- **Replaces a graveyard of legacy tools** — Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, HyperT00ls, Don's HyperTools, Hypersearch, the CUE Renamer, plus assorted lightgun wiring scripts. `spindoctor tools-audit` inventories what's installed and tells you which command supersedes each one.

### Added — Core library management

- `systems` — list every detected system across `roms_dir` and `Databases/`.
- `audit` — compare ROM files vs. HyperSpin DB and media; reports exact + fuzzy matches, missing entries, missing media, and ignored counts; CSV export with `--report`.
- `inspect` — per-file deep-dive (image dimensions, video length, modification times) for one game or every game with issues.
- `update-db` — sync HyperSpin XML to ROM directories; adds stub entries for new ROMs, optionally removes orphans. `--strip-variant-tags` collapses `(Japan)` / `(USA)` displays.
- `fetch-meta` — download description / year / manufacturer / genre / rating / players from ScreenScraper or TheGamesDB. Cached at `~/.spindoctor/metadata_cache/` with TTL. Interactive disambiguation with cached choices; `--auto-best` to skip prompts.
- `fetch-media` — download wheels, backgrounds, snaps, videos, themes, fade images, sounds, trailers. **Resumable downloads** via HTTP Range requests — partial files survive interruptions and pick up where they left off. Concurrency-controlled, 429/503-aware retry.
- `media-add` — manually drop a local file into the right HyperSpin media slot.
- `media-scan` — inverse of `find-orphan-media`: bulk-import a folder of local media (EmuMovies pack, custom art) by fuzzy-matching against the database. `--apply` is reversible via `--undo`.
- `find-global` — search every configured system's HyperSpin database for a title. Replaces standalone Hypersearch utilities.
- `report` — read-only summary or CSV.

### Added — Editing

- `batch-edit` — set / clear / append / prepend metadata fields across many games filtered by name, genre, year, manufacturer, or `missing=<field>`. Reversible via `--undo`.
- `rename` — atomic ROM + DB entry + every media slot rename. RocketLauncher PCLauncher INIs follow. Reversible.
- `clone` — duplicate a base ROM as a hack/translation variant; ROM and media are copied (not moved); a new `<game>` entry is appended.

### Added — Library generation

- `generate-config` — generate RocketLauncher INI files and the HyperSpin Main Menu XML.
- `mainmenu` — inspect, reorder, hide, show, add, remove, sort (alpha / manufacturer / year), and interactively edit the top-level systems wheel.
- `organize` — populate genre / year / manufacturer / letter sort wheels and optionally restructure ROMs into per-game folders or multi-disc m3u playlists.
- `add-system` — bootstrap a brand-new console end-to-end: registers it in the Main Menu, creates database stub, generates RocketLauncher INI, scaffolds media folders, walks the metadata + media fetch flow.
- `add-pc-system` — same for PC / Windows / Steam libraries; recursive scanning of nested install folders, title-picker for awkward layouts, per-game PCLauncher INIs.
- `pc-rename` — re-run the PC title picker after dropping new games in.
- `migrate` — move (or copy) the entire library — or specific components — to a new drive in one shot. Updates `config.json` and writes a manifest you can `--undo`. Components: `roms`, `hyperspin`, `emulators`, `rocketlauncher`, `ledblinky`, or `all`. `--keep-source --verify` for a safe SHA1-verified copy that leaves originals intact.
- `backup` — copy any combination of library components into a dated folder on a different drive (`backup create` / `list` / `info` / `restore`). `--use-current-paths` reroutes a restore when drive letters change.

### Added — Health & integrity

- `find-dupes` — duplicate detection within a system or across systems; `--by-content` for byte-level pairing across `.zip` / `.7z` / `.rar` / `.gz` / `.chd` (the last three need `[archives]` extra).
- `find-misplaced` — flag ROMs whose extension doesn't match the folder's system; `--apply` moves each to its suggested system; reversible.
- `curate` — region & version curation: pick one canonical variant per game (configurable region preferences, latest revision); archive losers to `_retired/` (reversible) or delete (permanent).
- `find-orphan-media` — wheels / snaps / videos / themes whose game no longer exists.
- `check-discs` — validate multi-disc layouts and `.m3u` playlists.
- `verify` — verify ROM integrity against No-Intro / Redump / TOSEC DAT XMLs. Inner-content and wrapper-byte matching. Lazy hashing — files whose size doesn't appear in the DAT skip hashing entirely. `.zip` / `.gz` / `.chd` native; `.7z` / `.rar` via `[archives]` extra.
- `stats` — coverage dashboard: % matched to DB, % metadata complete, % media complete.
- `preview` — visual contact sheets and per-game cards (HTML by default; PNG via `[preview]` extra).

### Added — Custom wheels

- `fav` — cross-system Favorites wheel. Cabinet end-user can favorite from any system; the wheel pulls all games into a synthetic `Favorites` HyperSpin system, alphabetically sorted by display title, with media hardlinked from source systems. `fav sync` pulls HyperSpin's per-system F-key favorites into the cross-system store.
- `recent` — Recently Played wheel auto-derived from RocketLauncher's `Statistics.ini`. No extra hooks needed.
- `stats-report` — playtime reporting (totals, top games, per-system breakdown) and the `build-wheel` subcommand that generates a Most Played wheel.
- `install-tools` — write `.bat` wrappers HyperSpin's Tools menu can invoke directly so end-users can refresh wheels from the UI.
- **Three standalone CLIs** (`spindoctor-fav`, `spindoctor-recent`, `spindoctor-stats`) with light `argparse` entry points — fast enough to use as a Windows boot trigger without loading the full CLI.

### Added — LEDBlinky

- `ledblinky generate` / `audit` — generate `controls.ini` and `colors.ini` from MAME `-listxml`, preserving any community-maintained entries.
- `ledblinky check` / `fix` — diagnose and patch the well-known issue where HyperSpin's Search overlay crashes when LEDBlinky is installed. Fully reversible.

### Added — Light guns

- `lightgun detect` / `audit` / `configure` — wires Sinden + DemulShooter into RocketLauncher's per-system `Settings/<System>.ini` via `Pre_Launch_App` / `Post_Launch_App`. Auto-targeting for MAME, Naomi, Atomiswave, Dreamcast, Model 2, Model 3 (Supermodel), Flycast, ChiHiro, Triforce, Lindbergh, Ringedge, Global VR. Module `.ahk` files are never modified — a stock Tur build remains intact.

### Added — Maintenance

- `doctor` — self-diagnose paths, binaries, XML DB integrity, match-cache hygiene, RocketLauncher / LEDBlinky files, optional `lxml` / `ffprobe`. `--apply` runs safe idempotent repairs (prune stale cache, scaffold media folders, regen `Global Emulators.ini`).
- `tools-audit` — read-only inventory of third-party arcade tools (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, Sinden, DemulShooter, XPadder, JoyToKey, DS4Windows, …); flags which `spindoctor` command replaces each one.
- `ignore` — per-system or global ignore lists honoured by `audit`, `fetch-meta`, `fetch-media`, `update-db`.
- `match` — manage cached metadata-match decisions made interactively during `fetch-meta`.
- `cleanup` — one-stop inventory and removal of every cache, manifest, temp dir, and `.bak` SpinDoctor produces, including stale `.part` sidecars from interrupted downloads.
- `lint` — AST pass over the SpinDoctor source itself; surfaces unused imports, bare `except:`, TODO markers, and near-duplicate function bodies.

### Added — Build & release infrastructure

- `build/build_windows.py` — PyInstaller driver producing four single-file `.exe` binaries.
- `.github/workflows/release.yml` — triggered by `v*` tag push; builds, smoke-tests, zips, and publishes a GitHub Release with the artefacts attached.
- `.github/workflows/ci.yml` — runs pytest on Linux + Windows (Python 3.8 and 3.12) and a PyInstaller smoke build on every PR.

### Compatibility

- **Operating systems** — Windows 7 SP1, 8, 8.1, 10, 11 (binaries). Windows 7 RTM (no Service Pack 1) is **not** supported. The CLI itself runs on macOS and Linux for development and testing, but the integration target is HyperSpin on Windows.
- **Python** — 3.8 or newer when installed from source. Binary releases bundle Python 3.8.10, so the cabinet doesn't need its own install.
- **Filesystems** — NTFS / ext4 / APFS for hardlink-based wheel media mirroring. FAT32 / exFAT fall back to copies via `--media-mode copy`.
- **Optional extras**:
  - `[xml]` (`lxml`) — lossless XML round-trips; preserves comments and attribute order written by HyperHQ.
  - `[archives]` (`py7zr`, `rarfile`) — `.7z` / `.rar` peeking for `verify` and `find-dupes --by-content`.
  - `[preview]` (`Pillow`) — PNG contact sheets for `spindoctor preview`.

### Security & data safety

- ROMs and BIOS files are never downloaded, by design. Source them from games and consoles you own.
- Metadata API credentials are stored in `~/.spindoctor/config.json`. Include `--include settings` in `backup create` to capture them; otherwise they're re-entered on a new install.
- Every XML write makes a timestamped `.bak` first (toggle via `backup_before_modify`). `curate --action delete` and `find-orphan-media --apply` are the only operations that aren't reversible — both prompt before acting.

### Known limitations

- Windows binaries are **not code-signed** — Windows 10/11 SmartScreen will warn the first time. Click "More info" → "Run anyway". Code signing is on the roadmap.
- `migrate` does not rewrite emulator-internal absolute paths (RetroArch's `retroarch.cfg`, PCSX2 INIs, Dolphin user folder, etc.). Re-test each emulator after a drive move.
- `fetch-media` theme / fade / sound coverage is sparse — these come from ScreenScraper only. For EmuMovies-style theme packs, drop the files into a folder and use `media-scan --apply`.
- ScreenScraper free tier is rate-limited to 500 requests/day.

[Unreleased]: https://github.com/phillram/spindoctor/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/phillram/spindoctor/releases/tag/v1.0.0
