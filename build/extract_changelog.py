"""Extract the section of CHANGELOG.md matching a given version.

Used by .github/workflows/release.yml to populate the GitHub Release body
from a curated source instead of generic auto-generated PR titles.

Usage:
    python build/extract_changelog.py v1.0.0 > release-notes.md

The leading 'v' is stripped before matching the heading. The section is
the body between `## [1.0.0] - DATE` and the next `## [...]` heading,
excluding the heading itself. Exits non-zero if the section isn't found
so the release workflow fails loudly rather than publishing an empty body.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def extract(changelog: str, version: str) -> str:
    version = version.lstrip("v")
    # Match `## [1.0.0]` (with or without trailing date / annotation).
    start = re.search(rf"^## \[{re.escape(version)}\][^\n]*$", changelog, re.MULTILINE)
    if not start:
        raise SystemExit(f"No section for version {version!r} found in CHANGELOG.md")
    body_start = start.end()
    # Stop at the next top-level version heading or the link references at EOF.
    next_heading = re.search(r"^## \[", changelog[body_start:], re.MULTILINE)
    body_end = body_start + (next_heading.start() if next_heading else len(changelog))
    return changelog[body_start:body_end].strip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: extract_changelog.py <version>", file=sys.stderr)
        return 2
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    sys.stdout.write(extract(changelog, argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
