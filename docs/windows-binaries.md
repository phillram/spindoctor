# Windows binaries

No Python installation is needed. Get a zip from the
[latest release](https://github.com/phillram/spindoctor/releases/latest):

| Edition | Windows 10/11 | Windows 7 SP1/8/8.1 | Contents |
|---|---|---|---|
| GUI | `spindoctor-gui-win10.zip` | `spindoctor-gui-win7.zip` | `spindoctor.exe` |
| CLI | `spindoctor-cli-win10.zip` | `spindoctor-cli-win7.zip` | `spindoctor-cli.exe` |

Each EXE embeds all workers and deployment media and works alone. Separate
Favorites/Recent/Stats EXEs are no longer shipped. The Win7 build uses Python
3.8.10/PyInstaller 5.13.2; the modern build uses Python 3.12/PyInstaller 6.x
(bootloader minimum Windows 8.1). Use the Win7 download on Windows 8.
Windows 7 RTM, XP and Vista are unsupported.

Application compatibility does not imply OS security support. See the
[legacy OS guide](windows-10-migration.md).

## Install and first run

1. Compare the zip's SHA-256 with `SHA256SUMS.txt` from the release.
   PowerShell: `Get-FileHash .\spindoctor-gui-win10.zip -Algorithm SHA256`.
2. Extract the EXE to a stable folder, such as `C:\SpinDoctor`.
3. Open **`spindoctor.exe`**, save cabinet paths in **Setup**, then run Diagnostics.

For CLI use, open a terminal first:

```text
C:\SpinDoctor\spindoctor-cli.exe --version
C:\SpinDoctor\spindoctor-cli.exe config init
C:\SpinDoctor\spindoctor-cli.exe doctor
```

You may add the folder to your user PATH through Windows Environment Variables.
Do not replace PATH with a copied `setx` command. Examples elsewhere use the
pip name `spindoctor`; substitute `spindoctor-cli`.

## GUI launcher

See the [page guide and screenshots](gui.md). The GUI relaunches itself with
`--run-tool` for workers. One-file builds extract to a temporary runtime folder;
do not remove that folder while they run.

## Wiring into HyperSpin

Use [install-tools](standalone-tools.md), not the source checkout's `.bat` files,
to generate wrappers pointing at your EXE. Embedded wheel workers can also be
called directly:

```text
spindoctor-cli.exe --run-tool spindoctor-fav rebuild --apply
```

For a windowed GUI EXE in a `.bat`, use `start "" /B /WAIT` to wait for completion.

## Updating

Close SpinDoctor and its workers, replace the EXE, then reopen it. Settings live
in `%USERPROFILE%\.spindoctor`, not beside the program.

After moving the EXE or upgrading from v2, regenerate `install-tools` helpers
with the same selections, re-enable startup wheel refresh, and reinstall intro
autorun if used. These embed absolute EXE paths. `doctor` flags stale helpers.

## Troubleshooting

- **CLI flashes and closes:** run `spindoctor-cli.exe` in a terminal.
  `spindoctor.exe` is the GUI in v3; older releases used different names.
- **SmartScreen/antivirus:** releases are unsigned. Verify origin/checksum;
  do not disable protection globally or restore an unverified binary.
- **Missing `api-ms-win-core-path` on Win7:** use the Win7 download and SP1.
- **Workers fail:** inspect Output, check extraction-directory permissions and
  quarantine history. Re-extract the correct release before reporting.

For packaging and isolated EXE validation, see [build instructions](../build/README.md).
