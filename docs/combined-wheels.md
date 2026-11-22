# One wheel, several programs

A HyperSpin wheel can list games that run in different programs, such as three
pinball programs on one `Pinball` wheel. RocketLauncher does the routing, with a
line per game in the wheel's `Games.ini`. Nothing here is done by SpinDoctor; it
is a layout SpinDoctor reads.

| | `Emulator=` (recommended) | `System=` |
|---|---|---|
| RocketLauncher runs the game as | the wheel | the other system |
| Settings, game list, media, key profiles, statistics | one set, under the wheel's name | the other system's |
| The old wheels' folders | can all go | several must stay |
| A setting that differs by program | shared, or set in the module | keeps its own |

Use `System=` when a program needs its own system settings and its old wheel
stays anyway.

## Set up the wheel

1. Give every game a name that is unique across the programs, whatever its case.
   RocketLauncher looks the game up by its database name.
2. List them all in `Databases\<Wheel>\<Wheel>.xml`, sorted by title.
3. In `RocketLauncher\Settings\<Wheel>\Emulators.ini`, set the program with the
   most games as `Default_Emulator` and one `Rom_Path` for all of them.
4. Add a section to `Settings\<Wheel>\Games.ini` for every other game:

   ```ini
   [Example Table (Maker)]
   Emulator=Pinball Arcade
   System=
   ```

5. If a program keeps its games inside itself, set `Skipchecks=Rom and Emu` in
   `Settings\<Wheel>\RocketLauncher.ini`. RocketLauncher still looks for a file
   and uses it when there is one, so the other programs keep working. File checks
   can no longer report a missing one.
6. Put each program's AHK key profile in `Profiles\AHK\<Wheel>\<Emulator>.ahk`.
   RocketLauncher looks for a profile named after the game, then the emulator,
   then the system.
7. Put loading art in `Media\Fade\<Wheel>\_Default`, and the HyperSpin art in the
   wheel's own `Media\<Wheel>` folders with `[video defaults] path=` blank. A
   redirect replaces the wheel's own videos.
8. Add the wheel to the Main Menu. Hide the old wheels only after one game from
   each program has been played.

If two programs run the same game, match them by the real machine or game rather
than by title: “Family Guy” can be two different tables.

### Settings that differ by program

Fade, Pause and SkipChecks belong to the system, so one wheel has one set. A
module can still keep Pause off for its own program: with Fade on, add
`pauseEnabled := "false"` on the line after `FadeInStart()`. A module may log
that the wheel is an “unsupported System Name”; that is a warning only.

## Check it

Start one game per program and read `RocketLauncher.log`. `systemName` is the
wheel and the key profile is the program's:

```text
systemName := "Pinball"
GetAHKProfile - Ended and found: ...\Profiles\AHK\Pinball\Pinball Arcade.ahk
```

A program whose module steps through its own menu needs longer in a launch test
before Exit works: use `test --seconds`.

## Retire the old wheels

With `Emulator=`, the old wheels' Main Menu entries, HyperSpin and RocketLauncher
settings, game lists, media, key profiles and statistics can all go. Archive them
rather than deleting them.

- **Statistics:** the old plays are in `Data\Statistics\<old system>.ini`. Copy
  the games' sections into `<Wheel>.ini` to keep them in Recently Played and Most
  Played, which skip a system they no longer know.
- **Launchers:** both wheels still start games under the old system's name until
  their next [refresh](standalone-tools.md).
- **Dropped games:** take them out of the list too. A game that isn't in its
  system's list is left out at the next refresh.

## With `System=`

```ini
[Example Table (Maker)]
Emulator=
System=Pinball Arcade
```

RocketLauncher carries on as if the game had been started from the other system,
and logs `Switching systemName to Pinball Arcade`:

| Read from the other system | Where |
|---|---|
| ROM folders, SkipChecks, default emulator, fade and Pause settings | `Settings\<System>\` |
| AHK key profile | `Profiles\AHK\<System>.ahk` |
| User Functions | `Lib\User Functions\<System>.ahk` |
| Play statistics | `Data\Statistics\<System>.ini` |
| Game details and art for the loading and Pause screens | `Databases\<System>\<System>.xml`, `Media\<System>` |

- **User Functions named after the wheel don't run.** Don't use `System=` on a
  wheel that depends on its own, such as a light-gun wheel that sets up the guns.
- **The old wheel can't go completely.** Keep its RocketLauncher settings, key
  profile and loading art; `Databases\<System>\<System>.xml`, which RocketLauncher
  checks for at every launch; `Media\<System>` art, which Recently Played and Most
  Played take under the name in the statistics; and
  `Media\Main Menu\Images\Wheel\<System>.png`, the loading screen's logo.
- `doctor` follows `System=` in its ROM path check, and `test` names a system that
  has no RocketLauncher settings.

LEDBlinky is never switched: HyperSpin passes it the wheel's own name, so the
lights belong under that name either way.

## Genre lists

HyperSpin reads a Genre list from `Databases\<Wheel>\<Genre>.xml`. A genre with
the wheel's own name, such as `Pinball` on a `Pinball` wheel, is therefore the
wheel's own game list: picking it shows every game, and a tool that writes Genre
lists would overwrite it. Use another name, or one list per program.
