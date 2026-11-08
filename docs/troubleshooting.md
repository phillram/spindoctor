# Troubleshooting

Common problems and their fixes. For deeper recovery (rolling back a migration, restoring an XML, reversing a curate), see [Workflows → Recovery](workflows.md#recovery-from-mistakes).

## Install / startup

### Double-clicking `spindoctor.exe` flashes a window that closes instantly

That's the program working correctly — `spindoctor.exe` prints `--help` and exits when run with no arguments, and Windows tears the cmd window down the moment it exits. Three options:

- **Double-click `spindoctor-gui.exe`** instead — that's the supported windowed launcher.
- Open `cmd.exe` first (`Win+R` → `cmd` → Enter), `cd` to the install folder, then run `spindoctor.exe …` with arguments.
- Use the bundled `.bat` wrappers in [`scripts/`](https://github.com/phillram/spindoctor/tree/main/scripts) — they `pause` on error so the window stays open.

### `spindoctor: command not found`

The console scripts didn't end up on PATH. Re-run `pip install -e .` from the repo root and confirm Python's `Scripts\` directory is on your `Path` environment variable. As a fallback, `python -m spindoctor.cli ...` works without the entry point.

If you're using the prebuilt Windows binaries (no Python install), make sure the folder containing `spindoctor.exe` is on `PATH`, or invoke by full path (`C:\spindoctor\spindoctor.exe systems`). The GUI launcher embeds every worker and relaunches itself with `--run-tool`, so it works alone without `PATH` configured — handy for cabinets where you don't want to touch environment variables.

### `spindoctor-gui` opens but every button errors with "Binary not found"

For Windows binary installs, this indicates an older GUI: v3 embeds every worker and all bundled deployment media in `spindoctor-gui.exe`, with no helper EXEs required. Replace the GUI with the current release EXE; if a command still fails, check its error in the Output panel.

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

### `audit` reports 0 ROMs (or every game missing) for a wheel whose games launch fine

`spindoctor audit` shows `Total ROMs: 0` and every database game under **DB
entries with no ROM**, or thousands of **ROMs not in database**, for a wheel
whose games launch normally.

**Cause:** `audit` used to look for ROMs only in `<roms_dir>\<System>`, with
SpinDoctor's own guess at the system's file extensions. RocketLauncher, which
actually launches the games, uses the wheel's `Rom_Path` and `Rom_Extension`.
The two disagree when:

- the games sit in a subfolder, such as `J:\Games\Sega Dreamcast\roms`;
- `Rom_Path` lists more than one folder, such as
  `J:\Games\Sony Playstation|J:\Games\Sony Playstation\MultiDisc`;
- the folder isn't named after the wheel, or several wheels point at the MAME
  folder;
- `Rom_Extension` differs from SpinDoctor's guess (`.pbp` images, MAME `.txt`
  placeholders).

**Fix:** update SpinDoctor and make sure `rocketlauncher_dir` is set
(`spindoctor config set rocketlauncher_dir D:\Arcade\RocketLauncher`). `audit`
then reads each wheel's `Rom_Path` and `Rom_Extension` the way RocketLauncher
does. A folder that other wheels also use is shown as **Shared ROM folder**:
only the wheel's own games are taken from it, so the rest of the MAME folder
no longer shows up as ROMs missing from a smaller wheel's database.

If `audit` still reports games with no ROM, run `spindoctor doctor` to check
the launch settings (PCLauncher and `Skipchecks` can launch without a ROM
file). See *"Cannot find Rom … in any Rom_Paths provided", or a wheel opens
but no game launches* under [Wheels](#wheels).

## Metadata / scraping

### Reading `scraper.log`

Every ScreenScraper and TheGamesDB HTTP call SpinDoctor makes is logged to:

```
%USERPROFILE%\.spindoctor\scraper.log
```

(On macOS/Linux: `~/.spindoctor/scraper.log`. See [SpinDoctor Files](spindoctor-files.md) for the full list of files and their locations.)

The log rotates at 512 KB with two backups (`scraper.log.1`, `scraper.log.2`). Scraper passwords and API keys are redacted (`***`), but account identifiers and other context can remain. Share only a reviewed, relevant excerpt; see [Privacy and sharing diagnostics](privacy.md#sharing-logs-and-reports).

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

### `fetch-meta` reports `Expecting value: line 1 column 1 (char 0)`

**Symptom:** every game in the system fails with a line like:

```
  Error [Crazy Taxi 2-in-1]: ScreenScraper: ScreenScraper search failed: Expecting value:
  line 1 column 1 (char 0) (HTTP 200, raw: Erreur : API fermée pour les non membres)
```

**Cause:** the API replied `HTTP 200` with a plain-text body instead of JSON, so the JSON decoder failed on the first character. ScreenScraper does this for login, thread-limit and maintenance conditions. The text after `raw:` is the API's own message and names the real cause. `empty response body` means the API sent nothing at all.

**What to check:**

1. A login message (`Erreur de login`, `Vérifier vos identifiants`) — see [403 from ScreenScraper or TheGamesDB](#403-from-screenscraper-or-thegamesdb) below, causes 1 and 3.
2. A quota or thread message — see [ScreenScraper rate-limiting](#screenscraper-rate-limiting).
3. `empty response body`, or a body that looks like an HTML page — ScreenScraper is overloaded or down. Retry later, or run `--source thegamesdb` to keep working from the other provider.

With `--source both`, a failure on one provider does not stop the other: games that TheGamesDB resolves are still applied. The full request and response for each call is in `scraper.log`.

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

**Fix — run `install-tools` once, with the helpers you want on the wheel:**

```bat
spindoctor install-tools --tool refresh-favorites,refresh-recently-played,refresh-most-played,refresh-all --add-to-system Toolkit --apply
```

This writes everything RocketLauncher and PCLauncher need in one step:

| File written | Purpose |
|---|---|
| `Modules/PCLauncher/Toolkit/*.bat` | The helpers you picked |
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
spindoctor install-tools --tool refresh-all --add-to-system Toolkit --apply
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

### "Cannot find &lt;System&gt;.ini" when *selecting* a newly added wheel (e.g. Recompiled)

The wheel appears on the Main Menu carousel (logo, video, title all show) and
its game is in the Games tab, but choosing the wheel throws **"Cannot find
&lt;System&gt;.ini"** and it never opens. This is HyperSpin's own error about
its per-system settings file at `D:\Arcade\Settings\<System>.ini` (the HyperSpin
`Settings\` folder — **not** `RocketLauncher\Settings\`, which is a separate
folder that also holds a same-named `.ini` and is unrelated to this error).

**Cause:** HyperSpin requires `Settings\<System>.ini` to exist before it will
open a wheel as a sub-menu. The synthetic-wheel rebuilds (`fav rebuild`,
`recent rebuild`, `stats build-wheel`) write this file automatically, but a wheel
added *only* through `mainmenu add` — most notably **Recompiled**, which has no
rebuild path — previously never got one.

**Fix — re-run the add (`mainmenu add` now writes this file for you):**

```bat
spindoctor mainmenu add "Recompiled" --apply
```

`add-system` / `add-pc-system` write it too. The write is idempotent — it only
creates the file when it's missing, so an existing HyperHQ theme INI is never
touched.

**Manual one-liner (any version):** create `D:\Arcade\Settings\<System>.ini`
with the minimal content HyperSpin needs (or copy a working wheel's INI, e.g.
`Recently Played.ini`):

```ini
[exe info]
hyperlaunch=true

[filters]
parents_only=false
```

---

### A game from a synthetic wheel (Favorites/Recently Played/Most Played) plays with sound, but the screen stays frozen on RocketLauncher's "Loading Complete" fade screen

You can hear the game running, but the picture never appears — RocketLauncher's
fade/loading overlay is stuck on screen, and Alt-Tab doesn't help because that
overlay is always-on-top. This is specific to launching through a synthetic
wheel; the same game launched from its native wheel works fine.

**Cause:** synthetic wheels run two RocketLauncher instances (see
[Cabinet Architecture Reference → Recursive RocketLauncher Launch](cabinet-architecture-reference.md#recursive-rocketlauncher-launch--why-and-how)).
The first instance keeps the fade/loading overlay up until it detects the
emulator's window by matching the `FadeTitle=` value SpinDoctor writes against
the emulator's actual window title (see
[Cabinet Architecture Reference → `FadeTitle=` required](cabinet-architecture-reference.md#critical-fadetitle-required-to-fix-error-waiting-for-window-ahk_pid-xxxx)
for the full mechanism). SpinDoctor defaults `FadeTitle` to the
emulator's registered name — which works for the overwhelming majority of
emulators, because their window title contains their name. It fails for any
emulator whose window title does **not** contain its name — most notably
**Daphne**, an SDL 1.2 laserdisc emulator that never sets a window caption, so
its window is always titled `SDL_app` regardless of which game or system is
running. `FadeTitle=Daphne` never matches `SDL_app`, so the overlay never
clears.

**Fix:** SpinDoctor v2.10.3+ ships `"Daphne": "SDL_app"` in the built-in
correction table (`EMULATOR_WINDOW_TITLES` in `rocketlauncher.py`), so this is
fixed automatically for Daphne — just rebuild the affected synthetic wheel(s)
(`fav rebuild --apply`, `recent rebuild --apply`, or `stats-report build-wheel
--apply`) after upgrading.

If you hit this with a **different** emulator whose window title doesn't
contain its name, add a correction yourself — no SpinDoctor upgrade needed:

```bat
spindoctor emulator-title set "<Emulator Name>" "<Actual Window Title Fragment>"
```

Then rebuild the wheel so the new `FadeTitle=` value is written into its
PCLauncher INIs. Find the actual window title by launching the emulator
natively and checking `MiscUtils.GetActiveWindowStatus` in
`RocketLauncher.log` — it logs the live window `Title:`/`Class:` right before
`WinWait`/`WinWaitActive` calls.

**If you're typing the `emulator-title set` command into the GUI's Console
tab on Windows,** wrap arguments in quotes only when they contain spaces —
`spindoctor emulator-title set Daphne SDL_app` — since GUI versions before the
fix in the same release retained literal quote characters in quoted
arguments, silently storing a corrupted key that never matched anything. Run
`spindoctor emulator-title list` afterward and confirm the listed emulator
name and window title have **no** quote marks around them.

If you rebuilt the wheel and the fix still doesn't seem to take, fully
restart HyperSpin (or reboot the cabinet) before retesting — a stale
RocketLauncher/HyperSpin session can hold onto old state and mask a config
change that already succeeded.

---

### Can I edit favorites from inside HyperSpin?

HyperSpin's built-in F-key writes per-system favorite lists. Run `spindoctor fav sync` to merge those into the cross-system Favorites store, then `spindoctor fav rebuild --apply`. For explicit add/remove, use `spindoctor-fav add` / `remove`.

### Does favoriting a game double its disk usage?

No — by default media is hardlinked from the source system into `Media/Favorites/`. Both pathnames point at the same bytes on NTFS. Pass `--media-mode copy` if you're on a filesystem that doesn't support hardlinks (FAT32, exFAT). See [Configuration → Filesystem considerations](configuration.md#filesystem-considerations).

### How is "Most Played" different from "Recently Played"?

Both read the same RocketLauncher `Statistics.ini` files. **Recently Played** sorts by `Last_Played` and shows the last N games launched. **Most Played** sorts by `Total_Time_Played` and shows where you've actually spent the most hours. Build it with `spindoctor stats-report build-wheel --apply`.

### How do I get cross-system "Recently Played" working?

Automatic — `spindoctor recent rebuild --apply` reads RocketLauncher's `Statistics.ini` files (which RocketLauncher writes on every game launch). Schedule it at log-on or run from the Tools menu — see [Standalone tools](standalone-tools.md).

### "Cannot find Rom … in any Rom_Paths provided", or a wheel opens but no game launches

The wheel opens and scrolls normally, but choosing a game (every game, or just
some of them) drops straight back to the wheel, or RocketLauncher shows
**"Cannot find Rom `<name>` in any Rom_Paths provided … with any provided
Rom_Extension …"**.

**Cause:** RocketLauncher looks for each game as `<folder>\<name>.<ext>` or
`<folder>\<name>\<name>.<ext>`, for every folder in the system's `Rom_Path` and
every extension in `Rom_Extension`. It doesn't search any deeper. The usual ways
this breaks:

- **`Rom_Path` points at a parent folder.** For example
  `Rom_Path=J:\Games\Sega Dreamcast` while every game sits in
  `J:\Games\Sega Dreamcast\roms`. Either move the files up into
  `J:\Games\Sega Dreamcast` (a flat game folder), or point `Rom_Path` at the
  subfolder.
- **A second folder isn't listed.** Multi-disc games kept in a `MultiDisc\`
  folder (or gun games in `_Gun Games\`) must be added to `Rom_Path`,
  separated with `|`:

  ```ini
  Rom_Path=J:\Games\Sony Playstation|J:\Games\Sony Playstation\MultiDisc
  ```

- **MAME alternate-name placeholders were deleted.** Wheels such as a
  4-player wheel list games under alternate names (`xmenxbox`,
  `3stooges2play`). The MAME module maps each one to the real ROM through
  `RocketLauncher\Modules\MAME\MAME.ini` (`[xmenxbox]` /
  `MameRomName = xmen`), but RocketLauncher first has to find a file with the
  alternate name: an empty `xmenxbox.txt` in the MAME ROM folder, with `txt`
  in the emulator's `Rom_Extension`. Clearing out "empty junk files" from
  the ROM folder breaks every one of those games.
- **The drive letter no longer exists.** `Rom_Path` still points at the old
  drive after a migration or a restore. This includes a PCLauncher wheel's
  placeholder-INI folder (`Rom_Path=…\Modules\PCLauncher\<System>`).
- **A game borrows another system's settings.** A `System=` line in the
  wheel's `RocketLauncher\Settings\<System>\Games.ini` makes RocketLauncher use
  that other system's `Rom_Path` (and its `Skipchecks`) for the game, so a
  broken `Rom_Path` there breaks the game here too.

**Find them:** run `spindoctor doctor`. Its **ROM paths** check lists every
`Rom_Path` folder that doesn't exist and, per wheel, how many games
RocketLauncher can't find, with an example or two; games that borrow another
system's settings get their own "Games via `<System>`" row. The `fix:` line
names the settings file to edit, the subfolder holding most of the missing
games (move the files up, or add the subfolder to `Rom_Path`), or the `.txt`
placeholders to recreate. Wheels switched off on the Main Menu are checked too,
but only reported as INFO.

**Fix:** correct `Rom_Path` (and `Rom_Extension` if needed) in
`RocketLauncher\Settings\<System>\Emulators.ini` `[ROMS]` (or the flat
`RocketLauncher\Settings\<System>.ini` `[Settings]`), or in RocketLauncherUI.
For MAME alternate names, recreate the empty `<name>.txt` files. Then re-run
`spindoctor doctor` to confirm the wheel shows `N games OK`. See
[Cabinet Architecture Reference → Multiple ROM folders and MAME alternate-name placeholders](cabinet-architecture-reference.md#multiple-rom-folders-and-mame-alternate-name-placeholders).

### A game won't launch: AutoHotkey says "Failed attempt to launch program or document"

A RocketLauncher User Functions file (`RocketLauncher\Lib\User Functions\...`)
runs a program that isn't there any more: a helper that was moved, uninstalled
or archived, such as a key mapper, gun software or a vendor tool. AutoHotkey
stops at that `Run` line, so the game never starts.

**Find it:** run `spindoctor doctor`. Its **User Functions** check names the
file, the line and the missing path.

**Fix:** correct the path, or comment the line out with `;` if the program is
gone for good. When you retire a helper program, comment its `Run` lines out
*before* removing it, so no launch looks for it.

### Every pad press moves the HyperSpin menu twice, but only after playing certain games

Something besides your normal pad mapping is turning presses into keys in
HyperSpin. The usual cause is a key mapper (JoyToKey, Xpadder, antimicro)
started from a RocketLauncher User Functions file, either started for a game
and never closed, or started again as the game ends to load a "HyperSpin"
profile. If DS4Windows Auto Profiles (or another mapper) already map the pad
in HyperSpin, each press now arrives twice. DS4Windows doesn't hide the real
controller from other programs unless its exclusive mode is on, so a mapper
can read the pad while DS4Windows maps it too.

**Find it:** run `spindoctor doctor`. Its **User Functions** check lists each
file and line that starts a key mapper as the game ends, or starts one that
nothing closes. After quitting a game, Task Manager shows it still running.

**Fix:** keep one mapper for the menus. If DS4Windows Auto Profiles already
handle HyperSpin, comment out (`;`) the mapper's `Run` lines in those files.
Otherwise close it when the game ends, in `PostExit()`:
`Process, Close, JoyToKey.exe` (or the mapper you use). See
[Controller input](controller-input.md) for the DS4Windows setup.

### A game boots, but the panel's Coin and Start do nothing (often driving or gun games)

The game's own settings bind Coin and Start to a device's buttons only: a
steering wheel, pad or gun it was once set up for. MAME and Supermodel keep one
binding per input, and a game's own cfg or `[ <game> ]` section replaces the
folder-wide one, so the key your panel sends never reaches it. Other games in
the same emulator work, because they use the folder-wide keys. If the device
has been unplugged since, MAME rewrites the game's cfg as it exits, with
`JOYCODE_1_UNKNOWN_SWITCH` in place of each binding it can't place.

**Find it:** run `spindoctor doctor`. Its **Coin/Start** check lists the games
per emulator, and why each one can't be pressed from a key ("joystick only", "a
device MAME no longer finds").

**Fix (MAME):** with MAME closed, add a key to the `COIN1` / `START1` port in
`cfg\<game>.cfg`, keeping the device for when it's plugged in:
`KEYCODE_5 OR JOYCODE_1_BUTTON9`. Or delete those `<port>` entries so
`cfg\default.cfg` applies. Edit only while MAME is closed: it saves the file
when the game exits. **Fix (Supermodel):** add a `KEY_` to `InputCoin1` /
`InputStart1` in the game's section of `Config\Supermodel.ini`, or delete the
line so `[ Global ]` applies. Back the files up first; a device that comes
back later needs its old bindings.

### A wheel shows no games, but RocketLauncher's ROM checks pass

The wheel opens empty in HyperSpin (or shows only a few of its games), though
its database lists them, and `doctor`'s **ROM paths** check and `audit` find
every ROM.

**Cause:** HyperSpin's own **ROMs only** filter. With `roms_only=true` under
`[filters]` in `<hyperspin_dir>\Settings\<System>.ini`, HyperSpin lists only
the games it finds as `<rompath>\<name>.<ext>`, using `rompath` and
`romextension` (comma-separated) from `[exe info]` of the same file.
RocketLauncher never reads that file: it launches from its own `Rom_Path`. So
after a ROM-drive move, `generate-config` puts RocketLauncher's `Rom_Path` on
the new drive, while `rompath` still names the old one (`J:\Games\AAE` instead
of `E:\Games\AAE`) and HyperSpin finds no games at all. A `romextension` that
doesn't match the files (`zip` while the games are `.7z`) does the same.

**Find it:** run `spindoctor doctor`. Its **HyperSpin ROMs only** check lists
each wheel with `roms_only=true` whose `rompath` is empty, missing or holds
none of its games. The `fix:` line names the file and gives a folder that holds
the games when it finds one.

**Fix:** in `<hyperspin_dir>\Settings\<System>.ini`, set `rompath=` under
`[exe info]` to the wheel's real ROM folder (and correct `romextension=` if
needed), or set `roms_only=false` under `[filters]` to list every database
game (HyperHQ edits the same file). A relative `rompath` is read from the
HyperSpin folder.

### One game shows text instead of its wheel logo (and plays no video)

Every other game on the wheel has its logo, and the game's wheel image is in
`Media\<System>\Images\Wheel\`, yet HyperSpin shows its name as text, plays no
video and uses the default theme. The game still launches.

**Cause:** its name in the wheel's database starts or ends with a space, for
example `<game name="Some Hack V2 ">`. HyperSpin looks up the wheel art
(`Some Hack V2 .png`), video and theme under the name exactly as written, but
the media was saved under the trimmed name (`Some Hack V2.png`), as scrapers
and SpinDoctor's own media downloads do. RocketLauncher uses the name as
written too, so the ROM is named `Some Hack V2 .nes` and launches fine.

**Find it:** run `spindoctor doctor`. Its **Spaces in game names** check lists
those names per wheel, and says which games have media only under the trimmed
name.

**Fix:** with HyperSpin closed, remove the spaces around the name (and its
`<description>`) in `Databases\<System>\<System>.xml`, then rename the ROM file
to match (`Some Hack V2 .nes` → `Some Hack V2.nes`), and any media saved under
the old name. Back up the XML first.

### Refresh All (or Refresh Favorites) does nothing after upgrading SpinDoctor

Running a Refresh helper from HyperSpin's Tools menu or a Toolkit wheel no
longer rebuilds Favorites, Recently Played or Most Played, and a scheduled task
that runs `Refresh All.bat` fails silently. Every other `doctor` check passes.

**Cause:** `install-tools` writes the helpers with the full path of the
SpinDoctor EXE that ran it, for example `start "" /B /WAIT
"D:\Tools\spindoctor-win10-v3.0.0\spindoctor.exe" --run-tool spindoctor-fav
rebuild --apply` (v2 named `spindoctor-fav.exe` in its install folder).
Portable releases unzip into a folder of their own, so once the old folder is
removed the helpers run a program that isn't there.

**Find it:** run `spindoctor doctor`. Its **SpinDoctor helpers** check lists
each folder whose helpers run a program that no longer exists, with the
`install-tools` command that rewrites them on its `fix:` line.

**Fix:** re-run `install-tools` from the new install, the way it was first
run and with the same helpers: for example
`spindoctor install-tools --tool refresh-all` for the Tools menu, or
`spindoctor install-tools --tool refresh-all --add-to-system Toolkit --apply`
for a Toolkit wheel (with `--output-dir <folder>` if one was used). The `fix:`
line names the helpers it found. Keeping SpinDoctor in a folder whose name has
no version number avoids this on later upgrades.

### Shut Down Cabinet (or Restart Cabinet) counts down, then HyperSpin comes back instead

The countdown ran to zero and HyperSpin closed, but a moment later HyperSpin
started again and the cabinet stayed on.

**Cause:** Windows refused the shutdown or restart, so `spindoctor toolkit
shutdown` (or `restart`) started HyperSpin again rather than leave the cabinet
on the desktop. Common reasons: another shutdown or restart already scheduled,
an update installing, or a policy that stops this account shutting the PC down.

**Find it:** the last lines of `%USERPROFILE%\.spindoctor\toolkit.log` show
`shutdown.exe failed (exit code N)`. Run `shutdown /s /f /t 0` (or `/r`) in a
console to see Windows' own message for that code.

**If the countdown never appears** (no `countdown started` line in
`toolkit.log`): the helper runs SpinDoctor by its full path, like the Refresh
helpers above, so run `spindoctor doctor` and look at **SpinDoctor helpers**.

**If Esc doesn't cancel:** another program already holds Esc as a system-wide
hotkey, so the countdown only sees Esc while it has the focus. Alt+F4 on the
countdown cancels too.

**If the buttons are still lit as the cabinet goes off:** Shut Down Cabinet and
Restart Cabinet don't wait for the lights. HyperSpin tells LEDBlinky to quit
only on its own exit, so the helper sends `LEDBlinky.exe 2` itself, then shuts
Windows down or restarts it at once, and Windows ends LEDBlinky part-way through
its quit animation (which can take half a minute). Windows takes over a few
seconds after the countdown.

### Exit To Windows leaves the desktop without a taskbar

After **Exit To Windows** HyperSpin is gone, but the desktop has no taskbar or
Start button.

**Cause:** HyperSpin hides the taskbar while it runs and shows it again only on
its own exit, so `spindoctor toolkit exit-to-windows` restarts Explorer to bring
it back. If Explorer couldn't be started, the taskbar stays hidden.

**Find it:** `%USERPROFILE%\.spindoctor\toolkit.log` ends with
`could not start …explorer.exe`, or has no `on the desktop` line.

**Fix:** press Ctrl+Shift+Esc for Task Manager, then **File → Run new task**,
`explorer.exe`. On a cabinet whose Windows shell was replaced with HyperSpin,
starting `explorer.exe` is what gives you a desktop at all.

**If the buttons stay lit on the desktop for a while:** that's LEDBlinky's quit
animation finishing (up to 30 s); Exit To Windows doesn't make you wait for it.

### HyperSpin starts stretched or in a corner after a game

HyperSpin comes back from a game (or starts after a crash) filling only part of
the screen, stretched, or with black bars, and the Windows desktop is at a
different resolution than before.

**Cause:** the game or emulator changed the display mode and didn't put it
back, usually because it crashed. HyperSpin draws at the size in its
`Settings\Settings.ini` `[Resolution]` section, whatever Windows is set to.

**Fix:** run `spindoctor toolkit set-resolution`, or put it on the wheel with
`spindoctor install-tools --tool set-windows-resolution --add-to-system Toolkit --apply`
and pick **Set Windows Resolution**. It sets Windows back to HyperSpin's
`[Resolution] Width` × `Height` and saves it. If the note says "Couldn't set",
`%USERPROFILE%\.spindoctor\toolkit.log` has the reason, for example a size the
display doesn't support.

### A Toolkit helper shows as plain text on the wheel, or with the wrong logo

The entries `install-tools --add-to-system` added show their name in
HyperSpin's default font, or an old logo, instead of SpinDoctor's pink-on-blue
wheel art.

**Cause:** the art is copied to `<HyperSpin>\Media\<System>\Images\Wheel\<entry>.png`
only when `--apply` writes the entries, and only when no file of that name is
there: a logo already in place is kept, so your own art is never replaced. An
install from before SpinDoctor shipped the art wrote none.

**Fix:** re-run the same `install-tools … --add-to-system <System> --apply`
for a missing logo. To swap an old logo for SpinDoctor's, delete
`<entry>.png` first, then re-run it. HyperSpin reads wheel art at start, so
restart HyperSpin to see it.

### The idle tour never changes wheels

HyperSpin's idle mode spins and plays videos, but always on the same wheel,
although the [idle tour](idle-tour.md) is installed.

**Check first:** `spindoctor doctor` (the **Idle tour** check), and
`spindoctor toolkit idle-tour --self-test`, whose last line says what would
stop a key press now. `%USERPROFILE%\.spindoctor\toolkit.log` has an
`idle-tour:` line for each start, wheel change and pause.

**Causes, most common first:**

- **It never started.** `install-tools --tool idle-tour` without `--apply`
  writes the `.bat` but doesn't add it to HyperSpin's Startup Script; re-run it
  with `--apply`. An entry numbered after a gap in the Startup Script's
  `[Startup]` list never starts, because the script stops at the first missing
  number: number the entries 1, 2, 3 … without gaps. After moving or upgrading
  SpinDoctor, the `.bat` runs an EXE that's gone (the **SpinDoctor helpers**
  check): re-run `install-tools --tool idle-tour`. No `idle-tour: started` line
  in `toolkit.log` means one of these.
- **HyperSpin's idle mode or LEDBlinky calls are off.** The tour needs
  `Settings\Settings.ini` `[AttractMode] Active=true` and `[LEDBlinky]
  Active=true` (it reads every selection and idle spin from HyperSpin's
  LEDBlinky calls in `log.txt`). Edit them with HyperSpin closed. Its `started`
  line is followed by a warning when either is off. In single mode
  (`[Main] Menu_Mode=single`) there is no main menu, and the tour presses
  nothing.
- **It's waiting on purpose.** Nothing happens before HyperSpin's idle mode
  has started (`[AttractMode] Time`, 300 s by default) and shown the set
  number of games or consoles; then it changes wheels as the last one's video
  ends, so a long video means a long wait. On the main menu it opens only a
  console that isn't in `Skip=` and has a database; a skipped one counts, and
  it waits for the next. After `TourMaxMinutes` (60) it stops until someone
  uses a control. `Enabled=0` in `Idle Tour settings.ini` switches it off.
  `spindoctor toolkit idle-tour-settings` (or the GUI's **Idle Tour
  settings** box) shows the values it uses.
- **Something else is in front, or "uses a control".** It presses nothing
  while HyperSpin isn't the front window (a tool that steals the focus at
  start), or while a `PauseWhile` program runs. Any keyboard or mouse input,
  including a program sending keys or a mouse that drifts, counts as someone
  using a control: the tour then waits for HyperSpin's idle mode to start
  again.

### The idle tour changes wheels right after a spin, not as a video ends

The idle tour opens a console (or goes back to the main menu) just after
HyperSpin's idle spin lands, so the video of the console it opens isn't seen.

**Cause:** that's its fallback when it can't time the video's end. Its
`toolkit.log` line for the item says which:

- **`(video length unknown)`:** a `.mp4` or `.flv` whose length can't be read
  in the wheel's video folder (`Settings\<wheel>.ini` `[video defaults]
  path=`, else `Media\<wheel>\Video`), or no video at all with
  `NoVideoSeconds=0` (otherwise an item with no video gets a Down, below).
  `spindoctor toolkit idle-tour --self-test` shows the selection's video
  length and the folder.
- **`the video ended early`:** HyperSpin spun before the end the file states,
  for example a video cut short without its header updated.
- **`(joystick)`:** HyperSpin reads a joystick itself (`[P1 Joystick]` or
  `[P2 Joystick]` `Enabled=true`). Windows doesn't see those presses, so the
  tour can't tell someone is playing, and pressing Start at a video's end
  could answer Yes to an exit menu a joystick opened. It keeps to the spin
  landings, which show HyperSpin's idle mode is still running, and presses
  no Down past items with no video (`(no video, joystick)`). Mapping the pad
  to keys (JoyToKey and the like) instead lets Windows see it.

### The idle tour moves on from a game after a few seconds

During HyperSpin's idle mode the wheel steps to the next game (or console) a
few seconds after landing on one, instead of waiting for a spin.

**Cause:** that item has no video (no `.mp4` or `.flv`, or only a still), and
HyperSpin's idle mode would sit on it for its whole idle `Time` (5 minutes by
default) before spinning again. After `NoVideoSeconds` (8) the idle tour
presses Down once; its `toolkit.log` line says `(no video: stepping on in
8 s)`. Adding the missing videos fixes it at the source. `NoVideoSeconds=0` in
`Idle Tour settings.ini` (or `spindoctor toolkit idle-tour-settings
--no-video-seconds 0`, or the GUI's **Idle Tour settings** box) switches the
step off, and HyperSpin then waits as before.

### The cabinet's screen no longer turns off when nobody plays

Since the idle tour was installed, the display stays on all night.

**Cause:** Windows counts the tour's key presses as input, so its screen
timeout starts over at each wheel change (HyperSpin's own idle timer ignores
them).

**Fix:** the tour stops changing wheels after `TourMaxMinutes` (60 by default)
and leaves HyperSpin's idle mode on the main menu, so the screen turns off
after Windows' own timeout from then. Lower `TourMaxMinutes` in
`Idle Tour settings.ini` (beside `Idle Tour.bat`) for a shorter tour; `0`
means it never stops.

### A script's key presses to HyperSpin go missing, or open the wrong thing

A script or helper that drives HyperSpin with key presses works only some of
the time: presses are lost, the wheel keeps moving after the script stops, or
an Esc-then-Enter meant to close HyperSpin opens a console or a game instead.

**Cause:** HyperSpin drops a key that goes down and up at once, queues presses
it gets faster than it moves (about 2 entries a second), and swallows keys
during its idle spins. Its exit menu writes nothing to `log.txt` and defaults
to Yes, so a lost Esc turns the following Enter into "open the selected
entry". Its idle timer also ignores keys sent by a program, so a script can't
hold HyperSpin's idle mode off.

**Fix:** hold each key about 80 ms, send one key at a time and wait for
`log.txt` to show its effect, and never send Exit unless the log shows
HyperSpin is inside a console. See [Idle tour → Scripting
HyperSpin](idle-tour.md#scripting-hyperspin-what-to-know).

## Intro Video Randomizer

### `introvideo` commands fail with "intro_randomizer_dir is not set" / "intro_video_target is not set"

Configure both on the Setup tab (**Intro video pool directory** and **Intro video target file**), or `spindoctor config set intro_randomizer_dir <path>` / `spindoctor config set intro_video_target <path>`. `intro_randomizer_dir` is the folder videos live directly in; `intro_video_target` is the full path to the file HyperSpin plays on boot (e.g. `Intro.mp4`) — they're independent fields, neither is derived from the other. See [Command reference → Intro Video Randomizer](commands.md#intro-video-randomizer).

### `introvideo swap` says "No videos in the pool — nothing to swap"

`intro_randomizer_dir` exists but has no video files directly inside it (extensions checked: `.mp4`, `.avi`, `.wmv`, `.mkv`, `.mov`, `.m4v`, `.flv`) — either it's genuinely empty (run `introvideo add` to add some) or every video in it has been moved into `Disabled\` by `introvideo remove` (run `introvideo restore` to bring one back). This is a clean no-op, not an error, on purpose — it's also what the unattended Windows logon task runs, and it must never crash the login sequence.

### A video I dropped straight into the pool folder isn't showing up as enabled

Double check it landed directly in `intro_randomizer_dir`, not in its `Disabled\` subfolder — that subfolder is never scanned as a candidate. There's no separate registration step in the new model: any video file with a recognized extension sitting directly in the pool folder is enabled the moment `introvideo list`/`swap` next scans it.

### `install-autorun` / `uninstall-autorun` / the Intro Video tab's auto-run status say "not available (Windows only)"

Expected on macOS/Linux — the Windows Task Scheduler integration (`spindoctor/autostart.py`, a thin `schtasks.exe` wrapper) only exists on Windows. On the actual cabinet (Windows), this should not appear; if it does, confirm you're running the Windows build, not a dev checkout on a different OS.

### The logon task is registered but the intro video never seems to change

**First, make sure you're on a version that includes the fixes for this.** Four real bugs were found and fixed after an extensive real-cabinet investigation:

1. The generated `.vbs` shim never actually ran the `.bat` when triggered by Task Scheduler, at any delay — the **actual root cause**, see step 4 below.
2. The `.bat`/`.vbs` always reported Task Scheduler's "Last Result" as `0` (success) even when the swap failed, so that field couldn't be trusted for diagnosis.
3. `swap_video` didn't retry when `intro_video_target` was locked.
4. Its retry window (originally 10 seconds) was too short for anything but the shortest intro clips.

**If you enabled auto-run before upgrading, re-run `introvideo install-autorun --apply`** to regenerate the launcher files with all four fixes — the old ones don't self-update.

Diagnostic steps, in the order that actually resolves this fastest:

1. Confirm it's registered: **Auto-run on Windows login** status label on the Intro Video tab, or `spindoctor introvideo uninstall-autorun` (dry-run — no `--apply` — just reports current status without removing anything).
2. Run `spindoctor introvideo swap --apply` by hand (CLI, or the **Swap now** button) and confirm it prints `✓ Copied <file>`. This isolates whether your `intro_randomizer_dir`/`intro_video_target` config is right — if this works, the problem is specific to the scheduled path, not your setup. **Don't judge success from `Intro.mp4`'s file date** — `shutil.copy2` deliberately preserves the *source* video's own modified date, not the time of the copy, so the date never reflects when a swap last ran. Compare file **size** instead (or just watch which video plays).
3. **Confirm the scheduled task actually executes at all** — this is the step that finds the real root cause fastest, and doesn't require waiting for a reboot. In Task Scheduler (`taskschd.msc`), right-click **SpinDoctor Intro Swap** → **Run**. If nothing changes and you're on an older build, temporarily replace the generated `.bat` (next to the frozen exe, or in `~/.spindoctor/` for a source install) with a version that logs its own output:
   ```bat
   @echo off
   "<path to spindoctor.exe>" introvideo swap --apply > "<same folder>\swap-debug.log" 2>&1
   echo Exit code: %errorlevel% >> "<same folder>\swap-debug.log"
   ```
   Click **Run** again, then check whether `swap-debug.log` was created at all. **No log file at all** (not even an empty one) means the `.bat` never started — that's the `.vbs` path-derivation bug (fixed on current versions; re-run `install-autorun --apply` to regenerate the launcher files). A log file **with** a `PermissionError` inside points at the lock scenario in step 4 instead.
4. If the `.bat` does run (confirmed via step 3) but still doesn't change the video, it's the lock: HyperSpin holds `intro_video_target` open for the **entire duration** it's playing the *previous* intro video — not just an instant. Reproduce it directly: run `introvideo swap --apply` while an intro clip is actively playing and it fails immediately with `PermissionError: [WinError 32] The process cannot access the file because it is being used by another process`; run it again once the clip finishes and it succeeds instantly. `swap_video` retries every 2 seconds to ride this out, for the playing clip's length plus a minute (at least 3 minutes, at most 30). It reads the length from the MP4 / M4V / MOV header; when it can't, it uses the longest clip in the pool, or 3 minutes. Older versions retried for a fixed 3 minutes, so a longer clip that was playing made the swap fail, and the same clip then played again at the next boot. `spindoctor doctor`'s **Intro video** check shows the longest clip and how long the swap waits for it, and warns about clips too long to wait out. For a clip in another format, or one over 29 minutes, convert or remove it, or increase `--delay-minutes` on `install-autorun` (or the GUI's **Delay after login** field) for a bigger head start.

## Light guns

### Model 3: player 2's gun does nothing, or both guns move one crosshair

Supermodel sees two guns as one mouse unless it runs with raw input and every gun line names its own mouse. Start and Coin can also stop working once raw input is on, because raw input ignores keys sent by a keymapper remap. See [Two guns: Model 3 and the Sinden software](lightgun.md#two-guns-model-3-and-the-sinden-software) for the settings, how Supermodel numbers mice, and the `Crosshairs` values. If player 2's gun aims but doesn't recoil like player 1's, check that the Sinden software runs both guns for that game (same section).

### Start or Coin does nothing in one game, though the same button works in others

The game's emulator is probably bound to the key the button sends, while a RocketLauncher keymapper remap turns that key into another one. With `r::1`, a Start bound to R never fires; bind it to 1. A game can also load a different profile from the rest of its system (a game- or emulator-named one), so its emulator may need other keys. See [RocketLauncher's keymapper profile order](lightgun.md#rocketlaunchers-keymapper-profile-order) for which profile a game loads.

### A Super Scope game starts firing single shots, though turbo works

Snes9x starts every game with the Super Scope's turbo off, and its turbo key toggles it. To start a game in turbo, press the key from the game's User Functions `PostLoad()`, and give the game automatic recoil. See [SNES Super Scope games](lightgun.md#snes-super-scope-games-snes9x).

### `spindoctor lightgun detect` reports "DemulShooter not found"

DemulShooter must be on disk somewhere spindoctor scans, at most four folders deep. The auto-detected roots are `<HyperSpin>/Tools`, `<RocketLauncher>/Modules`, `<RocketLauncher>/Plugins`, `<emulators_dir>`, plus `Program Files` and the Start Menu. If yours lives elsewhere, or `detect` lists several DemulShooter executables and picked the wrong one:

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

Open `RocketLauncher\Settings\<System>\Emulators.ini` (folder layout) or `RocketLauncher\Settings\<System>.ini` in any editor and delete the `Pre_Launch_App` and `Post_Launch_App` lines, then set `"lightgun": false` under the system in `~/.spindoctor/config.json` (or run `spindoctor lightgun audit` to confirm the change took).

### `doctor` says a light-gun system "runs with no gun", but the guns work

The guns are probably started from RocketLauncher User Functions, not from a `Pre_Launch_App` hook; SpinDoctor 2.15.0 and earlier only looked for the hook. Now a `Run` or `RunWait` line that starts `Lightgun.exe` or DemulShooter in `RocketLauncher\Lib\User Functions\<System>.ahk`, `<System>\<Game>.ahk`, `Emulators\<Emulator>.ahk` or `<System>\Emulators\<Emulator>.ahk` counts, and `lightgun audit` names the file. If `doctor` still fails the system:

1. **The `Run` line is commented out** (`;` in front, or inside `/* … */`).
2. **The file runs a helper** (a `.ps1`, `.bat` or another script) that starts the gun software. SpinDoctor doesn't follow helpers, so the system shows as unwired although it works. To make `doctor` see it, start `Lightgun.exe` or DemulShooter from the User Functions file itself.
3. **The emulator file doesn't match.** `Emulators\<Emulator>.ahk` counts only when `<Emulator>` is the system's `Default_Emulator` or a `Games.ini` `Emulator=` value. `Global.ahk` isn't read: it runs for every system.

Don't add a `Pre_Launch_App` hook to a system whose User Functions already start DemulShooter, or it starts twice; `lightgun configure` warns about this.

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

### A custom `.lwax` animation won't load: "Animation File has a missing or invalid signature"

Expected for any file made by `spindoctor ledblinky lwax fade` or `scripts/generate_lwax_patterns.py` — they emit *unsigned* files. LedBlinky Config validates a per-file signature it only writes itself. Open the file once in `LEDBlinkyAnimationEditor.exe` (in `<ledblinky_dir>\Plugins\LEDBlinky\`), do **Animation → Save As** with the same name and no edits, then copy the result into `<ledblinky_dir>\lwa\`. (Runtime playback via `Settings.ini` does not check the signature — the error only appears inside LedBlinky Config's own animation UI.) Full detail: "LEDBlinky Animation Files (.lwax)" in [`cabinet-architecture-reference.md`](cabinet-architecture-reference.md#ledblinky-animation-files-lwax).

### A custom animation plays, but some buttons stay a fixed colour (often white)

`Settings.ini` `[FEOptions] LightFEControls=1` overrides the front-end's currently-active navigation buttons with a fixed colour, so they never join the animation. Set `LightFEControls=0` for a fully synced panel (or leave it `=1` if you *want* those buttons to show a fixed "usable" colour — it's one or the other, not both). This is a LedBlinky setting, not a flaw in the generated file.

### Buttons on one LED board flash constantly, even during calm animations

A fixed group of buttons blinks whatever LedBlinky plays, even a slow `breathe_*` fade, while the rest of the panel animates normally. Restarting HyperSpin and LedBlinky doesn't help, and the buttons go dark once LedBlinky closes. On the cabinet it was Search, Pause and every Player 2 button: all on the second PAC-LED64, while Exit on the same board stayed steady.

The board itself is doing it. The PAC-LED64 has its own per-port flash mode, which stays on until it's cleared or the board loses power, and a flashing port blinks whatever brightness it's given. That is why they go dark like the rest once LedBlinky turns them off. Nothing SpinDoctor writes, and no `.lwax` file, can switch flash mode on, and LedBlinky never resets it.

1. Close HyperSpin, then light every LED solid straight through Ultimarc's `PacDrive32.dll`. If the same buttons still blink, the board is in flash mode.
2. Set every port's flash speed to 0 with `Pac64SetLEDFlashSpeeds` and `Pac64SetLEDFlashSpeed`. `Pac64ClearFlash` alone did not stop it. A full power-off also clears it.

**Fix:** run `spindoctor toolkit reset-button-lights`. It does step 2 on every PAC-LED64 through the `PacDrive32.dll` in `ledblinky_dir`, with HyperSpin and LEDBlinky still running. To fix it from the cabinet, put it on a Toolkit wheel with `spindoctor install-tools --tool reset-button-lights --add-to-system Toolkit --apply`. "No button light boards found" means PacDrive saw no PAC-LED64 (check USB); "Button light reset failed" has its reason in `%USERPROFILE%\.spindoctor\toolkit.log`. See [`toolkit`](commands.md#toolkit).

**One board still lit after LEDBlinky quits** (seen on the same cabinet: the second board stayed purple) is a different thing. Exit To Windows turns every PAC-LED64 light off once LEDBlinky has quit, through the same DLL, and logs it to `toolkit.log` (`lights off: board 1 off: True, …`). Shut Down Cabinet and Restart Cabinet don't wait for LEDBlinky, so they leave the lights to Windows.

The script, the diagnosis and a HyperSpin startup step that repeats the reset at every start are in [Diagnosing buttons that flash on one board](cabinet-architecture-reference.md#diagnosing-buttons-that-flash-on-one-board-pac-led64-on-board-flash-mode) in `cabinet-architecture-reference.md`.

### Where does `ledblinky generate` pull its data from?

Locally. A missing entry is copied from SpinDoctor's LEDBlinky library (`~/.spindoctor/ledblinky_library/`, the entries `ledblinky prune` removed) when it's there; otherwise it's built from `mame -listxml`, which is run as a subprocess and cached in `~/.spindoctor/mame_listxml_cache/`. No scraper API, no quota. The cache is invalidated automatically when the MAME binary is newer than the cached file.

### LEDs and the ServoStik come alive a minute after HyperSpin starts

HyperSpin is up, but the panel stays dark (or shows its last colours) and the ServoStik stays in the wrong mode for a minute or more after every start. Wheel changes made in that time don't light anything. `LEDBlinky.log` shows "Timeout waiting for Primary Instance Handle" for those events.

LEDBlinky reads all of `controls.ini` and `Colors.ini` when it starts (`LoadMameFilesAtStartup=1` in its `Settings.ini`), and only then sets the ServoStik, plays its start animation and answers the front end. Every LED event HyperSpin sends before that times out after 5 seconds and is dropped. Older versions of `ledblinky generate` / `setup` wrote an entry for every ROM file in the MAME folder. With a full ROM set that's tens of thousands of entries and over 10 MB. On one cabinet, LEDBlinky started on its own with 33,700 entries per file (15 MB) used 28–30 seconds of CPU and was busy for 36–40 seconds, dropping events for the first 20. With the 6,100 entries its wheels need (2.8 MB), it used 14 seconds and was ready after 22–24 seconds, start animation included, with nothing dropped. Started alongside HyperSpin, the full files kept the lights and the ServoStik waiting about a minute. `spindoctor doctor` warns about it under **LED coverage**, and `spindoctor ledblinky audit` shows how many entries are for games in no wheel.

1. Preview, then remove the entries for games in no wheel. Games in any wheel, hidden ones included, and their parent ROMs keep their entries unchanged:

   ```bat
   spindoctor ledblinky prune
   spindoctor ledblinky prune --apply
   ```

   Each removed entry is saved to SpinDoctor's LEDBlinky library first, and both files are backed up.
2. Restart HyperSpin and time it: the gap between HyperSpin starting and the last "Timeout waiting for Primary Instance Handle" line in `LEDBlinky.log` should shrink sharply, or the line disappear. LEDBlinky still plays its start animation before it's ready; shorten that animation if the rest of the wait bothers you.
3. After adding MAME games to a wheel, run `spindoctor ledblinky generate --apply`: it adds only the missing entries, from the library exactly as they were when it has them. `spindoctor ledblinky generate --all-roms --apply` puts every pruned entry back.

`LoadMameFilesAtStartup=0` doesn't help: LEDBlinky then reads the same files the first time a MAME wheel opens.

### Start and Coin stay dark in a game, though they work when pressed

The wheel probably uses RocketLauncher's AHK keymapper to turn panel keys into the keys the emulator listens for, for example `r::1 s::5 t::2 u::6` in `RocketLauncher\Profiles\AHK\<wheel>.ahk`. Older versions of `ledblinky profiles` didn't read those remaps: they looked for a panel button that sends 1, found none, and lit only Exit and Pause. Re-run it:

```bat
spindoctor ledblinky profiles              :: dry-run: the table notes the AHK profiles used
spindoctor ledblinky profiles --apply
```

If they are still dark:

- `Keymapper_AHK_Method` must be `Internal` or `External` in `Settings\<wheel>\RocketLauncher.ini`, or in `Global RocketLauncher.ini` when the wheel says `use_global`. With it off, RocketLauncher doesn't load the profile either.
- The profile's name must match the game, emulator or wheel name exactly. A game's own profile replaces the wheel's, even one that remaps nothing.
- Only plain `key::key` lines count. A key sent by a `Send` line or a hotkey with a body isn't followed. Conditional `#If` / `#IfWin...` regions are ignored because their runtime window or expression isn't known.
- On wheels with "MAME" in the name, LEDBlinky reads the keys from MAME's cfg itself, so an AHK profile there can't change what lights.

## Migration / drives

### Disc-based games stop launching after reinstalling DAEMON Tools (or moving to a new PC)

**Symptom:** Every system that mounts disc images through RocketLauncher's virtual drive (for example Sega Saturn, Neo Geo CD, PC-FX, Amiga CD32, CD-i) stops launching, while cartridge and arcade systems still work. RocketLauncher reports that it could not find the virtual-drive program (`DTLite.exe`) and asks you to fix the Virtual Drive Path.

**Cause:** RocketLauncher stores the full path to the virtual-drive program in `Virtual_Drive_Path` under `[Virtual Drive]` in `RocketLauncher\Settings\RocketLauncher.ini`. The 64-bit DAEMON Tools Lite installer uses `C:\Program Files\DAEMON Tools Lite\`, but a cabinet set up with the 32-bit version still points at `C:\Program Files (x86)\DAEMON Tools Lite\DTLite.exe`. After a Windows reinstall or a move to a new PC, that file is gone. Which systems use the virtual drive is set by `Virtual_Drive_Enabled`: globally in `Settings\Global RocketLauncher.ini`, overridden per system in `Settings\<System>\RocketLauncher.ini`, where `use_global` follows the global value.

**Find it:** `spindoctor doctor` → **RocketLauncher settings** → **Virtual drive** shows a WARN listing the systems affected. If `DTLite.exe` exists in the other Program Files folder, the fix line gives that exact path.

**Fix:** Set the Virtual Drive Path in RocketLauncherUI, or edit the file directly:

```ini
; D:\Arcade\RocketLauncher\Settings\RocketLauncher.ini
[Virtual Drive]
Virtual_Drive_Path=C:\Program Files\DAEMON Tools Lite\DTLite.exe
```

Then re-run `spindoctor doctor`, and launch one disc-based game to confirm.

### Every launch takes longer than it should

**Symptom:** Games launch, but RocketLauncher takes noticeably longer on every launch than it used to.

**Cause:** `Logging_Level` under `[Logging]` in `RocketLauncher\Settings\RocketLauncher.ini` is 4 (debug) or higher, often left over from troubleshooting. RocketLauncher logs its own warning at those levels that debug logging slows it down. Levels 2 and 3 still log warnings and errors; 3 is RocketLauncher's default.

**Fix:** Set `Logging_Level=3` (in RocketLauncherUI or in the file). `spindoctor doctor` reports a level of 4 or higher as INFO under **RocketLauncher settings** → **Logging**.

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

### Naomi/Atomiswave, AAE, Daphne or Pokémon Mini games can't find their ROMs or saves after moving the ROM drive

**Symptom:** You moved your ROMs (for example from `J:\Games` to `E:\Games`) and ran `generate-config --apply`. Most wheels launch again, but Sega Naomi / Sammy Atomiswave games in Demul, AAE vector games or Daphne laserdisc games still report missing ROMs, or Pokémon Mini saves stop working.

**Cause:** These emulators keep a ROM or save folder in their *own* config file, separate from RocketLauncher's `Rom_Path`. Neither `generate-config` nor `migrate` rewrites it:

| Emulator | File | Key |
|---|---|---|
| Demul with the v0.5.6 / v0.5.7 module (it only passes `-rom=`, so Demul searches its own list) | `Demul.ini` in the emulator folder | `roms0` … `romsN` under `[files]`, up to `romsPathsCount` |
| AAE | `aae.ini` in the emulator folder | `mame_rom_path` |
| PokeMini | `pokemini.cfg` in the emulator folder | `eepromfile` (the one shared save file, used while `eepromshare=yes`, the default; with `eepromshare=no` saves sit next to each ROM and this is not checked) |
| Daphne | `RocketLauncher\Modules\Daphne\Daphne.ini` | `homedir` in each game's section |

**Fix:** Run `spindoctor doctor`. The **Emulator ROM folders** check lists every value whose folder no longer exists, with the file and key, and gives the replacement value when the same folder exists under your `roms_dir`. Close the emulator, open the file in Notepad and set each listed key to the new folder. Keep Demul's trailing backslash (`roms1 = E:\Games\Sega Naomi\`). A Daphne `homedir` of `.` (Daphne's own folder) is fine.

If `doctor` shows a value as INFO ("harmless"), the emulator's RocketLauncher module sets that folder itself before every launch (the stock AAE module, and the Demul v0.5.8 / v0.7 modules), so there's nothing to fix.

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
across at least three Dolphin generations on the example cabinet:

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

### Xpadder still launches and throws errors after I disabled it in Windows and HyperSpin

**Symptom:** You removed Xpadder from Windows startup and from the HyperSpin Startup
Script, but it still opens **as a game launches or exits**, with the dialog:

> *An error has occurred in this program — AutoProfileScan thread failed to stop.
> This error should never happen! For assistance, please visit the website xpadder.com*

A related symptom is **controls "randomly" switching** between the PS4 pad, the arcade
stick, and a third mapping mid-session — two auto-profile mappers (Xpadder's
AutoProfileScan and DS4Windows Auto Profiles) fighting over the same pad.

`AutoProfileScan` is Xpadder's **own Auto-Profiles** thread (it watches the foreground
window and swaps profiles — the same job DS4Windows Auto Profiles now does). "Failed
to stop" is a shutdown race: Xpadder is launched with auto-profiles running and then
killed as the game exits.

**Cause:** Once the Windows autostart surfaces (Startup folder, registry Run keys,
Task Scheduler) and the HyperSpin Startup Script are all confirmed clean, the
remaining culprit is **RocketLauncher's own Keymapper**. RocketLauncherUI → Global →
Keymapper can be set to Xpadder — the RL log records it as:

```
keymapperEnabled := "true"
keymapper        := "xpadder"
xpadderFullPath  := "D:\Arcade\Utilities\Xpadder\Xpadder.exe"
```

Because the keymapper runs per game launch/exit, the tell-tale is that the error fires
**when you launch or quit a game** (a PCLauncher/PC-game exit on the example cabinet), *not* at
Windows boot. DS4Windows Auto Profiles already maps the pad, so RL keymapping is
redundant and only creates the second-mapper fight.

> A clean Windows Startup list does not rule this out. A renamed or retired
> Xpadder folder can still contain a runnable executable referenced by
> RocketLauncher. Identify the parent process before changing unrelated settings.

**Fix:**

1. **Disable the keymapper.** RocketLauncherUI → Global → Keymapper → **Keymapper
   Enabled = false**. If RLUI doesn't expose it, hand-edit `RocketLauncher\Settings\
   Global RocketLauncher.ini` → `[Keymapper]` → `Keymapper_Enabled=false` (close RLUI
   first, or it rewrites the file on exit). This is the high-value step — it stops the
   game-launch/exit invocation and the control-switching fight in one move. Note that
   JoyIDs controller-ordering (`JoyIDs_Enabled`) lives in the same `[Keymapper]` block;
   if a game's player/controller assignment looks swapped afterward, that's the setting
   to revisit (DS4Windows can handle ordering instead).
2. **Delete the Xpadder install folder(s)** (`spindoctor tools-audit` / `where /r D:\
   Xpadder.exe` reports where they are — note a renamed folder still contains a runnable
   `Xpadder.exe`) so nothing can launch it even if a stray reference survives.
3. Full runbook: [Controller input → Removing Xpadder completely](controller-input.md#6-removing-xpadder-completely).

**Diagnosis:** confirm *when* the dialog fires. If it's on a **game launch/exit**, it's
the RL Keymapper (above). If it's at **Windows boot/logon**, check the autostart
surfaces instead — Task Manager → Startup, `shell:startup`, `taskschd.msc`, and the
`…\CurrentVersion\Run` registry keys. To catch the launcher live, leave the error
dialog open and run
`powershell "Get-CimInstance Win32_Process -Filter \"name='Xpadder.exe'\" | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.ParentProcessId); [pscustomobject]@{Xpadder=$_.ExecutablePath;Parent=$p.Name;ParentPath=$p.ExecutablePath} } | Format-List"`
— `Parent`/`ParentPath` name whatever started it. Related: the *"After the game loads,
HyperSpin stays in front…"* entry below, where an Xpadder profile mapped the back
button to `Escape`.

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

Almost every destructive command writes a manifest under `~/.spindoctor/<category>/` and supports `--undo`. Full recovery flows and the manifest map live at [Workflows → Recovery](workflows.md#recovery-from-mistakes). The GUI's `File → View logs & manifests` window lists every per-run manifest with a tree on the left and a JSON viewer on the right; the **Undo this run** button at the bottom runs the matching `--undo` command for the selected row in one click. For categories whose CLI always reverses the most recent run (`curate`, `media-scan`), the button warns you if you pick an older row so you don't accidentally reverse the wrong one.

## GUI launcher

### Status bar says "Update available: vX.Y.Z" — what does it mean?

The GUI checks GitHub Releases on launch and surfaces newer-version hints in the status bar (with the URL in the Output panel). `Help → Check for updates` re-runs the same check on demand. To download, open the [latest release](https://github.com/phillram/spindoctor/releases/latest) and replace your `.exe` files (config and caches under `~/.spindoctor/` survive the upgrade — see [Updating](windows-binaries.md#updating)).

### How do I disable the update check?

Set the `SPINDOCTOR_NO_UPDATE_CHECK=1` environment variable before launching the GUI. The check is also a no-op when GitHub is unreachable, so you don't need to disable it explicitly for offline cabinets — it just silently degrades. See [Configuration → Environment variables](configuration.md#environment-variables).

### Where do my manifests live? How do I read one?

Open the GUI and use **`File → View logs & manifests`**. The window groups manifests by category (Migrations, Curation, Edits, Renames, Media imports, Theme swaps, Misplaced ROMs) and shows the JSON content read-only. The folder behind it is `~/.spindoctor/<category>/`; **`File → Open SpinDoctor folder`** jumps straight there if you'd rather edit by hand. Don't edit a manifest if you might want to `--undo` later — the undo path reads the manifest verbatim. The same window has an **Undo this run** button that runs the matching `--undo` command for the selected row, so you don't have to remember which CLI invocation owns each category.

### My controller-glyph swap looks wrong / I want to revert it

`spindoctor theme-apply --apply` writes a manifest under `~/.spindoctor/themes/theme-apply-<timestamp>/manifest.json` with a backup of every overwritten file alongside. To revert: `spindoctor theme-apply --undo latest` from the CLI, or open the GUI's **`File → View logs & manifests`** window, expand **Theme swaps**, click the row, and press **Undo this run**. If the GUI's `File → Browse HyperSpin themes` returns nothing for your cabinet but you can clearly see glyphs at the bottom of the screen, those glyphs likely live inside a Flash `.swf` in `Media/Main Menu/Themes/default.zip` — SpinDoctor can't edit SWFs (they need a Flash authoring tool).

### Custom Wheels tab → Enable auto-run fails with "access denied"

`schtasks.exe` writes to a system-wide Task Scheduler store that requires admin rights. Run SpinDoctor as Administrator (right-click `spindoctor-gui.exe` → **Run as administrator**) and click Enable auto-run again. The GUI now translates `schtasks` failures into one-line actionable messages: "access is denied" → run as Administrator; "already exists" → use the Disable auto-run button first; "specified task does not exist" → there's no task to remove yet; anything else falls back to the raw `schtasks` output so power users can diagnose obscure error codes.

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
- **`Hide`** (in the Output panel's header, or `View → Show output pane`, or `Ctrl+`` `) collapses the bottom panel and gives the active tab the full window height. Re-show it with the status bar's **Show output** button or the same menu item or shortcut. Persisted across restarts via the `output_visible` config key.

The two together typically clear another 200–300 vertical pixels on a 720p cabinet display.
