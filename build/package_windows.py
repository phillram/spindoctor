"""Package independently downloadable Windows GUI and CLI executables."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package_windows(dist: Path, output: Path, platform: str) -> list[Path]:
    """Each ZIP contains exactly one standalone EXE, with no enclosing folder.

    Names carry no version (``spindoctor-gui-win10.zip``): the release page
    says which version it is, and the GUI shows it in Help → About.
    """
    if platform not in ("win7", "win10"):
        raise ValueError("platform must be win7 or win10")
    targets = (("gui", "spindoctor.exe"), ("cli", "spindoctor-cli.exe"))
    for _, executable in targets:
        if not (dist / executable).is_file():
            raise FileNotFoundError(dist / executable)
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    for edition, executable in targets:
        archive = output / f"spindoctor-{edition}-{platform}.zip"
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.write(dist / executable, arcname=executable)
        archives.append(archive)
    return archives


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--platform", choices=("win7", "win10"), required=True)
    args = parser.parse_args()
    for archive in package_windows(args.dist, args.output, args.platform):
        print(archive)


if __name__ == "__main__":
    main()
