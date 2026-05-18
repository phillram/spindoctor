#!/usr/bin/env python3
"""Block commits that introduce a second ``## [Unreleased]`` section.

CHANGELOG.md has a strict format contract: exactly one ``## [Unreleased]``
heading, at the top of the file, holding every change since the last
tagged release. During the 2.0 cycle a "Unreleased — earlier entries"
sibling section accumulated alongside the canonical one, and the release
note extractor (``build/extract_changelog.py``) silently dropped the
second block from published notes. This hook catches that pattern at
commit time so it can't ship.

A line counts as an Unreleased heading if it matches::

    ## [Unreleased
            (case-sensitive, leading "## ", literal "[Unreleased")

So "[Unreleased]", "[Unreleased — earlier entries]", "[Unreleased v2]"
all count. Tagged release headings like "## [2.0.0] - 2026-05-18" do
not. Section dividers, body text, and anything indented are ignored.

Exit code 0 if exactly one Unreleased heading is found, 1 otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
PATTERN = re.compile(r"^## \[Unreleased", re.MULTILINE)


def main() -> int:
    if not CHANGELOG.exists():
        # Not an error — a fresh clone may not have one yet, and a
        # missing file is not the failure mode this hook guards against.
        return 0
    text = CHANGELOG.read_text(encoding="utf-8")
    matches = PATTERN.findall(text)
    if len(matches) == 1:
        return 0
    if len(matches) == 0:
        print(
            "CHANGELOG.md: no '## [Unreleased]' section found. "
            "Add one above the most recent version block, or revert if "
            "you intentionally removed it.",
            file=sys.stderr,
        )
        return 1
    print(
        f"CHANGELOG.md: found {len(matches)} '## [Unreleased]' "
        "sections; expected exactly one. Merge the extra sections into "
        "the top one — the release-note extractor only reads the first "
        "match, so duplicates silently drop content from published "
        "release notes.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
