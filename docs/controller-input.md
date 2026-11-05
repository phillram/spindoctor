# PS4 controller: menu keystrokes + in-game controller (DS4Windows Auto Profiles)

This example uses a **PS4 DualShock 4** for two different jobs. Adapt the paths and key mappings to your cabinet; it is not a record of a reader's current setup.

1. **Navigate the HyperSpin menus**, which read the **keyboard** only.
2. **Play games**, where emulators expect an **XInput (Xbox 360) controller**.

The solution is **DS4Windows Auto Profiles** — DS4Windows switches profiles
automatically based on the focused program, so the pad sends keystrokes while
HyperSpin is in front and behaves as a normal Xbox controller the moment a game
launches. One tool does both jobs, with no separate key-mapper and no reliance
on HyperSpin's native joystick support.

> This is the setup walkthrough for the DS4Windows example. Keep DS4Windows independent of HyperSpin's lifetime (see §3). The [cabinet reference](cabinet-architecture-reference.md#controller-input--ds4windows-and-xinput) supplies integration context; do not run both this setup and an older separate mapper stack.

---

## 1. Why not the two obvious alternatives

| Approach | Why it was rejected |
|---|---|
| **HyperSpin native joystick nav** (`Joysticks_Enabled=True` in the HyperSpin Startup Script) | Unreliable with a Bluetooth PS4 pad; the `Joy*` axis/button numbers in the INI don't match how a raw DS4 reports itself. In testing the pad did nothing in menus. |
| **The old mapper stack** (DS4Windows → Xpadder **and** antimicro → keyboard) | Redundant (two key-mappers), and DS4Windows was launched by *both* Windows startup and the HyperSpin Startup Script, producing a duplicate window that wouldn't minimize. |

Auto Profiles replaces both: it keeps the reliable "pad sends keystrokes"
behaviour for menus, drops the extra mappers, and — because DS4Windows keeps the
virtual XInput device alive the whole time — never disconnects the controller
mid-game.

---

## 2. The keyboard profile (Player 1)

