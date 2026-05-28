# Troubleshooting

Common problems and their fixes. For deeper recovery (rolling back a migration, restoring an XML, reversing a curate), see [Workflows → Recovery](workflows.md#recovery-from-mistakes).

## Install / startup

### Double-clicking `spindoctor.exe` flashes a window that closes instantly

That's the program working correctly — the CLI binaries (`spindoctor.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, `spindoctor-stats.exe`) print `--help` and exit when run with no arguments, and Windows tears the cmd window down the moment they exit. Three options:

- **Double-click `spindoctor-gui.exe`** instead — that's the supported windowed launcher.
- Open `cmd.exe` first (`Win+R` → `cmd` → Enter), `cd` to the install folder, then run `spindoctor.exe …` with arguments.
- Use the bundled `.bat` wrappers in [`scripts/`](https://github.com/phillram/spindoctor/tree/main/scripts) — they `pause` on error so the window stays open.

### `spindoctor: command not found`

The console scripts didn't end up on PATH. Re-run `pip install -e .` from the repo root and confirm Python's `Scripts\` directory is on your `Path` environment variable. As a fallback, `python -m spindoctor.cli ...` works without the entry point.

If you're using the prebuilt Windows binaries (no Python install), make sure the folder containing `spindoctor.exe` is on `PATH`, or invoke by full path (`C:\spindoctor\spindoctor.exe systems`). The GUI launcher locates its sibling exes by walking up from `sys.executable`, so it works without `PATH` configured — handy for cabinets where you don't want to touch environment variables.

### `spindoctor-gui` opens but every button errors with "Binary not found"

The GUI shells out to `spindoctor.exe` / `spindoctor-fav.exe` / `spindoctor-recent.exe` / `spindoctor-stats.exe` sitting next to it. If those got moved, renamed, or quarantined by antivirus, every Run click fails. Restore the missing exe (or re-extract the release zip) so all five files share a folder again.

For the pip install route, the same error means the underlying console script isn't on `PATH` — re-run `pip install -e .` and confirm the Python `Scripts/` directory is on `PATH`.

### Windows 7: "The procedure entry point ... could not be located in api-ms-win-core-..."

The `.exe` was built against a Windows SDK newer than Win 7 supports. The official binaries ship from a Python 3.8.10 + PyInstaller 5.x build environment specifically to avoid this — that pairing (not the runner OS) is what keeps the bootloader Win 7-compatible. If you self-built and hit this, downgrade your build environment to those versions — see [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md). Also confirm your Win 7 install has Service Pack 1 — the RTM (un-patched) release isn't supported.

### Windows SmartScreen blocks the .exe

Releases aren't code-signed yet, so Windows 10/11 may flag the binaries as unrecognised. Click **More info** → **Run anyway**. (Code signing is on the roadmap.)

### Win 7: `fetch-meta` or update check fails with `EOF in violation of protocol` / `SSL: WRONG_VERSION_NUMBER`

The remote scraper (ScreenScraper, TheGamesDB) refused the connection because Win 7's bundled OpenSSL 1.0.2 negotiated TLS 1.0 or 1.1 by default, and the server requires TLS 1.2+. SpinDoctor 2.0 pins TLS 1.2 as the floor on every HTTP session it creates, which fixes this — confirm you're on the latest binary. If you're on an older build, upgrade. Self-built `spindoctor.exe` on a custom Python should be fine as long as the Python install has TLS 1.2 enabled (Python 3.8.10 on Win 7 SP1 does).

### Second GUI window won't open ("Another SpinDoctor is already running")

By design — the GUI takes a single-instance file lock at `~/.spindoctor/gui.lock` because two windows writing to the same HyperSpin XML can corrupt the library. Bring the existing window to the front (Alt+Tab) or close it first. If you genuinely need two windows (comparing two cabinet configs on one machine), set `SPINDOCTOR_DISABLE_SINGLETON=1` before launching — you're then responsible for not running destructive operations from both. The lock is released when the process exits; it does not survive a crash.

### `~/.spindoctor/gui.lock` exists after a crash

That's expected and harmless. The OS released the lock on process exit; the file is just a stamped PID. Launching the GUI again will overwrite it and acquire the lock cleanly.

### `config init` rejects a path

Folders must exist before they can be configured. Create the folder first, then re-run.

### `spindoctor systems` shows `Database: ✗` next to a folder

That system has ROMs but no HyperSpin database yet. Run `spindoctor add-system "<exact folder name>"` to bootstrap it (dry-run first; re-run with `--apply`).

### Main Menu tab pops "Main Menu.xml could not be parsed"

The GUI tried to read `<hyperspin_dir>/Databases/Main Menu/Main Menu.xml` and the parser rejected it. The Main Menu table is cleared (so you don't act on stale rows) and the dialog names the file path and the parser's error message. Common causes:

- **HyperHQ is open and holds an exclusive write lock** — close HyperHQ and click Refresh.
- **Malformed XML** — usually a stray edit, an unclosed tag, or a Windows BOM in the wrong place. Re-save the file from HyperHQ (which always writes valid XML) and retry.
- **Truncated mid-write** — the file ends partway through a tag because a previous SpinDoctor / HyperHQ run was killed. Restore from your most recent backup (`spindoctor backup list` → `restore --include databases`) or hand-edit the tail back to a valid `</menu>` close tag.

The Output pane also has the raw parser error if you need to share it.

### `add-system` reports "no ROMs found, drop ROMs in and re-run"

Either the ROM folder is empty, or the file extensions aren't in SpinDoctor's recognized set for that system. Either drop ROMs in or teach SpinDoctor about a custom extension:

```bat
spindoctor config system set "<System>" --rom-extensions ext1,ext2
```

See [Configuration → Per-system overrides](configuration.md#per-system-overrides).

## Metadata / scraping

### ScreenScraper rate-limiting

SpinDoctor caps itself at 1 request/second. The free tier allows 500/day — wait until midnight UTC or upgrade your account.

### 403 from ScreenScraper or TheGamesDB

The Setup tab's **Test credentials** button verifies both providers. When either returns `HTTP 403`, the failure dialog now includes a trimmed copy of the upstream response body — that's usually where the real reason lives ("Erreur de login : mauvais mot de passe", "Invalid API key", a rate-limit notice). If you need the full request / response (e.g. to share with a maintainer), check the rotating log at:

```
~/.spindoctor/scraper.log
```

It records every ScreenScraper and TheGamesDB call SpinDoctor makes — `verify`, `fetch`, and `search` — with the URL, redacted query params (passwords and API keys are stripped), the HTTP status, and the first ~500 chars of any error-status body. The file rotates at 512 KB with two backups, so it stays small.

Common 403 causes, in order of likelihood:

1. **Wrong user credentials** — re-check `screenscraper_user` / `screenscraper_pass` (or `thegamesdb_key`). The Custom Command tab's `config show` preset prints the current values.
2. **Rate-limit exhaustion** — ScreenScraper free tier is 500 req/day, TheGamesDB is on a monthly-allowance budget. The body usually names this explicitly.
3. **ScreenScraper developer-credential rejection** — every ScreenScraper request also sends a per-app `devid`/`devpassword` pair (separate from the user creds). SpinDoctor defaults both to `"SpinDoctor"`; if the log shows the failure mentions `devid` or `developpeur`, override the pair with your own:
   ```bat
   spindoctor config set screenscraper_devid <your-devid>
   spindoctor config set screenscraper_devpassword <your-devpassword>
   ```
   The same Custom Command tab in the GUI takes these. See [Configuration → `screenscraper_devid` / `screenscraper_devpassword`](configuration.md#most-used-keys).

### Wrong metadata picked during `fetch-meta`

```bat
spindoctor match clear --system MAME
spindoctor fetch-meta --system MAME --apply
```

Cached match decisions live at `~/.spindoctor/match_cache/<system>.json`; clearing them only resets the cached choice — the previous XML edits aren't rolled back. To undo the writes too, restore the `.bak` next to the XML or use `git diff` if your library is under version control.

### ROM filenames have region tags like `(USA)` — will they match?

Yes — region/version/revision tags are stripped before searching. Ambiguous matches prompt with a review link to the metadata source. See [ROM variant handling](commands.md#rom-variant-handling).

## Wheels

### "PCLauncher does not know what exe, FadeTitle, and/or SteamID to watch for" when launching a Toolkit helper

This error appears when RocketLauncher's PCLauncher module finds a `[exe info]`-style INI for the helper entry, but the field for the monitored executable (or FadeTitle) is empty. PCLauncher needs that information to know when the launched program has finished — but the SpinDoctor refresh helpers are `.bat` files that run and exit on their own, so there is no process to monitor.

**Fix — run `install-tools` once:**

```bat
spindoctor install-tools --add-to-system Toolkit
```

This writes everything RocketLauncher and PCLauncher need in one step:

| File written | Purpose |
|---|---|
| `Modules/PCLauncher/Toolkit/*.bat` | The four refresh scripts |
| `Modules/PCLauncher/Toolkit/*.ini` | Per-game PCLauncher INIs (`[Settings]` format — no FadeTitle needed) |
| `Databases/Toolkit/Toolkit.xml` | HyperSpin `<game>` entries |
| `Settings/Toolkit.ini` | RocketLauncher system INI — tells RL to use PCLauncher and where the per-game INIs live |

The `Settings/Toolkit.ini` is the piece that was missing in older SpinDoctor
versions. Without it, RocketLauncher has no emulator mapping for the wheel and
PCLauncher can't find the per-game INIs — producing this exact error even when
all the other files are correctly in place.

**Prerequisites:** the Toolkit system must already exist in HyperSpin. If it
doesn't yet:

```bat
spindoctor add-system "Toolkit"
spindoctor mainmenu add "Toolkit" --apply
spindoctor install-tools --add-to-system Toolkit
```

The command is idempotent — safe to re-run after an upgrade.

See [Standalone tools → Wiring into HyperSpin Tools menu](standalone-tools.md#wiring-into-hyperspin-tools-menu) for the full
setup walkthrough, including the optional HyperHQ Tools-menu route and
Windows Startup scheduling.

---

### "Cannot find recently played.ini" when navigating the Recently Played wheel

RocketLauncher is using PCLauncher to launch a game from the Recently Played
wheel but can't find a per-game INI in `<RocketLauncher>/Modules/PCLauncher/Recently Played/`.
This is separate from the data-reading errors (covered below) — the wheel was
built and the database XML is fine; the problem is the launch chain.

Two approaches, in order of simplicity:

**Option A — point the "Recently Played" system at its source emulators via
RocketLauncher's Global Emulators.**  In RocketLauncherUI, set the "Recently
Played" system's emulator to **Global** and enable *Use system default emulators*.
RocketLauncher then looks up each ROM's origin system and uses that system's
emulator automatically. No per-game INIs needed.

**Option B — per-game PCLauncher INIs.** If you prefer PCLauncher-managed
launch (e.g. to run custom pre/post-launch scripts), run:

```bat
spindoctor install-tools --add-to-system "Recently Played"
```

This writes INIs that shell out to the correct system emulator for each entry.
Re-run after every `recent rebuild --apply` when the wheel contents change.

**Diagnostic tip:** run `spindoctor-recent rebuild` (without `--apply`) and
look for `source:` lines in the output — each shows which statistics file was
read. Any path that was tried but not found appears as a warning so you can see
exactly where RocketLauncher wrote its data.

---

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

### All unused buttons flash randomly during gameplay

Caused by `GamePlayLWAFile=<Random>` in `[GameOptions]` of `Settings.ini`. LedBlinky applies a random animation to every button not defined for the current game. Fix:

```bat
spindoctor ledblinky patch-settings             :: preview
spindoctor ledblinky patch-settings --apply     :: set GamePlayLWAFile= (empty) → unused buttons go dark
```

The empty value causes LedBlinky to fall back to each button's `defaultInactive` color. In the DEFAULT control group (`LEDBlinkyControls.xml`) that is `0,0,0,0` — off.

### LEDs flash randomly while browsing HyperSpin menus

Caused by `FELWAFile=<Random>` in `[FEOptions]` of `Settings.ini`. Fix by choosing a specific animation file, or silencing animation entirely:

```bat
:: List available .lwa files in your ledblinky_dir, then pick one:
spindoctor ledblinky patch-settings --apply                              :: preview first
spindoctor ledblinky patch-settings --fe-lwa "Slow Fade.lwa" --apply    :: smooth fade
spindoctor ledblinky patch-settings --fe-lwa "" --apply                  :: static colors, no animation
```

Use the **Refresh list** button in the GUI's LEDBlinky → Settings.ini Patch section to see which `.lwa` files are in your install.

### Where does `ledblinky generate` pull its data from?

Locally — `mame -listxml` is run as a subprocess and the output is cached in `~/.spindoctor/mame_listxml_cache/`. No scraper API, no quota. The cache is invalidated automatically when the MAME binary is newer than the cached file.

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

Almost every destructive command writes a manifest under `~/.spindoctor/<category>/` and supports `--undo`. Full recovery flows and the manifest map live at [Workflows → Recovery](workflows.md#recovery-from-mistakes). The GUI's `File → View logs & manifests…` window lists every per-run manifest with a tree on the left and a JSON viewer on the right; the **Undo this run** button at the bottom runs the matching `--undo` command for the selected row in one click. For categories whose CLI always reverses the most recent run (`curate`, `media-scan`), the button warns you if you pick an older row so you don't accidentally reverse the wrong one.

## GUI launcher

### Status bar says "Update available: vX.Y.Z" — what does it mean?

The GUI checks GitHub Releases on launch and surfaces newer-version hints in the status bar (with the URL in the Output panel). `Help → Check for updates` re-runs the same check on demand. To download, open the [latest release](https://github.com/phillram/spindoctor/releases/latest) and replace your `.exe` files (config and caches under `~/.spindoctor/` survive the upgrade — see [Updating](windows-binaries.md#updating)).

### How do I disable the update check?

Set the `SPINDOCTOR_NO_UPDATE_CHECK=1` environment variable before launching the GUI. The check is also a no-op when GitHub is unreachable, so you don't need to disable it explicitly for offline cabinets — it just silently degrades. See [Configuration → Environment variables](configuration.md#environment-variables).

### Where do my manifests live? How do I read one?

Open the GUI and use **`File → View logs & manifests…`**. The window groups manifests by category (Migrations, Curation, Edits, Renames, Media imports, Theme swaps, Misplaced ROMs) and shows the JSON content read-only. The folder behind it is `~/.spindoctor/<category>/`; **`File → Open SpinDoctor folder`** jumps straight there if you'd rather edit by hand. Don't edit a manifest if you might want to `--undo` later — the undo path reads the manifest verbatim. The same window has an **Undo this run** button that runs the matching `--undo` command for the selected row, so you don't have to remember which CLI invocation owns each category.

### My controller-glyph swap looks wrong / I want to revert it

`spindoctor theme-apply --apply` writes a manifest under `~/.spindoctor/themes/theme-apply-<timestamp>/manifest.json` with a backup of every overwritten file alongside. To revert: `spindoctor theme-apply --undo latest` from the CLI, or open the GUI's **`File → View logs & manifests…`** window, expand **Theme swaps**, click the row, and press **Undo this run**. If the GUI's `File → Browse HyperSpin themes…` returns nothing for your cabinet but you can clearly see glyphs at the bottom of the screen, those glyphs likely live inside a Flash `.swf` in `Media/Main Menu/Themes/default.zip` — SpinDoctor can't edit SWFs (they need a Flash authoring tool).

### Tools tab → Schedule auto-refresh fails with "access denied"

`schtasks.exe` writes to a system-wide Task Scheduler store that requires admin rights. Run SpinDoctor as Administrator (right-click `spindoctor-gui.exe` → **Run as administrator**) and click Schedule auto-refresh again. The GUI now translates `schtasks` failures into one-line actionable messages: "access is denied" → run as Administrator; "already exists" → use the Remove button first; "specified task does not exist" → there's no task to remove yet; anything else falls back to the raw `schtasks` output so power users can diagnose obscure error codes.

### "I hit Ctrl+C (or Stop) on a backup / migrate / curate — what's recoverable?"

All three commands now write a *partial manifest* of whatever finished before the interrupt:

- **Backup** — completed components remain in the backup folder and the manifest lists them; `backup restore` can replay it like a normal backup.
- **Migrate (move-mode)** — completed moves are recorded; `migrate --undo <manifest>` puts the source folders back. Without the partial manifest, an interrupted move-mode migrate used to be unrecoverable.
- **Curate (archive-mode)** — files moved to `_retired/` before the interrupt are recorded; `curate --undo <manifest>` un-archives them.

The in-flight component / move / archive (the one that was running when you hit Stop) is cleaned up automatically. Already-completed work is deliberately left in place — the manifest exists so *you* can choose whether to roll it back.

### Update check pings GitHub but I'd rather it didn't on this cabinet

Set `SPINDOCTOR_NO_UPDATE_CHECK=1` in the environment. The background check on launch silently becomes a no-op, and the manual `Help → Check for updates` action prints "Update check disabled" instead of contacting GitHub. See [Configuration → Environment variables](configuration.md#environment-variables).

### Menubar reference

See [GUI walkthrough → Menubar](gui.md#menubar) for the canonical list of File / View / Help menu items and their shortcuts.

### GUI looks cramped on a 720p (1280×720) cabinet screen

By default the window opens at 960×720 (minsize 720×540), which is fine on most 1080p / 1200p panels but tight on 720p with the Output panel mounted. Two new controls in the GUI fix this without resizing the window:

- **`View → UI scale → 0.9×`** (or press `Ctrl+-` once) shrinks fonts and widget metrics across the board so a full tab fits without scrolling. `Ctrl++` zooms back in, `Ctrl+0` resets. The chosen scale persists across restarts via the `ui_scale` config key. Range is `0.6`–`2.0`.
- **`Hide output`** (status-bar button, `View → Show output pane`, or `Ctrl+`` `) collapses the bottom panel and gives the active tab the full window height. Re-show with the same control. Persisted across restarts via the `output_visible` config key.

The two together typically clear another 200–300 vertical pixels on a 720p cabinet display.
