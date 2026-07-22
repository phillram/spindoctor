# Migrating a cabinet from Windows 7 to Windows 10 (with a hardware upgrade)

This guide covers moving an existing HyperSpin + RocketLauncher cabinet from
Windows 7 to Windows 10 on older small-form-factor (SFF) hardware, including the
GPU/SSD upgrade, disk cloning, the Windows install, and — the part that bites
everyone — getting the frontend and emulators working again afterward.

It is written from a real migration on an **HP EliteDesk 800 G1 SFF**
(i5-4590, 32 GB RAM, Intel HD 4600 → discrete GPU) but the gotchas apply to any
Haswell-era Legacy/MBR cabinet.

> SpinDoctor does not perform any of the steps below — it's a librarian, not an
> installer (see the [README](../README.md)). This doc is reference material for
> cabinet owners doing the OS/hardware move by hand. Once Windows is back up,
> `spindoctor doctor` and the audit commands are the fastest way to confirm the
> library survived. See also [Cabinet architecture reference](cabinet-architecture-reference.md)
> for the startup/exit orchestration and input-stack details this migration
> depends on.

---

## 1. Hardware upgrade (SFF constraints)

SFF cases only take **low-profile, single-slot, slot-powered** cards, and the
stock ~240 W PSU rules out anything needing a power connector.

| Part | What fits an 800 G1 SFF | Notes |
|---|---|---|
| GPU | Low-profile **RTX 3050 6 GB** (~70 W, slot-powered) | Ships with a tall bracket attached + a low-profile bracket in the box — **swap to the low-profile bracket** or the case won't close. Ignore the "300 W PSU recommended" label; the 240 W HP PSU runs it. |
| GPU (alt) | Low-profile **GTX 1650** | Was the value pick, but new stock is now scarce/overpriced — the 3050 is the better buy. |
| SSD | **2.5" SATA** (flat), 500 GB–1 TB | **Not** an M.2 stick — this chipset predates M.2/NVMe boot support and a stick won't boot without a BIOS mod. |

Do **not** bother upgrading RAM, CPU, or motherboard for emulation up to Wii —
they're not the bottleneck.

---

## 2. Clone the old drive (before installing anything)

Clone the **whole disk**, not just C:. HyperSpin/RocketLauncher use hard-coded
paths like `D:\Arcade\…`, so a full-disk clone preserves every partition's
**drive letter and path**, and nothing needs reconfiguring.

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

A Windows 7 cabinet is almost always **Legacy/MBR**, and the install must match.

- If setup errors with *"the selected disk has an MBR partition table … EFI
  systems can only install to GPT"*, your USB booted in **UEFI** mode. Reboot,
  press **F9**, and pick the USB entry **without** the `UEFI:` prefix (Legacy).
  Do **not** convert the disk to GPT — that would wipe the Arcade partition.
- Use **Custom install** and select **only the C: partition** (identify by
  size — the install screen shows no drive letters). Leave the Arcade partition
  and System Reserved alone. Physically disconnect the games drive first so it
  can't be picked by mistake.
- Edition: **Windows 10 Pro** (Win 7 Ultimate upgrades to Pro). Avoid **Pro N** —
  N editions strip the media components HyperSpin's video playback needs.
- The BIOS listing "UEFI Boot Sources" above "Legacy Boot Sources" is normal;
  the machine falls through to Legacy and boots the SSD. Optionally move Legacy
  to the top for a faster, more predictable boot.

---

## 4. Post-install recovery checklist

A clean install wipes C:, so everything that lived there is gone (the Arcade
drive is fine). Reinstall, in roughly this order:

| Item | Why | Gotcha |
|---|---|---|
| **DirectX End-User Runtime (June 2010)** | HyperSpin & many emulators need the `d3dx9_*.dll` files Windows 10 doesn't ship | HyperSpin is 32-bit — verify `C:\Windows\SysWOW64\d3dx9_43.dll` actually exists |
| **.NET Framework 3.5** | Older tooling | Enable via "Turn Windows features on or off" |
| **Visual C++ Redistributables (2005–2022, x86+x64)** | Emulator dependencies | Install the older ones too, not just the latest |
| **GPU driver** | Fixes emulators that render a white screen | See §6 |
| **AutoHotkey 1.1 (ANSI, 32-bit)** | RocketLauncher will not run without it | **Not** AutoHotkey 2.x |
| **DAEMON Tools Lite** | Virtual drive for disc-based games (`vdEnabled=true`) | If it uses SCSI, add a virtual SCSI drive after install |
| **Control-board software** | WinIPAC, ServoStik driver, etc. | Reinstall to the same paths your configs expect |
| **LEDBlinky** | Button lighting | Program was on C:; profiles survive on the Arcade drive |
| **Fonts** (e.g. Bebas Neue) | HyperSpin themes reference them | `C:\Windows\Fonts` was wiped — easy to forget |

Also re-apply the cabinet settings that lived on C:: **auto-logon** (`netplwiz`),
**auto-start of the frontend** (Startup folder), power plan set to **never
sleep**, and Windows Update **active hours**.

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
- [Troubleshooting](troubleshooting.md) — general error lookup once the cabinet
  is back up.
