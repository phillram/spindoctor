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
| “Windows cannot find '…\spindoctor-gui.exe'” at log on, once per command | A logon task still runs the EXE from before an upgrade. Open the current SpinDoctor once: it points the wheel refresh and intro video tasks at itself and says so in Output. |

## Library and launch routing

| Symptom | Check / action |
|---|---|
| ROM folder has no database | Preview `add-system` with the exact folder/system name. |
| Main Menu XML parse error | Back up the file, fix malformed XML or restore a known-good version. Do not save an empty replacement over it. |
| No ROMs found | Check extensions, system overrides and effective RocketLauncher `Rom_Path`, including shared/relative/multiple folders. |
| ROMs launch but audit misses them | Use a current release; audit now honors configured RL ROM paths and game overrides. Confirm configuration points at that RL install. |
| Content dupes have different sizes/SHA1s | Recognized NES/FDS/SNES ROM headers are ignored for content pairing. Wrapper equality is not required. |
| “Cannot find Rom” | Check actual stem, allowed extensions, per-game emulator and every effective ROM path. |
| “You do not have a RocketLauncher module for …” | RocketLauncher looks in a module folder named after the emulator entry. An entry that shares a module needs `Module=..\<folder>\<module>.ahk`: [two builds side by side](xbox.md#two-builds-side-by-side). |
| ScummVM: “Cannot find …\scummvm.ini”, or a game won't start | The ScummVM module reads ScummVM's game list from `CustomConfig` under `[Settings]` in its module INI (relative to the RocketLauncher folder), else from `%APPDATA%\ScummVM\scummvm.ini`. Each game's target (its `TargetName`, else its name) needs a section there whose `path=` is the game's folder; after a drive change those paths still name the old drive. `doctor`'s "ScummVM game list" check finds both. |
| Casual Games cannot locate program | Check `gamePath`, executable naming/fallback folder and matching placeholder; unrelated `.txt` files can match accidentally. |
| PCLauncher: “There was an error waiting for the window” for a game with a Japanese (or other non-English) window title | RocketLauncher matches `FadeTitle` byte for byte in the PC's ANSI code page, so the INI must keep the title's original bytes (Shift-JIS for most Japanese games; they look like `‚a‚`‚s` on a Western PC). An editor that saved the INI as UTF-8 replaced them with `�`, and `doctor`'s **PCLauncher INI text** check lists those values. Copy the line back from a backup or the module's original INI, or retype it in an editor saving in the ANSI code page. |
| AHK cannot launch a program | Inspect effective User Functions for stale helper paths and working directories. |
| DOSBox (eXoDOS module): a game stops with a CheckFile error naming `…\!dos\<folder>\dosbox.conf` | The module starts each game with its own config: `<Config_Folder>\<folder>\dosbox.conf`, by default the `!dos` folder beside the games (`!win3x` for a Windows system). `<folder>` is the game's name, or its short name under `[mapping]` in `Modules\DOSBox\ZipMapping\<System>.ini`. Add the config, or map the game to the folder its config is in. `doctor`'s "DOSBox game configs" check lists every game without one. |
| DOS games lose their saves | They save inside their own folder, which RocketLauncher unpacks from the archive at each start. With `7z_Delete_Temp=true` it deletes that folder when the game closes; `7z_Games_to_Keep` (read only from `Settings\RocketLauncher.ini`, for every system) keeps only that many of the newest unpacked games, whatever `7z_Delete_Temp` says ([unpacked games](xbox.md#unpacked-games)). To keep every DOS game: `7z_Delete_Temp=false` and the wheel's own `7z_Extract_Path` in its `RocketLauncher.ini`, and, with `7z_Games_to_Keep` set, `sevenZGamesToKeep := ""` in the DOSBox module before it calls `7zCleanUp`. `doctor` notes it under "DOSBox game configs". |
| A game on a mixed wheel starts with the wrong keys or settings | Read the system name and key profile in `RocketLauncher.log`: [combined wheels](combined-wheels.md#check-it). |
| A Genre menu entry shows the whole wheel | A genre with the wheel's own name is the wheel's own list: [Genre lists](combined-wheels.md#genre-lists). |
| Double menu movement after certain games | A second mapper probably survived launch. Inspect User Functions and RL keymapper settings, not just Windows startup. |
| Refresh stopped after upgrade | Regenerate helpers/tasks with the current EXE path and same tool selections; run `doctor`. |
| Toolkit “exe/FadeTitle/SteamID” error | Reinstall the helper using `install-tools`; module routing and placeholders must agree. |
| Synthetic wheel missing INI/stuck fade | Rebuild with the current version; do not substitute ordinary PC-game INIs for recursive launch routing. |
| Newly added wheel won't open | Check HyperSpin `Settings/<System>.ini` as well as database/media and RL settings. |
| Vectrex games show white vectors, no colour overlay (or another game's) | MESS reads overlays only from `artwork\vectrex\vectrex.lay`, not old `.art` files, and RocketLauncher's MESS module asks for a game's view only when `artwork\Vectrex\<game>.png` is there. Each game needs a view named exactly as its ROM, above any longer name it starts with. `doctor` (Vectrex overlays) says what's missing: [Vectrex overlays](vectrex-overlays.md). |
| “Cannot find” `\Databases\<System>\<System>.xml` | RocketLauncher wants that game list even for a system that isn't on the Main Menu: [an empty one is enough](pinball.md#rocketlauncher-says-it-cant-find-the-systems-database). |
| Visual Pinball X won't start, or ignores its settings file | The stock module is for versions 8 and 9, and 10.8.0 reads an INI beside the program only with `-Ini`: [Visual Pinball X](pinball.md#visual-pinball-x). |
| Panel buttons move BAM's camera or open its menu in Future Pinball | Its default keys are letters: [change them in `bam.cfg`](pinball.md#future-pinball-with-bam). |
| A 3DS game stops at a message that it is encrypted | Azahar runs decrypted `.3ds` / `.cci` dumps only, and `.cia` files must be installed: [3DS games](nintendo-3ds.md#games). |
| DS saves are gone after moving from DeSmuME to melonDS | DeSmuME's `.dsv` adds a footer, and melonDS reads `<name>.sav` from its own save folder: [convert them](nintendo-ds.md#saves-from-desmume). |
| Disc games (Saturn, Neo Geo CD, PC-FX, …) start without their own disc, and DAEMON Tools says “Close all running applications which may use your virtual drive” | An emulator was closed by force while it read the mounted disc, and DAEMON Tools Lite now refuses every mount and unmount, though no program shows a handle on the drive. Restart its “Disc Soft Lite Bus Service” as administrator. That frees the disc but also removes the virtual drive, so add it back (`DTCommandLine.exe --add --type "dt"`) and check its letter (`--get_letter --type "dt" --number 0`): RocketLauncher mounts on SCSI drive 0, else DT drive 0. Close emulators with the exit key, not by ending the process, while a disc is mounted. |
| The screen freezes when a game starts, and only turning the PC off gets out of it | RocketLauncher waits for the game's script with no time limit, so an AutoHotkey or Windows error box behind the frontend can leave it waiting: [the cabinet freezes when a game starts](#the-cabinet-freezes-when-a-game-starts-rocketlauncher). |

### The cabinet freezes when a game starts (RocketLauncher)

RocketLauncher 1.2 builds one AutoHotkey script for each launch: its own settings,
the module, its library files, the User Functions files and, last, the game's
key-remap profile from `Profiles\AHK`, added word for word. The profile is the first
of `<System>\<game>.ahk`, `<System>\<emulator>.ahk`, `<System>.ahk` and
`_Default.ahk` that exists. RocketLauncher runs the script in its own `AutoHotkey.dll`
(AutoHotkey_H 1.1.13) with `ahktextdll`, then waits for it with no time limit, so
whatever stops the script stops the cabinet. Before turning the PC off, press Alt+Tab:
it can show a box hidden behind the frontend. Then check these:

- **An AutoHotkey load error.** One bad line anywhere in the built script, such as
  the same hotkey twice in a profile (“Duplicate hotkey”) or a line this old
  AutoHotkey doesn't know, makes it refuse the whole script with an “AutoHotkey.dll”
  error box. `ahktextdll` doesn't return until that box is closed, and the box opens
  behind the frontend, so the cabinet looks frozen. A fault in a module hangs every
  game that uses it; one in a profile, the games that load that profile. `doctor`'s
  **Keymapper hotkeys** check reads the same profiles for hotkeys that RocketLauncher's
  menu keys switch off.
- **An AutoHotkey runtime error.** An error while the script runs (its box ends
  “The current thread will exit”) stops the module, but the script stays loaded for
  its hotkeys and timers, so RocketLauncher keeps waiting. This box opens behind the
  frontend too. One of these is “Failed attempt to launch program or document” from
  PCLauncher: RocketLauncher's `Process.Run()` starts the program by its bare file
  name inside the start folder, without `UseErrorLevel`, so a `WorkingFolder` that
  doesn't hold the program fails this way. Set `WorkingFolder` to the program's own
  folder, or leave it out to get that folder.
- **A game that can't start.** A program that needs a DLL that isn't there ends at
  once with exit code `0xC0000135`, and Windows shows “System Error … was not found”,
  also when RocketLauncher started it. On a cabinet that box can sit behind the
  frontend. Windows logs each such box in the System log as event 26 from
  “Application Popup”. When a module gives up waiting for a program's window, it
  shows RocketLauncher's own full-screen error screen (`ScriptError` in
  `Lib\Shared.ahk`), which ends by calling `ExitModule()`. RocketLauncher's own
  comment there warns that this has a small chance of looping back into
  `ScriptError`; that is read from the code, not seen on a cabinet. To find the
  missing file, start the game's program from Windows once, or list the boxes
  Windows logged:

  ```powershell
  Get-WinEvent -LogName System -FilterXPath "*[System[Provider[@Name='Application Popup'] and (EventID=26)]]" -MaxEvents 20 |
      Format-List TimeCreated, Message
  ```

- **Antivirus took a game file.** Antivirus programs often quarantine `steam_api.dll`,
  `steam_api64.dll` and similar files from game folders, and the game then can't
  start (above). Defender's own list (`Get-MpThreatDetection`) can have dropped
  detections that its event log still holds: events 1116 (found) and 1117 (action
  taken) in `Microsoft-Windows-Windows Defender/Operational`, with the file after
  “Path:”. This lists the files it quarantined:

  ```powershell
  Get-WinEvent -LogName 'Microsoft-Windows-Windows Defender/Operational' -FilterXPath '*[System[(EventID=1117)]]' |
      Where-Object { $_.Message -match 'Action: Quarantine' } |
      ForEach-Object { '{0:yyyy-MM-dd HH:mm}  {1}' -f $_.TimeCreated, [regex]::Match($_.Message, 'Path:\s*(.+)').Groups[1].Value.Trim() }
  ```

  Restore or replace only files you trust: some are named as trojans, not only as
  cracks.
- **Finding where it stopped.** Below `Logging_Level=10` (under `[Logging]` in
  `Settings\RocketLauncher.ini`), RocketLauncher keeps its log lines in memory and
  writes them to `RocketLauncher.log` only at a few points. One is just before the
  module starts, so after a forced power-off the log can end at “Main - Running
  module”, however far the launch got. At level 10 each line is written as it is
  logged. Set it back afterwards: a high level slows every launch, and `doctor`'s
  **RocketLauncher settings** check notes level 4 or higher.
- **A box asking which AutoHotkey version to run.** Once AutoHotkey v2 is installed,
  `.ahk` files open through its launcher, which picks v1 or v2 from the script and
  can ask in a box when it can't tell. A box like that over a running game takes its
  keyboard focus. Give scripts that run on their own `#Requires AutoHotkey v1.1` (or
  `v2.0`) as their first line, or start them with the right `AutoHotkey.exe`. Never
  put it in RocketLauncher's modules, profiles or User Functions: AutoHotkey 1.1.13
  is older than `#Requires` (added in 1.1.33) and refuses the line (“This line does
  not contain a recognized action”), which is the first cause above.

## Metadata and scraping

Provider requests/errors are in `.spindoctor/scraper.log` (rotating).
“Failed: 500” can be a failed-item count, not HTTP 500. Inspect per-item errors.
Logs redact some secrets, not all identifying data.

- **403/login failure:** test credentials in Setup or `config verify-credentials`.
  ScreenScraper account and developer credentials are different; change the
  latter only if you have an issued pair. ScreenScraper refuses the bundled
  `devid=SpinDoctor` on every request ("Erreur de login : Vérifier vos
  identifiants développeur !"), whatever the user login, and `doctor` warns while
  it is set. A developer pair comes from ScreenScraper on request, through its
  [forum](https://www.screenscraper.fr/forumsujets.php?frub=12&numpage=0); the
  member sign-up page gives only the user login.
- **Rate limit/closed API/non-JSON response:** inspect the provider message,
  wait or check current account limits. Quotas can change; repeated retries
  will not bypass them.
- **Wrong match:** clear the relevant `match` decision or pin a
  `config game-override` ID, then refetch deliberately. Clearing a cache
  does not undo already-written XML.
- **Region tags:** matching normalizes common variant tags; review ambiguity.
- **TheGamesDB finds nothing for a game it has:** its name search matches the
  title's punctuation (`007: Blood Stone`, not `007 blood stone`). SpinDoctor sends
  the ROM name without its region tags and with ` - ` as `: `, then the title's
  parts, longest first (at most three names, each one request). If it still misses,
  look the game up on thegamesdb.net and pin its ID with `config game-override`.
- **Matched game, no media URL:** provider search results can be sparse.
  Use the current release, check the detailed provider lookup, try another
  configured source or import local media. Not every provider supplies videos/themes.
- **A fetch uses up the monthly allowance:** every game looked up costs
  provider requests (`config verify-credentials` shows what's left). `fetch-media`
  looks up only games missing one of the `--types` you name, so name the ones you
  need (`--types wheel`) instead of the default ten. With `--output-dir`, a file is
  missing only when it is in neither HyperSpin's `Media` nor the output folder, so a
  re-run skips what is already staged. A dry run makes the same lookups (cached for
  the apply), so preview a few games with `--game` first.

## Media and wheels

| Symptom | Check / action |
|---|---|
| Video plays silently | Inspect audio codec; compatible ffmpeg/ffprobe can repair MP3-in-MP4 to AAC. |
| Steam trailer is very short/silent/truncated | Use a current release and compatible ffmpeg; inspect full duration and audio streams. HLS quality/segment failures can produce a seemingly successful short file; retry a supported lower quality if needed. |
| Missing duration but playable file | Built-in header reader covers MP4/M4V/MOV; install ffprobe for other formats. |
| Zero-byte “present” media | Current audit treats it as missing; fetch-media can re-download. Check failed/partial downloads. |
| Local videos never play | Inspect `[video defaults] path=`. A redirect replaces the wheel's own Video folder, with no per-game fallback. |
| Empty wheel despite valid RL ROMs | HyperSpin `roms_only` uses its own path/extensions; RL validation alone does not satisfy that filter. |
| Game videos look stretched (too wide or too tall) | HyperSpin stretches a theme's 1024×768 layout to the screen, and with `forceaspect="both"` the video fills its `<video>` box whatever its own shape. Give the box the videos' shape on screen: `w` × (screen width ÷ 1024) : `h` × (screen height ÷ 768) = video width : height (on 1920×1080, `w` × 1.875 : `h` × 1.406). A basic full-screen box plays 4:3 videos at 16:9, and tall two-screen DS or 3DS clips very wide. A game with its own `Themes/<game>.zip` plays its video in that theme, not the wheel's `Default.zip`. One box can't fit videos of two shapes: give the games of the other shape their own copy of the theme, with a box of their shape. `doctor` (Theme video shape) lists the wheel themes that do this, judged by the games that use them, and per wheel the games whose own theme does. |
| TV snow or "No Video" plays for a game | HyperSpin plays `Media/Frontend/Video/No Video.flv` when a game has no video. `generate-media list` shows which; `placeholders --no-video-clip` makes a clearer clip. [Guide](generate-media.md). |
| Reports call a game's media missing though a file is there | Only a SpinDoctor placeholder or drawn title is (`inspect` says so); real media replaces it. `generate-media remove` takes placeholders out. |
| `generate-media record` saves nothing | Its reason is in the output: black or frozen picture, another window in front, or the game closed. Try a longer `--wait`; close overlays; black on every game means the capture can't see that display mode. |
| `generate-media record` stops at once | A key, control-panel button or mouse click stops it. Leave the PC alone, and check for a stuck button. |
| `put-in` or `media-scan --apply` stopped with `[WinError 5] Access is denied: '...tmp' -> '...import-....json'` | Another program (a virus scanner, the search indexer) had the undo record open for a moment. Current builds wait for it and finish the run, with a warning if the record still couldn't be saved. On an older build, run the same `put-in --apply` again for the files it didn't reach. |
| Game hidden or shown as text | Check exact media stem/case/spaces, `wheels_only`, `parents_only`, enabled status and wheel art. |
| Hidden Main Menu wheels show again after `add-system` or `generate-config` | Older builds rewrote `Main Menu.xml` with names only. Hide them again with `mainmenu hide SYSTEM --apply`; both commands now keep `enabled="False"`. |
| No letter-jump graphic | Supply `Images/Letters/<character>.png` for visible title initials; run `doctor`. |
| Starts on a different letter/game | Inspect `wheel-start`; set first/last/random with HyperSpin closed. |
| Piped `mainmenu edit` commands left the Main Menu in the wrong order | Windows PowerShell 5.1 pipes a byte-order mark before the first line, and older builds called that line unrecognised and saved anyway. `edit` now ignores the mark and saves nothing if a piped command fails; put the menu's backup back. |
| `mainmenu sort year` or `manufacturer` sorted A–Z | HyperSpin's own `Main Menu.xml` lists names only; `sort` now says so and stops. Use `sort alpha`, or `reorder` to move wheels. |
| Recently Played or Most Played lost games or art after a wheel was retired | They read the list and media of the system the statistics name: [retire the old wheels](combined-wheels.md#retire-the-old-wheels). |
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
| A MAME driving game won't brake from the panel, or one button does two things in it | Its cfg may keep only a steering wheel's axis for a pedal (increment `NONE`), or put two inputs on one key. `doctor`'s **MAME driving keys** check lists both; set the key in the game's Tab > Input (this Machine). Keys a driver gives its own inputs (often player 2's) never reach a cfg: check that menu too. |
| Panel stops working while a controller is on | Some emulators read one input source: [panel and controller together](controller-input.md#panel-and-controller-together). |
| Every game in one MAME loses panel keys | Inspect `default.cfg` for 0-byte/empty maps and a preserved controller/backup map. `doctor` warns about vulnerable old MAME pad codes; repair from a known-good map while closed. |
| Daphne volume key pauses/quits | A zero key slot in `dapinput.ini` can match unmapped media keys. Assign valid deliberate SDL keys; back up first. |
| PS4 pads do nothing in Xbox games | Cxbx-R misses a virtual Xbox pad that appears as it starts: [bind the real pads](xbox.md#ps4-pads). |
| Panel or pad does nothing in 3DS games | Azahar binds each button to one source, so its profile is the panel or the pad; the module can pick per start: [3DS panel and pads](nintendo-3ds.md#panel-and-pads). |
| PS4 pad does nothing in DS games (melonDS) | melonDS binds the pad by SDL's raw joystick numbers, with the D-pad as buttons: [DS panel and pad](nintendo-ds.md#panel-and-pad). |
| Saturn keys are right in most games but wrong in a few, or an SSF setting doesn't take for one game | SSF keeps each game's settings, keys included, in its own file once the game has run, and uses it over `SSF.ini`: [SSF per-game settings](cabinet-architecture-reference.md#ssf-per-game-settings). |
| DemulShooter not found | Set its explicit path, verify the installation and run detection. |
| Gun fails after configure | Check target, per-game ROM requirements, native RL gun settings and duplicate User Functions startup. |
| Gun audit says partial coverage | Only some games/emulators have recognized direct startup. Indirect scripts may work but are not proof for the inspector. |
| Player 2 gun controls player 1 | Supermodel needs raw input and distinct numbered mouse bindings; device order can change. |
| Super Scope starts single-shot | Snes9x turbo starts off; toggle after load and use matching automatic recoil. |
| A hotkey in an AHK key profile does nothing | RocketLauncher's menu navigation keys replace a plain `key::` in an Internal profile. `doctor` lists them; write `*key::` or a remap (`key::other`). |
| One panel button does two things in a game | The game read the key before RocketLauncher's keymapper could block it: see [games that read the keyboard first](controller-input.md#games-that-read-the-keyboard-first). |
| Future Pinball tables ignore coin, start and flippers | The table's script never started. `doctor` warns when the library is missing: [register it](#register-future-pinballs-type-library). |
| An emulator hotkey on Coin + another button does nothing from the panel | Coin may be the encoder's shift button, which changes what the other buttons send: [hotkeys and the shift button](controller-input.md#emulator-hotkeys-and-the-encoders-shift-button). |

[Light-gun setup and reversion](lightgun.md). Changing SpinDoctor tracking alone
does not remove hooks.

### Register Future Pinball's type library

Future Pinball's table scripts need the type library built into `Future Pinball.exe`
to be registered with Windows. A folder copied from another PC has no registration,
and the program doesn't add one when it runs as a normal user. Symptoms: tables load
and the camera keys (F1 to F8) work, but coin, start, flippers and the score displays
do nothing. Run this in PowerShell with Future Pinball closed, using your own path;
it registers the library for your Windows user only and needs no administrator rights.
0 means it worked. Run it again if Future Pinball moves.

```powershell
$exe = 'E:\Cabinet\Emulators\Future Pinball\Future Pinball.exe'
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using CT = System.Runtime.InteropServices.ComTypes;
public static class FpTypeLib {
    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode)] static extern int LoadTypeLibEx(string file, int kind, out CT.ITypeLib lib);
    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode)] static extern int RegisterTypeLibForUser(CT.ITypeLib lib, string path, string help);
    public static int Register(string exe) {
        CT.ITypeLib lib;
        int hr = LoadTypeLibEx(exe, 2, out lib);
        return hr != 0 ? hr : RegisterTypeLibForUser(lib, exe, null);
    }
}
"@
[FpTypeLib]::Register($exe)
```

## LEDBlinky

| Symptom | Check / action |
|---|---|
| Search overlay crashes | `ledblinky check --menus Search,Genre,Favorites` finds LEDBlinky process hooks in a menu's `Settings.ini`; preview `ledblinky fix --menus …`, then `--apply`. An entry for the menu in `LEDBlinkyControls.xml` doesn't help: LEDBlinky never looks menus up there. |
| `doctor` warned "crash risk on: Genre, Favorites" | A false alarm from older versions, which wanted a `<game>` entry per menu in `LEDBlinkyControls.xml`. LEDBlinky reads only its `<emulator>` and `<frontEnd>` sections, and HyperSpin doesn't call it when these menus open. `<game name="Search" … spindoctor="compat-stub" />` lines an older `ledblinky fix` added are ignored; leave or delete them. |
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
- **ScummVM blank/quit:** game paths in `scummvm.ini` (`doctor` checks them); focus/fullscreen problems
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
- **A game is unpacked again at every start:** RL keeps only the last ones, and only
  while their size still matches: [unpacked games](xbox.md#unpacked-games).
- **Xbox games crawl:** one full CPU core and an idle GPU point to Cxbx-R's
  [core setting or build](xbox.md#one-cpu-core-is-full-and-the-game-crawls).
- **An Azahar setting doesn't take:** its `\default` line still says `true`, so Azahar
  ignores the value: [set both lines](nintendo-3ds.md#a-setting-that-doesnt-take).
- **A melonDS setting doesn't take, or a pause-menu save slot opens a file box:**
  melonDS writes `melonDS.toml` back when it closes, screen smoothing is now a
  per-window setting, and F9 opens a file box: [melonDS settings](nintendo-ds.md#settings),
  [save states](nintendo-ds.md#starting-games-from-rocketlauncher).
- **After moving to a newer RetroArch, panel buttons slow the game or start netplay,
  a game-name popup shows at every start, the picture sits off-centre, or saves
  seem gone:** the config came from the older version, and newer versions sort
  saves into core folders: [moving to a current RetroArch](cabinet-architecture-reference.md#moving-retroarch-wheels-to-a-current-retroarch).
- **MSU-1 (SNES CD) games black, or without their CD music, after a RetroArch
  upgrade:** current cores don't read `.bml` manifests, and bsnes shows these packs
  black: [MSU-1 packs](cabinet-architecture-reference.md#msu-1-snes-cd-packs).
- **Restoring to new drive letters:** preview `backup restore --use-current-paths`.

SpinDoctor cannot universally rewrite third-party emulator internals.
See [cabinet reference](cabinet-architecture-reference.md) and
[migration](workflows.md#migration).

## Reporting a problem

Include version, OS, exact command and a short reviewed error excerpt.
Do not attach complete configuration, unreviewed test screenshots or backups.
[Privacy checklist](privacy.md).
