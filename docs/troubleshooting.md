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

The GUI shells out to `spindoctor.exe`, `spindoctor-fav.exe`, `spindoctor-recent.exe`, and `spindoctor-stats.exe` sitting next to it. If those got moved, renamed, or quarantined by antivirus, every Run click fails. Re-download or re-extract the affected EXE from the release zip — each is a self-contained binary.

For the pip install route, the same error means the underlying console script isn't on `PATH` — re-run `pip install -e .` and confirm the Python `Scripts/` directory is on `PATH`.

### Windows 7: "The procedure entry point ... could not be located in api-ms-win-core-..."

The `.exe` was built against a Windows SDK newer than Win 7 supports. The official binaries ship from a Python 3.8.10 + PyInstaller 5.x build environment specifically to avoid this — that pairing (not the runner OS) is what keeps the bootloader Win 7-compatible. If you self-built and hit this, downgrade your build environment to those versions — see [build/README.md](https://github.com/phillram/spindoctor/blob/main/build/README.md). Also confirm your Win 7 install has Service Pack 1 — the RTM (un-patched) release isn't supported.

### Windows SmartScreen blocks the .exe

The release binaries aren't code-signed, so Windows 10/11 may flag them as unrecognised. Click **More info** → **Run anyway**. If your IT policy blocks unsigned binaries entirely, see [Windows binaries → SmartScreen warning](windows-binaries.md#windows-protected-your-pc-smartscreen-warning) for alternatives.

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

### Systems tab pops "Main Menu.xml could not be parsed"

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

### Reading `scraper.log`

Every ScreenScraper and TheGamesDB HTTP call SpinDoctor makes is logged to:

```
%USERPROFILE%\.spindoctor\scraper.log
```

(On macOS/Linux: `~/.spindoctor/scraper.log`. See [SpinDoctor Files](spindoctor-files.md) for the full list of files and their locations.)

The log rotates at 512 KB with two backups (`scraper.log.1`, `scraper.log.2`). Passwords and API keys are always redacted (`***`) — the file is safe to share with maintainers.

Each line is one HTTP call:

```
2026-05-25 16:45:32 INFO  screenscraper.verify GET https://…/ssuserInfos.php params={…} → HTTP 200 (1254 bytes)
2026-06-14 17:46:37 ERROR screenscraper.search GET https://…/jeuRecherche.php params={…} → HTTPSConnectionPool…Max retries exceeded…NameResolutionError
2026-06-14 12:45:16 INFO  screenscraper.fetch  GET https://…/jeuInfos.php  params={…} → HTTP 404 (40 bytes)
2026-06-14 12:45:17 DEBUG screenscraper.fetch  body: Erreur : Rom/Iso/Dossier non trouvée !
```

What to look for:

| Log entry | Meaning |
|-----------|---------|
| `→ HTTP 200` | Success |
| `→ HTTP 403` + `Erreur de login` body | Wrong user/password |
| `→ HTTP 403` + devid mention | Wrong or unregistered `devid`/`devpassword` |
| `→ HTTP 400` + `Champ systemeid obligatoire` | System not found in SpinDoctor's ID map; open an issue |
| `→ HTTP 404` + `non trouvée` | Game not found on ScreenScraper for that ROM filename |
| `→ HTTP 200` (tiny body, ~59 bytes) | Search returned zero results (not an error) |
| `→ Max retries exceeded … NameResolutionError` | DNS failure — cabinet cannot reach the internet |
| `→ Read timed out` | ScreenScraper server overloaded; retry later |

### `fetch-media` reports "Failed: 500" with no explanation

**Symptom:** `fetch-media` completes immediately, prints `Downloaded: 0  Skipped: 0  Failed: 500`, and gives no other output. The cabinet's network may have been down at the time.

**Cause:** Both ScreenScraper and TheGamesDB were unreachable (DNS resolution failed). SpinDoctor now surfaces this as a per-game error message and aborts the metadata phase early:

```
  metadata error: Animal Crossing (USA): ScreenScraper: … Max retries exceeded … NameResolutionError
  metadata error: Baten Kaitos - Eternal Wings…: ScreenScraper: …
  metadata error: Chibi-Robo! (USA): …
  Network unreachable — aborting metadata resolution (97 games counted as failed).
  Downloaded: 0  Skipped: 0  Failed: 500
```

**What to check:**

1. Open `scraper.log` (path above). If every `screenscraper.fetch` and `thegamesdb.fetch` line ends with `NameResolutionError` or `getaddrinfo failed`, the cabinet's internet connection was down at that time. Wait for network to recover and re-run.

2. If the log shows `HTTP 403` instead of DNS errors, see [403 from ScreenScraper or TheGamesDB](#403-from-screenscraper-or-thegamesdb) below.

3. If the log shows a mix of successes and DNS errors, the cabinet's connection is intermittent. Reduce `max_concurrent_downloads` to 1 to serialise requests and reduce load on the DNS resolver.

### ScreenScraper rate-limiting

SpinDoctor caps itself at 1 request/second. The free tier allows 500/day — wait until midnight UTC or upgrade your account.

### 403 from ScreenScraper or TheGamesDB

The Setup tab's **Test credentials** button verifies both providers. When either returns `HTTP 403`, the failure dialog includes a trimmed copy of the upstream response body — that's usually where the real reason lives ("Erreur de login : mauvais mot de passe", "Invalid API key", a rate-limit notice). Check the full request/response in `scraper.log` if you need more detail.

Common 403 causes, in order of likelihood:

1. **Wrong user credentials** — re-check `screenscraper_user` / `screenscraper_pass` (or `thegamesdb_key`). The Console tab's `config show` preset prints the current values.
2. **Rate-limit exhaustion** — ScreenScraper free tier is 500 req/day, TheGamesDB is on a monthly-allowance budget. The body usually names this explicitly.
3. **ScreenScraper developer-credential rejection** — every ScreenScraper request also sends a per-app `devid`/`devpassword` pair (separate from the user creds). The default `"SpinDoctor"` value is **not** a registered developer account — ScreenScraper rejects it with HTTP 403. Register your own at `https://www.screenscraper.fr/membreinscription.php`, then set the values:
   ```bat
   spindoctor config set screenscraper_devid <your-devid>
   spindoctor config set screenscraper_devpassword <your-devpassword>
   ```
   The same Console tab in the GUI takes these. See [Configuration → `screenscraper_devid` / `screenscraper_devpassword`](configuration.md#most-used-keys).

### Wrong metadata picked during `fetch-meta`

```bat
spindoctor match clear --system MAME
spindoctor fetch-meta --system MAME --apply
```

Cached match decisions live at `~/.spindoctor/match_cache/<system>.json`; clearing them only resets the cached choice — the previous XML edits aren't rolled back. To undo the writes too, restore the `.bak` next to the XML or use `git diff` if your library is under version control.

### ROM filenames have region tags like `(USA)` — will they match?

Yes — region/version/revision tags are stripped before searching. Ambiguous matches prompt with a review link to the metadata source. See [ROM variant handling](commands.md#rom-variant-handling).

### `fetch-media` resolves the game but every type reports "no URL", even with `--source both`

```
→ resolved (screenscraper)
  no URL:      Some Game (USA) · wheel
  no URL:      Some Game (USA) · background
  ...
```

This means ScreenScraper matched the game by name through its text-search endpoint, which returns a lighter record than the per-game detail page and can omit the media gallery entirely — even though the game's own ScreenScraper page has plenty of art. SpinDoctor automatically re-fetches the matched game by ID to backfill the gallery when this happens; if you're still seeing this on an up-to-date install, it means that backfill also came back empty (the account used genuinely has no media access for that title, e.g. a non-contributor ScreenScraper account hitting premium-only assets).

If `--source both` didn't fill the gap from TheGamesDB either, check whether the game's title differs meaningfully between TheGamesDB and your ROM name (e.g. punctuation: a ROM named `Game - Subtitle (USA)` vs. TheGamesDB's `Game: Subtitle`) — TheGamesDB's name search is normalized (region tags and punctuation stripped) before querying, but it can still miss if the base title itself differs between the ROM set and TheGamesDB's listing.

If neither source ever matches well by name for one specific title (a recurring offender, often due to a language barrier — e.g. the scraper's primary listing is in Japanese/French and the fuzzy match against your English ROM name never clears the confidence threshold), stop relying on name matching for that game entirely: look the game up directly on the scraper's own site, copy the ID from the URL, and set a [per-game override](configuration.md#per-game-overrides):

```bat
spindoctor config game-override set "Nintendo DS" "Golden Sun - Dark Dawn (USA)" ^
    --screenscraper-id 5775 --thegamesdb-id 11251
```

Every future `fetch-meta`/`fetch-media` run for that exact game uses the forced ID directly — also available from the GUI's Metadata & Media tab.

## Media / video

### Video plays but has no sound

**Cause:** ScreenScraper's standardised (`video-normalized`) files encode audio as MP3 inside an MP4 container (`mp4a.40.34`). Both macOS AVFoundation (QuickTime, Finder preview) and Windows Media Foundation (used by HyperSpin on Windows 7) expect AAC behind any `mp4a` tag and silently drop an MP3 bitstream — so the video plays but you hear nothing.

SpinDoctor automatically re-encodes the audio to AAC after every video download, but **only when `ffmpeg` and `ffprobe` are installed**. If they are not found the download still succeeds and `fetch-media` prints a yellow warning:

```
⚠ ffmpeg not found — video audio may be silent on macOS and Windows 7.
  Install ffmpeg and place ffmpeg.exe + ffprobe.exe next to spindoctor.exe
  (or set ffmpeg_path in config).
```

#### Check whether ffmpeg is installed

Open a Command Prompt on the cabinet and run:

```
ffmpeg -version
```

- **Version info appears** → ffmpeg is installed. Re-download the video with `--overwrite --apply` and sound should work.
- **`"ffmpeg" is not recognized`** → ffmpeg is not installed; follow the steps below.

#### Install ffmpeg on the cabinet (Windows 7)

1. On any PC with internet access, go to **<https://www.gyan.dev/ffmpeg/builds/>** and download **`ffmpeg-release-essentials.zip`** (the "release" row, "essentials" build). **Do not download the `full` or `full-shared` builds** — they link against a Windows 10 DLL and will not run on Windows 7.
2. Extract the zip. Inside the `bin\` folder you will find `ffmpeg.exe` and `ffprobe.exe`.
3. Copy **both** `ffmpeg.exe` and `ffprobe.exe` into the **same folder as `spindoctor.exe`** on the cabinet. SpinDoctor checks there automatically — no PATH changes needed.
4. Re-download the silent video:
   ```
   spindoctor fetch-media --system <SYSTEM> --game "<GAME>" --types video --overwrite --apply
   ```
   The output should show `downloaded` with no warning, and the file will play with sound.

> **If `ffmpeg.exe` crashes immediately on launch:** Windows 7 may be missing the Universal C Runtime (UCRT). Install Microsoft update **KB2999226** (part of the Visual C++ 2015 redistributable), then retry.

#### If ffmpeg is already installed but sound is still missing

The video on the cabinet was downloaded before ffmpeg was installed. Re-download it with `--overwrite --apply` as shown above to replace the silent file.

### Steam HLS video downloads as a 2–3 second clip (full trailer never completes)

**Symptom:** The downloaded file is only 2–3 seconds long and around 2–3 MB, even though the Steam store page shows a trailer that is over a minute long (e.g. A Boy and His Blob, App 281200, is 1:19). SpinDoctor reports the download as successful — ffmpeg exits 0 and the file is non-empty. From v2.7.12 onward SpinDoctor also prints a yellow `⚠` warning when the HLS output is under 5 MB.

**Cause:** Three concurrent issues in versions before v2.7.12:

1. **fMP4/CMAF audio corruption (before v2.7.11).** Steam has migrated many trailers to fMP4/CMAF HLS segments, where AAC audio is already in MPEG-4 ASC format. The original ffmpeg command applied `-bsf:a aac_adtstoasc` unconditionally, which double-converts audio that is already containerised — corrupting the AAC track and causing ffmpeg to abort the mux partway through.

2. **HTTPS segment URLs blocked (before v2.7.11).** Without `-protocol_whitelist file,http,https,tcp,tls,crypto`, ffmpeg cannot follow the HTTPS segment URLs that Steam's Akamai CDN embeds in the variant playlist. ffmpeg exits 0 after writing whatever it had already buffered.

3. **Audio re-encode timestamp discontinuities (before v2.7.12).** Using `-c:a aac` (re-encode) introduced timing offsets between the copied video track and the re-encoded audio track. For certain CMAF segments these offsets accumulate, and ffmpeg aborts the mux after only the first 2–3 seconds while still exiting 0. Switching to `-c copy` (stream-copy, no re-encode) avoids all timestamp manipulation and lets the MP4 muxer handle format conversion natively.

**Fix:** Upgrade to SpinDoctor v2.7.12 or later, then re-download the affected video with `--overwrite --apply`:

```
spindoctor fetch-steam-media --system "PC Games" --game "<GAME>" --steam-id <ID> \
    --video-index 1 --types video --overwrite --apply
```

The ffmpeg command is now `-protocol_whitelist file,http,https,tcp,tls,crypto -c copy -movflags +faststart`: stream-copy preserves original timestamps, the protocol whitelist enables HTTPS segment fetching, and `+faststart` writes the MP4 moov atom at the start for WMP seek compatibility.

> **If the download still produces a short clip after upgrading to v2.7.12:** You may have downloaded the MP4 highlight clip rather than the full HLS trailer. Run without `--video-index` and check the dry-run listing — candidates labelled `(HLS — full length, needs ffmpeg)` are the complete trailers; `(MP4 — may be highlight clip)` are shorter autoplay clips (~10–15 s). Use the index of the `HLS` candidate. If you are using v2.7.12 but not yet v2.7.14, also check the two sub-sections below for separate audio and best-quality truncation issues.

### Steam HLS video plays with no audio (trailer downloads silently)

**Symptom:** The downloaded MP4 has a correct length and file size (e.g. 52 MB / 1:19) but plays back silently on the cabinet. `ffprobe -select_streams a:0 -show_streams <file>` returns `"streams": []` — zero audio streams were muxed into the file.

**Cause (before v2.7.14):** Steam HLS master playlists deliver audio in a separate `EXT-X-MEDIA TYPE=AUDIO` rendition that is not embedded in the video-only variant playlists. When SpinDoctor selected a quality variant (e.g. 720p) and passed that URL to ffmpeg, the resulting download contained only the video track — no audio had ever been available at that URL. The audio rendition URL is listed separately in the master playlist under `#EXT-X-MEDIA:TYPE=AUDIO,...,URI="..."`.

**Fix:** Upgrade to SpinDoctor v2.7.14 or later. `_pick_hls_variant` now parses `EXT-X-MEDIA TYPE=AUDIO` entries from the master playlist and returns the audio rendition URL alongside the video variant URL. ffmpeg is invoked with a second `-i audio_url` input and `-map 0:v:0 -map 1:a:0` to mux both tracks into the output. Re-download any silently-playing video:

```
spindoctor fetch-steam-media --system "PC Games" --game "<GAME>" --steam-id <ID> \
    --video-index 1 --types video --overwrite --apply
```

### Steam HLS "best quality" download is only ~9 seconds long

**Symptom:** Downloading without `--hls-quality` (or with a cap high enough that the best variant is selected) produces a file that is only ~8–10 seconds long and ~2–3 MB. ffmpeg exits 0 and the SpinDoctor success line shows the file as non-zero, but the `⚠ HLS output looks truncated` warning appears. The ffmpeg output references CMAF segment URLs like `chunk-stream0-XXXXX.m4s`.

**Cause (before v2.7.14):** When no quality cap was set, SpinDoctor passed the master `.m3u8` URL directly to ffmpeg and let ffmpeg pick a variant internally. ffmpeg selects the highest-bandwidth variant, which on Steam is a CMAF/fMP4-based stream. Older Windows ffmpeg builds (the version available for Windows 7) silently abort this stream after approximately 9 seconds of wall-clock data while still exiting 0. The `--hls-quality 720p` (or lower) workaround selected a non-CMAF variant via SpinDoctor's own Python parser, bypassing the problematic ffmpeg auto-selection path — which is why that workaround worked while "best quality" did not.

**Fix:** Upgrade to SpinDoctor v2.7.14 or later. SpinDoctor now always runs explicit variant selection via `_pick_hls_variant`, even when no quality cap is set (using a sentinel of 9999 for "best available"). ffmpeg receives a concrete variant URL rather than the master URL, bypassing the CMAF auto-selection path. Re-download any truncated file:

```
spindoctor fetch-steam-media --system "PC Games" --game "<GAME>" --steam-id <ID> \
    --video-index 1 --types video --overwrite --apply
```

### Steam HLS audio is truncated to ~5 seconds on Windows 7

**Symptom:** The downloaded MP4 has a full-length video track but the audio cuts out after approximately 5 seconds. `ffprobe` shows an audio stream is present (unlike the zero-audio case above), but the audio duration is only a few seconds while the video is full-length.

**Cause (before v2.8.1):** When a Steam trailer uses a separate `EXT-X-MEDIA TYPE=AUDIO` rendition, that audio playlist may consist of CMAF/fMP4 segments (`.m4s` files) with an `EXT-X-MAP` initialization segment. Older Windows ffmpeg builds (the version available for Windows 7) silently truncate CMAF HLS audio after a few seconds when these playlists are passed as a second `-i` input — the same family of CMAF segment demuxer bug that previously caused video to truncate at ~9 s. Unlike video, there is no lower-quality audio rendition to fall back to.

**Fix:** Upgrade to SpinDoctor v2.8.1 or later. SpinDoctor now pre-downloads each audio segment via the Python `requests` session (which handles HTTPS correctly on all platforms), concatenates the init segment and all audio chunks into a temporary plain fMP4 file, and passes that local file to ffmpeg instead of the HLS audio URL. This bypasses the broken CMAF HLS demuxer path entirely. The pre-download falls back to passing the URL directly to ffmpeg if segment fetching fails for any reason. Re-download any affected file:

```
spindoctor fetch-steam-media --system "PC Games" --game "<GAME>" --steam-id <ID> \
    --video-index 1 --types video --overwrite --apply
```

### `audit` reports a slot as present but the file has no content (0 bytes)

A 0-byte stub can land in the Media tree when a download server returns an empty HTTP 200 body, or when a previous download was interrupted before any bytes were written. Prior to v2.7.3 the presence check used `.exists()`, so a zero-byte file would pass and the slot would never be re-downloaded.

Since v2.7.3 `audit.check_media()` uses `stat().st_size > 0` — a zero-byte file is treated identically to an absent one. Running `spindoctor audit` will flag the affected slot, and `fetch-media` will re-download it on the next run without needing `--overwrite`.

If you believe you have zero-byte stubs from an older version, run `audit` and look for slots that are shown as missing even though the file appears to be on disk.

---

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

## Intro Video Randomizer

### `introvideo` commands fail with "intro_randomizer_dir is not set"

Configure the **Intro Video Randomizer directory** — the folder that *contains* `Random.ini`, not the video folder itself — on the Setup tab, or `spindoctor config set intro_randomizer_dir <path>`. See [Command reference → Intro Video Randomizer](commands.md#intro-video-randomizer).

### "Random.ini not found" / "\[Randomize1\] is missing key(s): folder, filetorandomize"

`intro_randomizer_dir` is pointed at the wrong folder, or the third-party randomizer script hasn't been installed/run there yet — SpinDoctor never creates `Random.ini` itself, it only reads and edits one that already exists. Confirm the path in File Explorer, and confirm `Random.ini` has a `[Randomize1]` section with `Folder=` and `FileToRandomize=` keys (SpinDoctor doesn't require `FileList=`/`RandomList=` to already have entries, just the keys to be present — see [Cabinet Architecture Reference → Intro Video Randomizer](cabinet-architecture-reference.md#intro-video-randomizer) for the expected format).

### A video I dropped straight into the folder shows "on disk" but never plays

It's on disk but not registered — SpinDoctor found the file when scanning `Folder=`, but it isn't in `Random.ini`'s `FileList=`/`RandomList=` yet, so the randomizer script doesn't know about it. In the GUI, select that row on the Intro Video tab and click **Register selected** (no re-browsing needed — it registers the file where it already sits). From the CLI, re-run `introvideo add` pointed at the file's existing path: `spindoctor introvideo add "<Folder=>\<filename>" --apply` — since the destination already matches the source, this only registers it, it doesn't copy anything.

### `introvideo add`/`remove` fails with a `backup_dir` error instead of silently backing up somewhere else

`backup_before_modify` is on (the default) and `backup_dir` is configured, but SpinDoctor couldn't actually write to it — an unmounted drive, a permission problem, a typo in the path. This is intentional: rather than silently falling back to writing the backup next to `Random.ini` (surprising, and easy to miss), or letting the underlying error crash with a bare traceback, SpinDoctor raises a clear message naming the exact destination that failed. Fix `backup_dir` (Setup tab, or `spindoctor config set backup_dir <path>`), or turn off `backup_before_modify` if you don't want backups for this cabinet. Nothing is left half-done — for `add`, this is checked *before* any file is copied, so a bad `backup_dir` can't leave a video copied onto disk without being registered.

### Where does the `Random.ini` backup actually go?

`<backup_dir>\IntroVideoRandomizer\Random.ini.<timestamp>.bak` when `backup_dir` is configured; next to `Random.ini` itself (in the Intro Video Randomizer directory) if `backup_dir` is blank. This is the same routing every other SpinDoctor backup uses (LEDBlinky, RocketLauncher configs, HyperSpin XML) — see [Where SpinDoctor stores its files → `backup_dir`](spindoctor-files.md#backup_dir). A multi-file `add`/`remove` call writes one shared backup for the whole batch, not one per file.

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

Read-only. Scans `<HyperSpin>/Tools`, `<RocketLauncher>/Modules`, the emulators tree, Program Files, and the Start Menu for a registry of known tools (Tur-RemoveDupes, FatMatch, FuzzyRename, HyperSync, HyperT00ls, Don's HyperTools, Hypersearch, Sinden, DemulShooter, XPadder, JoyToKey, DS4Windows, XOutput, …) and reports which spindoctor command replaces each one.

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

### ScummVM games launch but show a blank screen or quit immediately after a drive change

**Symptom:** ScummVM launches and then quits after a few seconds, or opens without loading any game. The RocketLauncher log shows the correct ROM path on the new drive (e.g. `romPath := "J:\Games\ScummVM"`) but the game doesn't load.

**Cause:** RocketLauncher's ScummVM module runs in **Standard/Auto launch mode** — it passes the game ID (e.g. `simon1-cd-win`) to ScummVM and lets ScummVM look up the game's folder path from its own config file. That config file is separate from RocketLauncher and is not updated by `generate-config` or any SpinDoctor command:

```
C:\Users\<username>\AppData\Roaming\ScummVM\scummvm.ini
```

Each game entry in this file contains a `path=` line pointing to where the game data lives on disk. When you move games to a new drive, this file still has the old drive letter — ScummVM finds no data at the old path and quits.

**Fix:** Close ScummVM, then open that file in Notepad and do a find-and-replace:

1. Press `Ctrl+H`
2. Find what: `E:\` (or whichever old drive letter the paths use — check `path=` lines in the file)
3. Replace with: `J:\` (your new drive)
4. Click **Replace All**, then save

> **Note:** RocketLauncher's `Rom_Path=` for ScummVM tells RL where to find ROM *archives* (`.7z`, `.zip`) — it does not control where ScummVM reads game data from when running in Standard mode. These are two separate path settings.

### RocketLauncher launches the wrong drive after moving an emulator to a new drive

**Symptom:** After moving an emulator (e.g. Pinball Arcade, MAME) to a different
drive, RocketLauncher throws an AutoHotkey error on launch:

```
Error in #include file "D:\Arcade\RocketLauncher\Lib\Shared.ahk":
Failed attempt to launch program or document:
Action <PinballArcade.exe>
Specifically: The system cannot find the file specified.
```

Despite the error mentioning `Shared.ahk`, the real cause is that the emulator
executable no longer exists at the path RocketLauncher was told to use — the
`#include` wording is just where AHK surfaces the runtime error.

**Why it happens:** `Global Emulators.ini` stores emulator paths relative to the
RocketLauncher directory (`..` = one level up). A relative path always resolves
against the drive RocketLauncher lives on. If the emulator moves to a *different*
drive (e.g. from `D:` to `J:`), the relative path silently points to the wrong
place and the exe is never found.

```ini
; D:\Arcade\RocketLauncher\Settings\Global Emulators.ini
[Pinball Arcade]
Emu_Path=..\Games\PinballArcade\PinballArcade.exe   ← resolves to D:\Arcade\Games\...
                                                        even when the exe is on J:
```

**Option A — absolute path (quick fix):**

Edit `D:\Arcade\RocketLauncher\Settings\Global Emulators.ini` and replace the
relative path with the full path on the new drive:

```ini
[Pinball Arcade]
Emu_Path=J:\Arcade\Games\PinballArcade\PinballArcade.exe
```

This is the simplest fix and is perfectly fine for a dedicated cabinet that isn't
going to be moved to another machine.

**Option B — directory junction (keeps relative paths working):**

Create an NTFS directory junction that makes the new drive's folder appear under
the old `D:` path. RocketLauncher then follows the original relative path without
any ini change.

Run this once in an elevated (`Run as Administrator`) Command Prompt:

```bat
mklink /J "D:\Arcade\Games\PinballArcade" "J:\Arcade\Games\PinballArcade"
```

A junction is a filesystem-level redirect — every program (including
AutoHotkey/RocketLauncher) sees it as a real folder, unlike a Windows shortcut
(`.lnk`) which only works at the application level and is ignored by programs
that access the filesystem directly.

> **No built-in Windows 7 UI for junctions.** The free shell extension
> [Link Shell Extension](http://schinagl.priv.at/nt/hardlinkshellext/linkshellextension.html)
> adds junction creation to Explorer's right-click menu and works on Windows 7.

After creating the junction, leave `Global Emulators.ini` on its original
relative path — no further changes needed.

**Which option to choose:**

| | Option A (absolute path) | Option B (junction) |
|---|---|---|
| Effort | Edit one ini line | One `mklink` command (admin) |
| Portable to a new machine | No — path is machine-specific | No — junction must be re-created |
| Keeps relative-path convention | No | Yes |
| Invisible infrastructure risk | None | Junction folder can be accidentally deleted |

For a dedicated single-machine cabinet, Option A is simpler and just as correct.
Use Option B if you prefer relative paths in your ini files or have multiple
emulators that all moved to the same new drive.

**How to confirm the fix:** Relaunch the game from HyperSpin. The RocketLauncher
log (`D:\Arcade\RocketLauncher\RocketLauncher.log`) should show `emuFullPath`
resolving to the correct new path, and the AutoHotkey error will not appear.

---

### After a migration, wheel art is missing

Run `spindoctor doctor` to see which paths failed validation. If you migrated with `--keep-source` and later removed the originals, restore the missing component from a `backup`. Hardcoded absolute paths inside HyperSpin XML are not rewritten by `migrate` (rare in practice — most XMLs reference games by name, not path).

### Drive letter changed after restoring a backup

```bat
spindoctor backup restore --backup E:\Backups\... --use-current-paths --apply
```

`--use-current-paths` writes restored files to whatever paths `config.json` currently has, instead of where the backup originally came from.

### My new drive is FAT32 / exFAT and the wheel rebuild is slow

`fav rebuild` and `stats-report build-wheel` default to hardlinks, which need NTFS / ext4 / APFS. On FAT32 / exFAT they fall back to copy automatically (via `auto` mode), which doubles disk use. Either pass `--media-mode copy` explicitly to make the fallback intentional, or move the wheel target to an NTFS volume.

---

## Dolphin / GameCube

### GameCube games fail with "error waiting for the window FPS ahk_class ..." (any variant)

**Symptom A (fails almost immediately):** Dolphin opens, the game starts running (visible on
the taskbar), but RocketLauncher times out within seconds/at the fade animation's end and
shows *"There was an error waiting for the window FPS ahk_class ..."*. Games work fine when
launched directly from Dolphin.

**Symptom B (fails after ~2 minutes):** The game launches and plays completely normally —
audio, controls, everything works — for about two minutes. Then RocketLauncher pops the same
*"error waiting for the window"* error, plays an error sound, and HyperSpin snaps back to the
foreground. The game is still running behind it: audible, and Alt-Tabbing to it works fine.
This is the same underlying bug as Symptom A, just observed on a cabinet where the
`Wait(120)` timeout fix (below) is already applied — RL keeps polling for the full 120 seconds
before giving up, instead of failing right when the fade animation ends.

**Cause:** Dolphin's window class name changed because the emulator build was upgraded, but
`Dolphin.ahk` still looks for the previous build generation's class string. This has happened
across at least three Dolphin generations on this cabinet:

| Generation | UI framework | Window class |
|---|---|---|
| 2017-era Ishiiruka | wxWidgets | `wxWindowNR` |
| 5.0-12188 … 5.0-17000ish | Qt 5.15 | `Qt5150QWindowIcon` |
| CalVer builds (e.g. `2606`) | Qt 6.5.1 | `Qt651QWindowIcon` |

Any time Dolphin is upgraded across a Qt version boundary, this string changes again and the
module needs to be updated to match — see the diagnostic recipe below rather than assuming
it's always the wx→Qt5 jump.

**Fix — stop matching on the window class entirely.** Rather than swapping in the new Qt
class string (which just breaks again on the next Dolphin upgrade), edit
`D:\Arcade\RocketLauncher\Modules\Dolphin\Dolphin.ahk` to match Dolphin's window by **process
name** (`ahk_exe Dolphin.exe`) instead of by class. The exe name can't change across
Dolphin/Qt versions, so this survives future upgrades with no further edits. See the
[Dolphin architecture section](cabinet-architecture-reference.md#rl-module-compatibility-when-upgrading-build-generation)
for the exact block to replace and the reasoning (including a related dead-code bug this
also fixes).

If you'd rather do the minimal-diff version instead (swap the class string and accept it'll
need updating again next time): open `RocketLauncher.log` and look at the
`MiscUtils.GetActiveWindowStatus` debug line right before the `ScriptError` line — it shows
the game window's *actual* current title/class, no AutoHotkey Window Spy needed — then
replace every occurrence of the old class string in `Dolphin.ahk` with that one.

---

### Dolphin opens to the game browser instead of launching the selected game

**Symptom:** Dolphin opens showing its game list. The correct game is listed
but does not auto-start. Games launch fine when double-clicked inside Dolphin.

**Cause:** The RL module launches Dolphin with Windows-style flags (`/b /e`).
Qt-based Dolphin (5.0-12188+) only accepts POSIX-style flags (`-b -e`); it
ignores the `/b /e` arguments and opens normally without a game.

**Fix:** In `Dolphin.ahk`, find:

```ahk
primaryExe.Run(" /b /e """ . romPath . "\" . romName . romExtension . """")
```

Change to:

```ahk
primaryExe.Run(" -b -e """ . romPath . "\" . romName . romExtension . """")
```

---

### "No valid roms found in the archive" for a .rvz inside a .zip

**Cause:** `.rvz` is not in the `Rom_Extension=` list RocketLauncher uses to
validate files inside archives.

**Fix (preferred):** Unzip the `.rvz` files directly into the ROM folder — `.rvz`
is already compressed and does not benefit from re-zipping. Then add `rvz` to
`Rom_Extension=` in
`D:\Arcade\RocketLauncher\Settings\Nintendo Gamecube\Nintendo Gamecube.ini`.

**Fix (keep the zip):** Add `rvz` to `Rom_Extension=` in `Global Emulators.ini`
under `[Dolphin Ishiiruka]`.

Run `spindoctor check-archive-ext --system "Nintendo Gamecube"` to verify all
inner extensions are covered before launching.

---

### "Your module does not contain a CloseProcess section"

**Cause:** `Dolphin.ahk` is corrupted — it contains HTML (e.g. from a file-sharing
site's landing page) instead of AHK code. This happens when a "Proceed to download"
warning page is saved as the file rather than the actual AHK module.

**Diagnosis:** Check the file size. A valid `Dolphin.ahk` is ≈ 32 KB. If it is
≈ 5 KB, open in Notepad — if it starts with `<!doctype html>` the wrong file was saved.

**Fix:** Re-copy the correct `Dolphin.ahk` via USB stick or network share. Avoid
web file-sharing services that show an intermediate landing page; the page HTML
gets saved instead of the file if the download link isn't clicked through correctly.

---

### GameCube controller not responding when launched through HyperSpin

**Symptom:** Controller works when Dolphin is launched directly, but stops responding when
the same game is launched through HyperSpin. The problem persists even when Dolphin is
launched directly afterward, until the computer is rebooted. Dolphin's controller list shows
`[disconnected] DInput/0/Wireless Controller` instead of `XInput/0/Gamepad`.

**Cause:** DS4Windows — which converts the PS4 controller into a virtual XInput device —
is tied to HyperSpin's process lifetime and exits when HyperSpin closes. Without DS4Windows
running, the `XInput/0/Gamepad` virtual device disappears. Dolphin's GCPad profile is bound
to `XInput/0/Gamepad`, so it loses the controller. The raw DInput device
(`DInput/0/Wireless Controller`) remains visible but is not what Dolphin's profile maps to,
so buttons do not register even though the device appears connected.

**Fix:**
1. Configure DS4Windows to start at Windows login independently of HyperSpin — add it to
   the Startup folder (`shell:startup`) or create a Task Scheduler entry set to run at logon.
2. Confirm Dolphin's GCPad Port 1 is set to `XInput/0/Gamepad` (not `DInput/0/Wireless Controller`).

**Diagnosis:** Press `Win+B` to access the system tray while HyperSpin's taskbar is hidden.
If DS4Windows is not listed in the tray, it has exited. See
[Controller input — DS4Windows and XInput](cabinet-architecture-reference.md#controller-input--ds4windows-and-xinput)
for the full architecture reference.

---

### Loading screen reaches 100% then errors — but the game is actually running in the background

**Symptom:** The RocketLauncher fade/loading screen fills its progress bar to 100% and then
shows *"There was an error waiting for the window FPS ahk_class Qt5150QWindowIcon"*. The game
is audible (music plays, controller rumbles) and Dolphin is visible on the taskbar — but
RocketLauncher has already given up and returned to HyperSpin.

**Cause:** Qt-based Dolphin (5.0-12188+) takes longer to start emulating than the fade
animation lasts. When the fake progress bar reaches 100% RocketLauncher checks whether the
game window has appeared yet; if not, it fires the error. The window check (`emuGameWindow.Wait()`)
has no explicit timeout so it defers to the animation duration — typically 45–60 seconds —
which is shorter than some games' boot time (Animal Crossing takes ≈ 50 s).

**Fix:** Edit `D:\Arcade\RocketLauncher\Modules\Dolphin\Dolphin.ahk`. Find:

```ahk
emuGameWindow.Wait()
emuGameWindow.Get("ID")
emuGameWindow.WaitActive()
```

Change to:

```ahk
emuGameWindow.Wait(120)
emuGameWindow.Get("ID")
```

Two changes: add a 120-second explicit timeout so the wait outlasts the animation, and
**remove `WaitActive` entirely** (see next entry for why).

---

### After the game loads, HyperSpin stays in front — the game is audible but not visible

**Symptom:** The loading screen disappears but the game window stays hidden behind HyperSpin.
Sound plays, controller LEDs light up, but the screen never switches to the game. Alt-Tab
shows Dolphin running. If you Alt-Tab to the game, it works — but pressing the back button
immediately quits back to HyperSpin.

**Cause:** `emuGameWindow.WaitActive()` waits for Dolphin's rendering window to become
the focused window. But RocketLauncher's own CoverFE overlay is an always-on-top AHK window
that sits in front of everything — Dolphin can never naturally gain focus while the overlay
exists. `WaitActive` hangs indefinitely (or errors after its timeout), so RL never reaches
the lines that remove the overlay (`HideAppEnd`) and activate Dolphin (`emuGameWindow.Activate()`).
The back-button quitting is a secondary symptom: if `WaitActive` eventually fires an error,
RL reloads the HyperSpin Xpadder profile before the user reaches the game — that profile maps
the back button to Escape, which quits Dolphin.

**Fix:** Remove `emuGameWindow.WaitActive()` from `Dolphin.ahk` as shown in the entry above.
With the line gone, RL falls through immediately to `emuGameWindow.Activate()` and `HideAppEnd`,
which remove the overlay and bring Dolphin to the front in the correct sequence — the same
result as Alt-Tab, but automatic.

---

### Dolphin launches windowed instead of fullscreen — title bar visible at the top

**Symptom:** The game runs but a window title bar is visible at the top of the screen, pushing
the game content down slightly. Bezels are misaligned. Running Dolphin directly (without
HyperSpin) goes fullscreen correctly.

**Cause:** The RL module contains a ternary expression that converts the `Fullscreen` variable
from `"true"` to `"True"` before writing it to `Dolphin.ini`. Due to how AHK 1.1 evaluates
the `If … ? … :` form inside an assignment, the variable ends up as `"False"` instead, and
`Dolphin.ini` keeps `Fullscreen = False`. Because the module runs before Dolphin opens, the
incorrect value is already on disk when the emulator reads its config.

**Fix:** In `D:\Arcade\RocketLauncher\Modules\Dolphin\Dolphin.ahk`, find:

```ahk
dolphinINI.Write(Fullscreen, "Display", "Fullscreen", 1)
```

Change to:

```ahk
dolphinINI.Write("True", "Display", "Fullscreen", 1)
```

Also set the value directly in `C:\Users\User\Documents\Dolphin Emulator\Config\Dolphin.ini`
right now so it takes effect before the next launch:

```ini
[Display]
Fullscreen = True
```

---

## ScummVM

### ScummVM window appears blank and requires a click to display

**Symptom:** ScummVM launches but the window stays black until you click on it. This happens intermittently, not on every launch.

**Cause:** ScummVM's SDL window opens at its default 640×480 size, then switches to fullscreen. Windows drops focus during this transition — even though RocketLauncher calls `WaitActive` on the window, the fullscreen switch happens after that and steals focus back to nothing.

**Fix:** Create a RocketLauncher User Function file that clicks the window once it is active:

```
D:\Arcade\RocketLauncher\Lib\User Functions\ScummVM\Emulators\ScummVM.ahk
```

Contents:

```ahk
StartEmu:
    Sleep, 1000
    WinActivate, ahk_class SDL_app
    Sleep, 200
    Click
Return
```

RocketLauncher picks this file up automatically — no other config changes are needed. The `Sleep, 1000` gives ScummVM time to complete its fullscreen transition before the click is sent. If the blank screen is shorter or longer on your cabinet, adjust this value (try 500–1500 ms).

> **Note:** The `User Functions` folder and its subfolders may not exist yet. Create them in Windows Explorer if needed: `RocketLauncher\Lib\User Functions\ScummVM\Emulators\`.

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

### Custom Wheels tab → Schedule auto-refresh fails with "access denied"

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
