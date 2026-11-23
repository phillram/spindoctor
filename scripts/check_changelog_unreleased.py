#!/usr/bin/env python3
"""Check CHANGELOG.md's format contract.

1. Exactly one ``## [Unreleased]`` heading. During the 2.0 cycle a
   "Unreleased — earlier entries" sibling section accumulated alongside the
   canonical one, and the release note extractor
   (``build/extract_changelog.py``) silently dropped the second block from
   published notes.

   A line counts as an Unreleased heading if it starts with the literal
   ``## [Unreleased`` (case-sensitive), so "[Unreleased]",
   "[Unreleased — earlier entries]" and "[Unreleased v2]" all count.

2. No hard-wrapped paragraphs or list items. Each entry is one line. A
   release's section becomes its GitHub Release body, and release bodies
   render every newline as a line break, so a wrapped entry is published
   with ragged lines. A line continues the previous one when the previous
   line is text and this line is neither blank, a heading, a list item, a
   table row, a code fence nor a link definition. Code blocks are skipped.

Exit code 0 if both hold, 1 otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
PATTERN = re.compile(r"^## \[Unreleased", re.MULTILINE)
_BLOCK_START = re.compile(r"(#|\||```|([-*+]|\d+\.)\s|\[[^\]]+\]:\s)")


def wrapped_lines(text: str) -> list[int]:
    """1-based numbers of lines that continue the line before them."""
    found = []
    in_code = False
    previous = ""
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
        elif (not in_code and stripped and previous.strip()
              and not previous.lstrip().startswith(("#", "|", "```"))
              and not _BLOCK_START.match(stripped)):
            found.append(number)
        previous = "" if in_code else line
    return found


def main() -> int:
    if not CHANGELOG.exists():
        # Not an error — a fresh clone may not have one yet, and a
        # missing file is not the failure mode this hook guards against.
        return 0
    text = CHANGELOG.read_text(encoding="utf-8")
    failed = False
    matches = PATTERN.findall(text)
    if not matches:
        print(
            "CHANGELOG.md: no '## [Unreleased]' section found. "
            "Add one above the most recent version block, or revert if "
            "you intentionally removed it.",
            file=sys.stderr,
        )
        failed = True
    elif len(matches) > 1:
        print(
            f"CHANGELOG.md: found {len(matches)} '## [Unreleased]' "
            "sections; expected exactly one. Merge the extra sections into "
            "the top one — the release-note extractor only reads the first "
            "match, so duplicates silently drop content from published "
            "release notes.",
            file=sys.stderr,
        )
        failed = True
    wrapped = wrapped_lines(text)
    if wrapped:
        shown = ", ".join(str(n) for n in wrapped[:10]) + (" …" if len(wrapped) > 10 else "")
        print(
            f"CHANGELOG.md: {len(wrapped)} hard-wrapped line(s) (line {shown}). "
            "Join each entry onto one line: GitHub Release notes show every "
            "line break, so wrapped entries publish as ragged lines. Leave a "
            "blank line before a note that follows a nested list.",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
