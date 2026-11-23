# Troubleshooting

Start with `spindoctor --version`, `doctor` and the failing command's `--help`.
Binary users substitute `spindoctor-cli`. Review Output and the relevant log
before retrying an Apply. [Recovery](workflows.md#recovery-from-mistakes) is
command-specific; do not delete manifests to silence errors.

## Install and GUI

| Symptom | Check / action |
|---|---|
| EXE flashes and closes | v3 `spindoctor.exe` is GUI; run `spindoctor-cli.exe` in a terminal. Old releases used different names. |
| Command not found | Activate your Python environment, check Scripts/PATH, or use `python -m spindoctor.cli`. |
| GUI says worker/binary missing | Replace an old/mixed install with the current self-contained EXE. No helper EXEs are required in v3. |
| Win7 API/entry-point error | Use Win7 download and SP1, not the modern bootloader. |
| SmartScreen/quarantine | Verify release origin and checksum. Do not disable protection globally. |
| TLS/SSL failure | Check clock, trusted certificates, proxy and current compatible release. Do not bypass certificate verification. |
| Second GUI refuses to open | Bring the first instance forward. `gui.lock` remaining after a crash is harmless; the OS lock is released. |
| Rejected config path | Create/select the actual existing folder, then save again. |
| Cramped screen | Hide Output/help text or reduce View UI scale; pages scroll. |
| Unwanted GitHub update checks | Set `SPINDOCTOR_NO_UPDATE_CHECK=1` before launch. |
| Startup task access denied | Inspect Task Scheduler permissions/policy and the exact error; elevate only if your policy requires it. |

## Library and launch routing

| Symptom | Check / action |
|---|---|
| ROM folder has no database | Preview `add-system` with the exact folder/system name. |
| Main Menu XML parse error | Back up the file, fix malformed XML or restore a known-good version. Do not save an empty replacement over it. |
| No ROMs found | Check extensions, system overrides and effective RocketLauncher `Rom_Path`, including shared/relative/multiple folders. |
| ROMs launch but audit misses them | Use a current release; audit now honors configured RL ROM paths and game overrides. Confirm configuration points at that RL install. |
| Content dupes have different sizes/SHA1s | Recognized NES/FDS/SNES ROM headers are ignored for content pairing. Wrapper equality is not required. |
| “Cannot find Rom” | Check actual stem, allowed extensions, per-game emulator and every effective ROM path. |
| Casual Games cannot locate program | Check `gamePath`, executable naming/fallback folder and matching placeholder; unrelated `.txt` files can match accidentally. |
| AHK cannot launch a program | Inspect effective User Functions for stale helper paths and working directories. |
| Double menu movement after certain games | A second mapper probably survived launch. Inspect User Functions and RL keymapper settings, not just Windows startup. |
| Refresh stopped after upgrade | Regenerate helpers/tasks with the current EXE path and same tool selections; run `doctor`. |
| Toolkit “exe/FadeTitle/SteamID” error | Reinstall the helper using `install-tools`; module routing and placeholders must agree. |
| Synthetic wheel missing INI/stuck fade | Rebuild with the current version; do not substitute ordinary PC-game INIs for recursive launch routing. |
| Newly added wheel won't open | Check HyperSpin `Settings/<System>.ini` as well as database/media and RL settings. |

## Metadata and scraping

Provider requests/errors are in `.spindoctor/scraper.log` (rotating).
“Failed: 500” can be a failed-item count, not HTTP 500. Inspect per-item errors.
Logs redact some secrets, not all identifying data.

- **403/login failure:** test credentials in Setup or `config verify-credentials`.
  ScreenScraper account and developer credentials are different; change the
  latter only if you have an issued pair.
- **Rate limit/closed API/non-JSON response:** inspect the provider message,
  wait or check current account limits. Quotas can change; repeated retries
  will not bypass them.
- **Wrong match:** clear the relevant `match` decision or pin a
  `config game-override` ID, then refetch deliberately. Clearing a cache
  does not undo already-written XML.
- **Region tags:** matching normalizes common variant tags; review ambiguity.
- **Matched game, no media URL:** provider search results can be sparse.
  Use the current release, check the detailed provider lookup, try another
  configured source or import local media. Not every provider supplies videos/themes.

## Media and wheels

| Symptom | Check / action |
|---|---|
| Video plays silently | Inspect audio codec; compatible ffmpeg/ffprobe can repair MP3-in-MP4 to AAC. |
| Steam trailer is very short/silent/truncated | Use a current release and compatible ffmpeg; inspect full duration and audio streams. HLS quality/segment failures can produce a seemingly successful short file; retry a supported lower quality if needed. |
| Missing duration but playable file | Built-in header reader covers MP4/M4V/MOV; install ffprobe for other formats. |
| Zero-byte “present” media | Current audit treats it as missing; fetch-media can re-download. Check failed/partial downloads. |
| Local videos never play | Inspect `[video defaults] path=`. A redirect replaces the wheel's own Video folder, with no per-game fallback. |
| Empty wheel despite valid RL ROMs | HyperSpin `roms_only` uses its own path/extensions; RL validation alone does not satisfy that filter. |
| Game hidden or shown as text | Check exact media stem/case/spaces, `wheels_only`, `parents_only`, enabled status and wheel art. |
| No letter-jump graphic | Supply `Images/Letters/<character>.png` for visible title initials; run `doctor`. |
| Starts on a different letter/game | Inspect `wheel-start`; set first/last/random with HyperSpin closed. |
| Missing synthetic art after move | Verify source media, redirects and mirror mode, then rebuild. Hardlinks cannot cross filesystems; auto mode falls back to copies. |
| Custom logo not replaced by installer | Intentional: existing art is preserved. Back it up and remove/replace it deliberately. |

HyperSpin favorites are per-system lists; `fav sync` imports them, and
`fav rebuild --apply` publishes the cross-system wheel. Recent sorts by last
played; Most Played by total time. Both depend on RL statistics and a refresh,
not an always-running SpinDoctor service.

## Cabinet helpers and idle tour

- **Shutdown/restart returns to HyperSpin:** Windows may have refused the action;
  inspect `.spindoctor/toolkit.log`. The helper restarts the frontend on refusal.
- **Exit leaves no taskbar:** Exit To Windows normally restarts Explorer;
  inspect its log before repeating. This affects open Explorer windows.
- **Wrong resolution after a game:** the resolution helper reads HyperSpin's
  configured dimensions and makes a live persistent primary-display change.
- **Tour never changes consoles:** run `doctor` and
  `toolkit idle-tour --self-test`; confirm multi mode, idle mode, LEDBlinky log
  calls, contiguous startup entries, focus and skip/pause rules.
- **Tour changes after a spin, not at video end:** duration was unavailable or
  native joystick safety requires landing-only behavior.
- **Tour advances after seconds:** no usable video, so `NoVideoSeconds` applies.
- **Screen never sleeps:** tour keys reset Windows' idle timer; set
  `TourMaxMinutes`. See [idle tour](idle-tour.md).
- **Ghost tray icons after exit:** force-killed helpers cannot remove icons.
  Hover clears stale entries; prefer graceful exits. Avoid unreviewed scripts
  that manipulate Explorer's memory or kill unrelated helpers.
- **DS4Windows resurfaces:** keep Start Minimized/Close Minimizes on and
  Minimize to Taskbar off; start it only once. [Controller guide](controller-input.md).

## Intro videos

Set both pool and target paths. Enabled videos live directly in the pool;
`Disabled/` is excluded. Add copies in, remove retires, restore re-enables.
Check accepted extensions and actual playable content.

If logon swap fails, test `introvideo swap` manually (preview, then Apply),
check the task's stored EXE path and regenerate autorun after moves/upgrades.
Task registration is Windows-only and separate from startup wheel refresh.

## Launch tests

- **Ranked wheels refuse unfinished test:** run `test --recover`; do not erase
  the active marker. Recovery closes owned processes and restores statistics.
- **Game works manually but test fails:** inspect its screenshot, RL log and
  selected emulator. Raise launch timeout for slow extraction; distinguish
  helper EXEs from the actual game using `test_helper_processes`.
- **False log/window error:** inspect first, then narrowly configure ignored
  log substrings/helper processes/error-window rules. Do not blanket-ignore errors.
- **HyperSpin startup timeout:** check live `log.txt`, intro behavior and
  `test_hyperspin_timeout`; skip-intro depends on logged state.
- **New saves/configs remain:** default cleanup is `report`. `remove` backs up
  eligible newly created files; existing files are never cleanup candidates.

[Test workflow and reports](workflows.md#launch-tests).

## Controls and guns

| Symptom | Check / action |
|---|---|
| Coin/Start fails in one game | Check game-specific device-only binds and effective AHK remap; bind to the key the emulator actually receives. |
| Panel stops working while a controller is on | Some emulators read one input source: [panel and controller together](controller-input.md#panel-and-controller-together). |
| Every game in one MAME loses panel keys | Inspect `default.cfg` for 0-byte/empty maps and a preserved controller/backup map. `doctor` warns about vulnerable old MAME pad codes; repair from a known-good map while closed. |
| Daphne volume key pauses/quits | A zero key slot in `dapinput.ini` can match unmapped media keys. Assign valid deliberate SDL keys; back up first. |
| DemulShooter not found | Set its explicit path, verify the installation and run detection. |
| Gun fails after configure | Check target, per-game ROM requirements, native RL gun settings and duplicate User Functions startup. |
| Gun audit says partial coverage | Only some games/emulators have recognized direct startup. Indirect scripts may work but are not proof for the inspector. |
| Player 2 gun controls player 1 | Supermodel needs raw input and distinct numbered mouse bindings; device order can change. |
| Super Scope starts single-shot | Snes9x turbo starts off; toggle after load and use matching automatic recoil. |

[Light-gun setup and reversion](lightgun.md). Changing SpinDoctor tracking alone
does not remove hooks.

## LEDBlinky

| Symptom | Check / action |
|---|---|
| Search overlay crashes | Preview `ledblinky check` / `fix`; apply the supported hook repair. |
| Unused game buttons animate | Inspect `[GameOptions] GamePlayLWAFile`, not just per-ROM colors. |
| Random frontend animation | Inspect `[FEOptions] FELWAFile`. |
| Generated LWAX has invalid signature | Open in Animation Editor, then Animation → Save As. |
| Some animation buttons stay white | `LightFEControls=1` can override active frontend controls. |
| One board blinks constantly | Possible onboard flash speeds; reset-button-lights is a live PAC-LED64 operation. |
| Controls/colors wrong | Check emulator/ROM names, file schema and the physical input map; run audit/profiles/calibration as appropriate. |
| Coin/Start dark after remapping | Regenerate profiles with current AHK-remap handling and inspect effective keys. |
| LEDs/ServoStik start late | Inspect LEDBlinky startup log/config workload and duplicate startup, not only SpinDoctor. |

Pruned custom controls live in `.spindoctor/ledblinky_library`; preserve them.
Flash-check classifications are not a medical safety guarantee.

## After a drive, OS or emulator change

Run `doctor` and archive checks, then test a game directly and through RL.
Check internal emulator paths, not only `Rom_Path`.

- **Virtual discs:** correct DAEMON Tools path, drive letter and drive type.
- **ScummVM blank/quit:** game paths in `scummvm.ini`; focus/fullscreen problems
  are separate from missing game data.
- **Dolphin fade timeout:** module must match installed Qt/wx generation and
  actual game title/class. Verify focus/fullscreen, not merely process existence.
- **Dolphin opens browser:** inspect effective command/ROM path.
- **RVZ archive rejected:** prefer bare RVZ; allow `rvz` in effective extensions.
- **“No CloseProcess section”:** inspect AHK file for accidental HTML/download
  page content; obtain the intended compatible module from a trusted source.
- **Controller edits revert:** RL may install custom per-game pad/Wii profiles.
- **Keyboard works only with gamepad on:** use explicit Dolphin keyboard device
  qualifiers alongside controller bindings.
- **Sideways Wii directions rotated:** use an appropriate per-game sideways profile.
- **Mapper still starts:** inspect RL Keymapper/User Functions, not just Windows startup.
- **Every launch slow:** check whether RL debug logging was left enabled.
- **Restoring to new drive letters:** preview `backup restore --use-current-paths`.

SpinDoctor cannot universally rewrite third-party emulator internals.
See [cabinet reference](cabinet-architecture-reference.md) and
[migration](workflows.md#migration).

## Reporting a problem

Include version, OS, exact command and a short reviewed error excerpt.
Do not attach complete configuration, unreviewed test screenshots or backups.
[Privacy checklist](privacy.md).