HyperHQ's Player-1 menu keys map to the pad like this — see [Cabinet architecture
reference → HyperSpin frontend menu controls](cabinet-architecture-reference.md#hyperspin-frontend-menu-controls-player-1--player-2)
for where the "sends key" / "HyperSpin action" columns below come from. Create a
DS4Windows profile named **`HyperSpin-Keys`** and bind each control to the
**Keyboard** output shown:

| PS4 button | Sends key | HyperSpin action |
|---|---|---|
| D-pad Up (+ Left Stick Up) | Up Arrow | Up — scroll up one game |
| D-pad Down (+ Left Stick Down) | Down Arrow | Down — scroll down one game |
| D-pad Left (+ Left Stick Left) | Left Arrow | Skip Up — jump back a letter |
| D-pad Right (+ Left Stick Right) | Right Arrow | Skip Down — jump forward a letter |
| Cross ✕ | Enter | Start — launch / select |
| Circle ○ | Escape | Exit — back out |
| Triangle △ | C | HyperSpin — jump to main menu |
| Square □ | A | Favorites |
| L1 | Left Arrow | Skip Up (fast) |
| R1 | Right Arrow | Skip Down (fast) |
| L2 | B | Genre |

The two numeric skips (Skip Up/Down Num = `D` / `E`) are omitted as redundant
with the arrow skips; map them to R2 / Touchpad if very-fast jumps are wanted.

> **Player 2:** for a second pad, make a second profile bound to the Player-2
> keys (Up `N`, Down `Q`, Skip Up `M`, Skip Down `O`, HyperSpin `I`, Genre `H`,
> Favorites `G`, Start `R`, Exit `Escape`) and assign it to Controller 2 in the
> same Auto Profile entry.

---

## 3. DS4Windows configuration

1. **Two profiles:**
   - `Controller` — the normal Xbox 360 mapping (used in games).
   - `HyperSpin-Keys` — the keyboard map in §2.
2. **Auto Profiles tab:** enable Auto Profiles → **Add Program** →
   `D:\Arcade\HyperSpin.exe` → assign Controller 1 → `HyperSpin-Keys`. Set the
   **default** profile (everything else) to `Controller`.
3. **Start DS4Windows at Windows login** (Startup folder or Task Scheduler),
   **not** from the HyperSpin Startup Script. Its lifetime must be independent of
   HyperSpin — if it dies when HyperSpin exits, an active Dolphin session loses
   the controller (`[disconnected] DInput/0/Wireless Controller`) until
   DS4Windows is restarted.

Emulators stay configured for the DS4Windows virtual pad — e.g. Dolphin's GCPad
Port 1 = `XInput/0/Gamepad` (see the [architecture reference](cabinet-architecture-reference.md#controller-input--ds4windows-and-xinput)).

---

## 4. HyperSpin Startup Script changes

If your cabinet uses `HyperSpin Startup Script.ini` (for example under
`<hyperspin_dir>\Utilities\Startup and Exit\`), simplify it for this design:

- `[Controls] Joysticks_Enabled=False` — native joystick nav stays **off** (DS4Windows drives menus now).
- `[Startup]` — remove duplicate `DS4Windows.exe` launches and unused Xpadder/antimicro helpers. Keep unrelated tools only if needed. Keep numbered entries contiguous: the script stops reading at the first missing `Program_To_Run_Target_N`. For PAC-LED64 flash reset, see the [separate hardware example](cabinet-architecture-reference.md#diagnosing-buttons-that-flash-on-one-board-pac-led64-on-board-flash-mode).
- `[Exit]` — remove DS4Windows kill entries so a game cannot lose its virtual pad when HyperSpin closes. Remove obsolete mapper kill entries; keep any independently needed exit script.

> Inspect any exit script before retaining it. Use explicit paths and do not copy a cache-deletion command from another cabinet without checking its target.

---

## 5. Result

| Context | Pad behaves as | Driven by |
|---|---|---|
| HyperSpin menus | Keyboard (arrows / Enter / Esc / letters) | DS4Windows `HyperSpin-Keys` profile |
| In a game | Xbox 360 controller (XInput) | DS4Windows `Controller` profile |
| Transition | Auto-switch on window focus | DS4Windows Auto Profiles |

No native joystick nav, no separate key-mapper, no duplicate DS4Windows window,
and the controller never drops mid-game.

---

## 6. Removing Xpadder completely

If DS4Windows Auto Profiles replaces Xpadder for your cabinet (§1), but Xpadder
still launches or throws an error after you've disabled the obvious autostarts,
it's because Xpadder can be started from **more than one** place. The easily-missed
one is **RocketLauncher's own Keymapper**, which can be pointed at Xpadder —
identifiable in a RocketLauncher log by entries such as:

```
keymapperEnabled := "true"
keymapper        := "xpadder"
xpadderFullPath  := "D:\Arcade\Utilities\Xpadder\Xpadder.exe"
```

With `keymapperAHKMethod := "Internal"` RocketLauncher reads the Xpadder *profile
format* through its own AHK engine and does **not** launch `Xpadder.exe` (the
*External* method does); either way it's a live reference, and when no profile
matches the game it just logs `GetAHKProfile - Keymapper support is enabled … could
not find a … profile`. DS4Windows Auto Profiles already maps the pad, so RL
keymapping is redundant.

Clear every launch point, in this order:

1. **RocketLauncher Keymapper** — RocketLauncherUI → **Global → Keymapper** → set
   **Keymapper Enabled = false**. If RLUI doesn't expose it, hand-edit `RocketLauncher\
   Settings\Global RocketLauncher.ini` → `[Keymapper]` → `Keymapper_Enabled=false`
   (close RLUI first, or it rewrites the file on exit). A keymapper still pointed at a
   renamed/missing Xpadder shows as "Not found" in RLUI — that's the live reference.
2. **Windows autostart** — Task Manager → **Startup** tab (covers the Startup folder
   *and* the registry Run keys), plus `shell:startup` / `shell:common startup`,
   `taskschd.msc`, and `HKCU\…\CurrentVersion\Run` (+ `RunOnce`, `HKLM`,
   `Wow6432Node`).
3. **HyperSpin Startup Script** — confirm `[Startup]`/`[Exit]` in `HyperSpin Startup
   Script.ini` has no Xpadder entry ([§4](#4-hyperspin-startup-script-changes) —
   adapt this to your own startup list).
4. **Uninstall the exe** — `spindoctor tools-audit` (or `where /r D:\ Xpadder.exe`)
   reports where `xpadder.exe` lives. Once the steps above are clear, uninstall it /
   delete the folder(s) so nothing can start it even if a stray reference survives.

> **Which one is the culprit?** Use *when* the error fires to tell them apart. A
> **game launch/exit** error is the RocketLauncher Keymapper (step 1); a **Windows
> boot/logon** error is an autostart (steps 2–3). To catch the launcher live, leave
> the Xpadder error dialog open and run the PowerShell parent-process query in
> [Troubleshooting → Xpadder still launches](troubleshooting.md#xpadder-still-launches-and-throws-errors-after-i-disabled-it-in-windows-and-hyperspin).
>
> Check the actual launcher rather than assuming a clean Windows Startup list
> rules Xpadder out: RocketLauncher's Keymapper can still invoke it at game
> launch or exit. Keep only one menu-mapping path active.

See also [Cabinet architecture reference → HyperSpin Startup/Exit
Orchestration](cabinet-architecture-reference.md#hyperspin-startupexit-orchestration).
