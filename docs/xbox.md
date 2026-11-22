# Xbox games in Cxbx-Reloaded

SpinDoctor doesn't install emulators or supply games. These notes are about running
original Xbox games in Cxbx-Reloaded (Cxbx-R) from RocketLauncher. Checked on a
4-core Windows 10 PC with the builds `0b69563` (November 2022), `535c8c9` (April 2026)
and `585c49a` (the newest then): check again after an upgrade, on a copy first.

Cxbx-R uses the `settings.ini` beside `cxbx.exe`, or the one in the user's AppData
when there isn't one. Close Cxbx-R and back the file up before editing it.

## One CPU core is full and the game crawls

By default Cxbx-R keeps the Xbox's own threads on one CPU core. A game can then fill
that core while the other cores and the graphics card sit idle, and stay on a logo for
a minute. Two things can help, and neither helps every game:

- **Another build.** The default is the same in the 2022 and April 2026 builds, yet a
  game that needed two minutes to reach its menu in the first ran its menus at 53 fps
  in the second.
- **All cores:** `UseAllCores = true` under `[hack]` in `settings.ini` (**Run Xbox
  threads on all cores** in the Hacks menu). One game went from 7 fps to 54–60. Two
  others hung with it in the April 2026 build.

So set it per game. The RocketLauncher module can write it before each start. Back up
the module, then add these lines to `Modules\CxbxR\CxbxR.ahk` before its `Run(`:

```autohotkey
useAllCores := IniReadCheck(settingsFile, "settings|" . dbName, "Use_All_Cores", "false",,1)
cxbxIni := emuPath . "\settings.ini"
If FileExist(cxbxIni)
	IniWrite(useAllCores, cxbxIni, "hack", "UseAllCores", 1)
```

The `If` matters: a `settings.ini` created beside `cxbx.exe` with this one line would
replace the AppData settings. The game's own section in `CxbxR.ini` overrides
`[settings]`:

```ini
[settings]
Use_All_Cores=false
[Example Game (USA)]
Use_All_Cores=true
```

## Try a build in a copy first

A newer build isn't always better. Of 16 games on one cabinet, three ran only on the
2022 build and most of the rest ran well on the April 2026 one. The newest build drew
one game's screens wrong and hung another.

1. Copy the whole emulator folder. The copy is separate only if it has its own
   `settings.ini` with `DataStorageToggle = 0x1` (data beside the program); otherwise it
   shares the AppData settings and saves.
2. Try every game in it, on one core and on all, past the menus and into play.
3. Only then replace the live folder, and keep the old one.

### Two builds side by side

If some games need the old build, keep both. Add a second entry to
`Settings\Global Emulators.ini`:

```ini
[CxbxR 2022]
Emu_Path=..\Emulators\CxbxR 2022\cxbx.exe
Rom_Extension=zip|rar|7z|xbe
Module=..\CxbxR\CxbxR.ahk
```

Then name it in the game's section of `Settings\<System>\Games.ini`:

```ini
[Example Game (USA)]
Emulator=CxbxR 2022
System=
```

