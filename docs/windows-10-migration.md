# Migrating a cabinet from Windows 7 to Windows 10 (with a hardware upgrade)

This guide covers moving an existing HyperSpin + RocketLauncher cabinet from
Windows 7 to Windows 10 on older small-form-factor (SFF) hardware, including the
GPU/SSD upgrade, disk cloning, the Windows install, and — the part that bites
everyone — getting the frontend and emulators working again afterward.

The hardware examples use an **HP EliteDesk 800 G1 SFF** with Haswell-era
Legacy/MBR storage. They are examples, not a current machine inventory or a
guarantee that the same parts fit another SFF model. Verify your system's service
manual, firmware, power limits and component dimensions before buying parts.

> SpinDoctor does not perform any of the steps below — it's a librarian, not an
> installer (see the [README](../README.md)). This doc is reference material for
> cabinet owners doing the OS/hardware move by hand. Once Windows is back up,
> `spindoctor doctor` and the audit commands are the fastest way to confirm the
> library survived. See also [Cabinet architecture reference](cabinet-architecture-reference.md)
> for the startup/exit orchestration and input-stack details this migration
> depends on.

> **OS security support:** This is a legacy migration reference, not a
> recommendation to install an unsupported OS. Standard Windows 10 Home/Pro
> support ended on **October 14, 2025**; application compatibility does not mean
> the OS still receives security updates. Check Microsoft's [Windows 10
> lifecycle](https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro)
> and current [Extended Security Updates eligibility and coverage](https://learn.microsoft.com/en-us/windows/whats-new/extended-security-updates).
> Consumer and commercial ESU programs differ, and LTSC editions have separate
> lifecycles. Prefer an OS and hardware combination that still receives security
> updates; do not assume this guide or a working SpinDoctor installation provides
> that coverage.

---

## 1. Hardware upgrade (SFF constraints)

Many SFF cases require low-profile, slot-powered cards. Slot width and available
power vary by model; a low-profile card is not necessarily single-slot.

| Part | What fits an 800 G1 SFF | Notes |
|---|---|---|
| GPU example | Low-profile **RTX 3050 6 GB** | Check the exact card's bracket, slot width, airflow and PSU requirements. Do not disregard the GPU or system manufacturer's power limits. |
| GPU example | Low-profile **GTX 1650** | Compare the exact model's dimensions and power requirements; availability and value change over time. |
| SSD | **2.5" SATA** (flat), 500 GB–1 TB | **Not** an M.2 stick — this chipset predates M.2/NVMe boot support and a stick won't boot without a BIOS mod. |

Measure the games and emulators you intend to run before upgrading. CPU, graphics
and memory bottlenecks depend on emulator version, resolution and workload.

---

## 2. Clone the old drive (before installing anything)

Clone the **whole disk**, not just C:. HyperSpin/RocketLauncher use hard-coded
paths like `D:\Arcade\…`, so include the boot and cabinet partitions as well as
Windows. Back up any cabinet data on other physical disks separately. A clone
does not guarantee the same drive-letter assignments after a swap or reinstall:
verify letters and paths in Disk Management before launching the frontend.

- Tool: **Hasleo Disk Clone** (free, clones a system disk and resizes to a
  smaller SSD). AOMEI Backupper's free tier only clones *data* disks — not
  usable here.
- Alignment: choose **1M** (a.k.a. SSD alignment). Leave **"sector-by-sector"
  OFF** so it copies used data only and can shrink oversized partitions.
- Connect the SSD with a cheap USB-to-SATA cable to clone, then swap it in.
- **Keep the old HDD.** It becomes your complete, untouched backup for the rest
  of the migration.

---

## 3. Install Windows 10 (Legacy/MBR)

For an existing **Legacy/MBR** installation, this section keeps that layout.
Verify the current boot mode and partition style first; do not infer them from
the Windows version alone.

- If setup errors with *"the selected disk has an MBR partition table … EFI
  systems can only install to GPT"*, your USB booted in **UEFI** mode. Reboot,
  use the firmware's boot menu (**F9** on the example HP), and pick the USB entry
  for Legacy mode if retaining MBR.
- **Do not delete partitions or run `diskpart clean` just to clear a boot-mode
  error.** Those actions can destroy the cabinet data. GPT conversion is not
  inherently destructive: Microsoft's [MBR2GPT](https://learn.microsoft.com/en-us/windows/deployment/mbr-to-gpt)
  can convert an eligible Windows system disk without deleting data. It has
  layout and OS prerequisites, requires UEFI-capable firmware and a subsequent
  switch to UEFI boot, and does not officially support offline conversion of
  Windows 7 system disks. Treat conversion as a separate, backed-up procedure,
  not an extra step in this Legacy/MBR walkthrough.
- Use **Custom install** and select **only the C: partition** (identify by
  the recorded disk, size and layout, not a drive letter; setup's letters may
  differ). Leave the Arcade partition and System Reserved alone. Physically
  disconnect a separate games drive first so it can't be picked by mistake.
  That does not protect a cabinet partition on the same physical disk.
- Edition: use the edition covered by your valid license; do not assume a
  Windows 7 license automatically activates Windows 10. Avoid **Pro N** —
  N editions strip the media components HyperSpin's video playback needs.
- The BIOS listing "UEFI Boot Sources" above "Legacy Boot Sources" is normal;
  the machine falls through to Legacy and boots the SSD. Optionally move Legacy
  to the top for a faster, more predictable boot.

---

## 4. Post-install recovery checklist

Formatting or deleting the Windows partition removes its contents. Some custom
installs may retain files in `Windows.old`, but that is not a backup or a promise
that applications and settings survive. Verify the cabinet data too, rather
than assuming other partitions were untouched. Reinstall, in roughly this order:

| Item | Why | Gotcha |
|---|---|---|
| **DirectX End-User Runtime (June 2010)** | HyperSpin & many emulators need the `d3dx9_*.dll` files Windows 10 doesn't ship | HyperSpin is 32-bit — verify `C:\Windows\SysWOW64\d3dx9_43.dll` actually exists |
| **.NET Framework 3.5** | Older tooling | Enable via "Turn Windows features on or off" |
| **Visual C++ Redistributables (2005–2022, x86+x64)** | Emulator dependencies. An older emulator needs the runtime of the Visual C++ version it was built with: NullDC, PokeMini and Pinball Arcade need **2010 x86** (`msvcr100.dll`), the Dolphin Triforce builds need **2013 x64** (`msvcr120.dll`), and Pinball Arcade's DX11 exe also needs **2012 x86** (`msvcr110.dll`) | Install the older ones too, not just the latest: 2015–2022 share one runtime, but 2005, 2008, 2010, 2012 and 2013 are separate installs. Install both x86 and x64 — a 32-bit emulator needs the x86 package even on 64-bit Windows. A missing one shows as "`MSVCR100.dll` was not found" (or `MSVCR120.dll`, …) when the emulator starts |
| **Java runtime** | ParaJVE (the GCE Vectrex emulator) is a Java program, and a fresh install has no Java | `ParaJVE.exe` is only a launcher that looks for an installed Java (1.5 or later) to run ParaJVE's `.jar`, so the wheel fails until Java is back. Alternative: run the Vectrex wheel through MAME/MESS (`vectrex` driver) and skip Java |
| **GPU driver** | Fixes emulators that render a white screen | See §6 |
| **AutoHotkey 1.1 (ANSI, 32-bit)** | RocketLauncher will not run without it | **Not** AutoHotkey 2.x |
| **DAEMON Tools Lite** | Virtual drive for disc-based games (`vdEnabled=true`) | If it uses SCSI, add a virtual SCSI drive after install. The 64-bit installer uses `C:\Program Files\DAEMON Tools Lite\`, so update `Virtual_Drive_Path` in RocketLauncher's `Settings\RocketLauncher.ini` if it still points at `Program Files (x86)`. `spindoctor doctor` flags a stale path |
| **Control-board software** | WinIPAC, ServoStik driver, etc. | Reinstall to the same paths your configs expect |
| **LEDBlinky** | Button lighting | Program was on C:; profiles survive on the Arcade drive |
| **Fonts** (e.g. Bebas Neue) | HyperSpin themes reference them | `C:\Windows\Fonts` was wiped — easy to forget |

Also re-apply the cabinet settings that lived on C:: **auto-logon** (`netplwiz`),
**auto-start of the frontend** (Startup folder), power plan set to **never
sleep**, and Windows Update **active hours**.

Two more settings decide how fast the cabinet reaches HyperSpin after power-on:

- **Turn off the start-up delay.** Explorer holds back everything in the
  Startup folder and the `Run` registry keys for about 10 seconds after the
  desktop appears, so HyperSpin, and anything else started that way, waits
  too. On one cabinet the desktop was ready at 06:24:20.0 and HyperSpin and
  DS4Windows were started at 06:24:30.5. This turns the delay off for your
  account only; run it in a normal command prompt (no admin needed), and it
  applies from the next sign-in:

  ```bat
  reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize" /v StartupDelayInMSec /t REG_DWORD /d 0 /f
  ```

  To undo it:

  ```bat
  reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize" /v StartupDelayInMSec /f
  ```

- **Keep Fast Startup on** (Control Panel → Power Options → *Choose what the
  power buttons do*). With it, a power-on resumes the kernel session saved at
  shutdown instead of starting Windows from scratch. On one cabinet, sign-in
  came about 1 second after Windows had resumed on those power-ons, and
  11–14 seconds after the kernel started on full boots. To check which kind a
  start was, look in Event Viewer → Windows Logs → System for **Kernel-Boot**
  event **27**: boot type `0x1` is Fast Startup, `0x0` a full boot. **Restart**
  always does a full boot, so use Restart, not Shut down, after installing a
  driver or a Windows update.

---

## 5. HyperSpin on Windows 10 — the silent-exit fix

Symptom: HyperSpin.exe appears in Task Manager for under a second, then vanishes
with **no error and nothing in Event Viewer**. Cause: a Windows 10 build (2004+)
broke the side-by-side assembly method older HyperSpin uses.

**Fix:** drop the community **`sxs.dll`** ("Windows 10 Build 2004 HyperSpin Fix")
into the HyperSpin folder next to `HyperSpin.exe`, and set the exe to **Run as
administrator**. Upgrading to **HyperSpin 1.5.1** (which bundles the fix) is the
fallback — back up `Settings`, `Databases`, and `Media` first and copy only the
loose program files in, never the data folders.

If it still exits instantly, use **Process Monitor** filtered to `HyperSpin.exe`
and read the last non-SUCCESS event — `NAME NOT FOUND` points at a missing file,
`ACCESS DENIED` at a permissions problem.

---

## 6. Emulators render a white screen (audio, no video)

MAME/Dolphin run — you hear audio — but the screen is white. On a fresh install
this is a **missing/incorrect GPU driver**: the card falls back to the generic
"Standard VGA Graphics Adapter" (0 MB VRAM), so Direct3D acceleration is
unavailable and the emulator's `d3d` renderer draws nothing.

- Install the real GPU driver (this is the main reason to be on Windows 10 —
  there is no Win 7 driver for a modern card).
- Confirm Device Manager → Display adapters names the actual GPU, not "Microsoft
  Basic Display Adapter."
- Dual-GPU note: with both the discrete card and Intel HD 4600 enabled, force
  the emulator onto the discrete card (Windows → Graphics settings, or the
  emulator's own adapter dropdown). "Ran fine before the upgrade, lags now" is
  almost always the app defaulting to the Intel chip or a reset config — not the
  new card being weaker.

---

## 7. Common file-operation gotchas after a reinstall

| Symptom | Cause | Fix |
|---|---|---|
| Copy quits partway / "not a single file copies" | Explorer's 260-char path limit (HyperSpin media nests deeply) | Enable Win32 long paths (gpedit), or use **TeraCopy** / **robocopy** which handle long paths |
| Access denied on Arcade files | Files owned by the old Windows account SID | Take ownership: Properties → Security → Advanced → change owner + "replace on subcontainers" |
| GameCube memory card ignored, Dolphin makes a new one | Dolphin defaults to **GCI Folder** mode; old card is a raw `MemoryCardA.USA.raw` | Config → GameCube → Slot A → **Memory Card**, point at the `.raw` (must end `.raw`) |
| Xbox Game Bar "Press X to record" popup | Windows 10 game capture | Settings → Gaming → turn off Game Bar and Captures |
| NVIDIA / Windows Security notifications | Default Win 10 toasts | Settings → System → Notifications; consider Focus Assist for a cabinet |

---

## See also

- [Cabinet architecture reference → HyperSpin Startup/Exit Orchestration](cabinet-architecture-reference.md#hyperspin-startupexit-orchestration) —
  what the startup script INI referenced in §4/§6 actually does, and how the
  controller-mapper stack (DS4Windows/Xpadder/antimicro) layers under it.
- [Controller input: PS4 pad, dual-mode via DS4Windows Auto Profiles](controller-input.md) —
  re-establishing controller menu nav + in-game input after the reinstall in §4,
  without the redundant Xpadder/antimicro mapper stack.
- [Controller input → Removing Xpadder completely](controller-input.md#6-removing-xpadder-completely) —
  if Xpadder resurfaces after the reinstall (it can still be launched from
  RocketLauncher's Keymapper or a leftover Windows autostart even once it's out of
  the HyperSpin Startup Script), the full purge runbook.
- [Troubleshooting](troubleshooting.md) — general error lookup once the cabinet
  is back up.
