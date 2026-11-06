"""Package independently downloadable Windows GUI and CLI executables."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package_windows(dist: Path, output: Path, platform: str, tag: str) -> list[Path]:
    """Each ZIP contains exactly one standalone EXE, with no enclosing folder."""
    if platform not in ("win7", "win10"):
        raise ValueError("platform must be win7 or win10")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise ValueError("tag must contain only letters, digits, dots, underscores or hyphens")
    targets = (("gui", "spindoctor.exe"), ("cli", "spindoctor-cli.exe"))
    for _, executable in targets:
        if not (dist / executable).is_file():
            raise FileNotFoundError(dist / executable)
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    for edition, executable in targets:
        archive = output / f"spindoctor-{edition}-{platform}-{tag}.zip"
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.write(dist / executable, arcname=executable)
        archives.append(archive)
    return archives


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--platform", choices=("win7", "win10"), required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    for archive in package_windows(args.dist, args.output, args.platform, args.tag):
        print(archive)


if __name__ == "__main__":
    main()