RocketLauncher looks for `Module=` in `Modules\<entry name>`, so any second entry that
shares a module needs the `..\<folder>\` part. Without it RocketLauncher stops with
“Cannot find” `...\Modules\CxbxR 2022\CxbxR.ahk` and “You do not have a RocketLauncher
module for CxbxR 2022”. The two entries then share the module's INI too, so each game's
section goes in the one `CxbxR.ini`. The key profile is looked up under the entry's own name.

## PS4 pads

Cxbx-R ignores new XInput pads while it starts. A DS4Windows auto profile that turns the
pad into an Xbox pad for the game does so about a second after that start, so the pad
does nothing for the whole game. Bind the real pads through SDL instead; DS4Windows
doesn't have to switch anything, but it must not hide them.

Add a profile to `settings.ini` under the next free number. These are the button and axis
numbers with SDL 2.30.11; L1 and R1 are White and Black:

```ini
[input-profile-3]
Type = 1
ProfileName = "PS4 Pad"
DeviceName = SDL/0/PS4 Controller
D Pad Up = Button 11
D Pad Down = Button 12
D Pad Left = Button 13
D Pad Right = Button 14
Start = Button 6
Back = Button 4
L Thumb = Button 7
R Thumb = Button 8
A = Button 0
B = Button 1
X = Button 2
Y = Button 3
Black = Button 10
White = Button 9
L Trigger = Axis 4+
R Trigger = Axis 5+
Left Axis X+ = Axis 0+
Left Axis X- = Axis 0-
Left Axis Y+ = Axis 1-
Left Axis Y- = Axis 1+
Right Axis X+ = Axis 2+
Right Axis X- = Axis 2-
Right Axis Y+ = Axis 3-
Right Axis Y- = Axis 3+
Motor =
```

Each port then names the device and the profile. The second pad is `SDL/1` in
`[input-port-1]`:

```ini
[input-port-0]
Type = 1
DeviceName = SDL/0/PS4 Controller
ProfileName = "PS4 Pad"
```

- **Check the order.** SDL lists the real pads and DS4Windows' virtual PS4 pads together.
  On the cabinet checked, the real ones came first. With its debug log on, Cxbx-R names
  them in order (`Added device: SDL/0/PS4 Controller`).
- **An old `SDL2.dll` may see no pads.** Version 2.0.20, in the 2022 build, found none
  where 2.30.11 found them all. The April 2026 build's `SDL2.dll` worked in the 2022
  build too.
- **No rumble** in this profile: the log says the pads don't support it through SDL.
- **A port takes one device,** so a panel and a pad can't share one. The module can pick
  before each start, when it knows whether a pad is on (`Panel P1` is a keyboard profile):

```autohotkey
If FileExist(cxbxIni) {
	IniWrite(padOn ? "SDL/0/PS4 Controller" : "DInput/0/KeyboardMouse", cxbxIni, "input-port-0", "DeviceName")
	IniWrite(padOn ? """PS4 Pad""" : """Panel P1""", cxbxIni, "input-port-0", "ProfileName")
}
```

`padOn` can come from Windows' `joyGetPosEx` and `joyGetDevCaps`: look for a device that
answers and has Sony's vendor ID, `054C`. Don't count DS4Windows' virtual PS4 pads
(`054C:05C4`, also the first DualShock 4 model) as extra ones. The pad has to be on before
the game starts.

## Unpacked games

- **`7z_Games_to_Keep=1`** under `[7z]` in `Settings\RocketLauncher.ini` keeps the last
  unpacked game when it closes, even with `7z_Delete_Temp=true`. Every other archive is
  unpacked again at each start.
- **A kept game is reused only if its total size still equals the archive's.** A game
  that adds or deletes a file in its own folder is unpacked again in full.
- **Some games change their own folder.** One sometimes deleted one of its files seconds
  after starting; started again from that folder, it stopped at “There's a problem with
  the disc”. RocketLauncher's size check unpacks such a game again, but a folder you
  unpacked yourself stays broken. As a precaution the module can make that game's files
  read-only while it runs, as long as it doesn't need to write there:

```autohotkey
FileSetAttrib, +R, %romPath%\*.*, 0, 1   ; after 7z(), before Run()
FileSetAttrib, -R, %romPath%\*.*, 0, 1   ; after the emulator closes, before 7zCleanUp()
```

- **“Finished 7z extraction which took N seconds” is often wrong.** RocketLauncher
  subtracts the two clock readings as plain numbers, so 17 seconds can be logged as 4057.
  Compare the times of the log lines.

## A passed launch test is not a playable game

A [launch test](workflows.md#launch-tests) can pass on a logo. Look at the screenshot,
give slow starters more time (`--seconds`, and `test_launch_timeout` for long unpacking),
then play each game past its menus. One game reached its menus at 55 fps and hung when a
new game started; another stayed black about one start in three.
