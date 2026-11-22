# Legacy Windows cabinet migration

This is a manual OS/hardware checklist, not a SpinDoctor feature.
Windows 10 Home/Pro standard support ended October 14, 2025.
Check Microsoft's [lifecycle](https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro)
and [ESU coverage](https://learn.microsoft.com/en-us/windows/whats-new/extended-security-updates)
for your edition; prefer supported hardware/OS. A working Win7-compatible
SpinDoctor binary does not make its OS secure.

## Before changing hardware or Windows

1. Make and verify a whole-disk image plus backups of separate game disks and
   `%USERPROFILE%\.spindoctor`. A settings/database snapshot alone is not enough.
2. Record disk layout, drive letters, firmware boot mode, licenses, controller
   mappings, scheduled tasks and application versions.
3. Check the exact SFF case/PSU/slot constraints before selecting a GPU or SSD.
4. Keep an untouched recovery disk. Cloning does not guarantee drive letters.

Do not delete partitions or run `diskpart clean` to fix a boot-mode mismatch.
Legacy/MBR and UEFI/GPT require a deliberate backed-up procedure;
[MBR2GPT](https://learn.microsoft.com/en-us/windows/deployment/mbr-to-gpt)
has prerequisites and does not officially support offline Windows 7 conversion.

## Restore cabinet dependencies

Install trusted vendor packages matching the applications you actually use:
GPU/control-board/gun drivers, required DirectX components, .NET, x86/x64 Visual
C++ runtimes, RocketLauncher's compatible AutoHotkey v1 setup, and virtual-drive
software. Newer VC++ runtimes do not replace every older generation.
N editions may need media components.

Verify virtual-drive executable/drive-letter settings, fonts, emulator portable
configs, Bluetooth pairing and startup tasks. Restart after driver changes.
Do not copy random DLL fixes or disable security controls as a blanket remedy.

## Validate

Restore intended drive letters before launching. Run `spindoctor doctor`,
`audit --all` and archive checks; test representative games directly, then
through RocketLauncher/HyperSpin. Check video/audio, fullscreen/focus, controls,
gun recoil and LEDs, not only process startup.

Regenerate SpinDoctor helpers/tasks after moving the EXE.
See [migration workflows](workflows.md#migration) and
[troubleshooting](troubleshooting.md).
