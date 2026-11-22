# One wheel, several programs

A HyperSpin wheel can list games that run in different programs, such as three
pinball programs on one `Pinball` wheel. RocketLauncher does the routing: a
`System=` line per game in the wheel's `Games.ini` sends it to another system's
settings. Nothing here is done by SpinDoctor; it is a layout SpinDoctor reads.

## Set up the wheel

1. Give every game a name that is unique across the programs, whatever its case.
   RocketLauncher looks the game up by its database name.
2. List them all in `Databases\<Wheel>\<Wheel>.xml`, sorted by title.
3. Add one section per game to `RocketLauncher\Settings\<Wheel>\Games.ini`. A
   blank `Emulator=` uses the other system's default emulator:

   ```ini
   [Example Table (Maker)]
   Emulator=
   System=Pinball Arcade
   ```

4. Put the art in the wheel's own `Media\<Wheel>` folders and leave
   `[video defaults] path=` blank in `Settings\<Wheel>.ini`. A redirect replaces
   the wheel's own videos.
5. Add the wheel to the Main Menu. Hide the old wheels only after one game from
   each program has been played.

If two programs run the same game, match them by the real machine or game rather
than by title: “Family Guy” can be two different tables.

## What `System=` switches

RocketLauncher carries on as if the game had been started from the other system.

| Read from the other system | Where |
|---|---|
| ROM folders, SkipChecks, default emulator, fade and Pause settings | `Settings\<System>\` |
| AHK key profile | `Profiles\AHK\<System>.ahk` |
| User Functions | `Lib\User Functions\<System>.ahk` |
| Play statistics | `Data\Statistics\<System>.ini` |
| Game details and art for the loading and Pause screens | `Databases\<System>\<System>.xml`, `Media\<System>` |

- **User Functions named after the wheel don't run.** Don't use `System=` on a
  wheel that depends on its own, such as a light-gun wheel that sets up the guns.
- **LEDBlinky isn't switched.** HyperSpin passes it the wheel's own name, so the
  lights belong under that name.

## Check it

Start one game per program and read `RocketLauncher.log`. The first line shows
the switch, the second the key profile in use:

```text
Main - Example Table (Maker) contains a System key in ...\Games.ini. Switching systemName to Pinball Arcade
GetAHKProfile - Ended and found: ...\Profiles\AHK\Pinball Arcade.ahk
```

`doctor` follows `System=` in its ROM path check, and `test` names a system that
has no RocketLauncher settings. A program whose module steps through its own menu
needs longer in a launch test before Exit works: use `test --seconds`.

## Retire the old wheels

The programs keep working behind the scenes, so some of each old wheel stays:

| Keep | Why |
|---|---|
| RocketLauncher settings, module, key profile, loading art | `System=` uses them. |
| `Databases\<System>\<System>.xml` | RocketLauncher checks for it at every launch. Recently Played and Most Played skip a game it doesn't list. |
| `Media\<System>` art for the games on the wheel | Recently Played and Most Played take their art from the system the statistics name. Pause shows it too. |
| `Media\Main Menu\Images\Wheel\<System>.png` | The loading screen's system logo, when RocketLauncher has none of its own. |

The Main Menu entry, HyperSpin's `Settings\<System>.ini`, the old Genre lists,
the Main Menu theme and video, and art for games that aren't on the new wheel can
go. Archive them rather than deleting them.

Take a dropped game out of the old system's XML as well. The next
[refresh](standalone-tools.md) then removes it from Recently Played and Most
Played, where it would no longer start.

## Genre lists

HyperSpin reads a Genre list from `Databases\<Wheel>\<Genre>.xml`. A genre with
the wheel's own name, such as `Pinball` on a `Pinball` wheel, is therefore the
wheel's own game list: picking it shows every game, and a tool that writes Genre
lists would overwrite it. Use another name, or one list per program.
