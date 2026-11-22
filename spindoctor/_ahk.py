"""Shared AutoHotkey line filtering, retaining source line numbers."""
from __future__ import annotations

import re
from typing import Iterator


_COMMENT_RE = re.compile(r"(?:^|[ \t]);")


def iter_ahk_code_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield numbered code lines, skipping comments and block comments."""
    in_block = False
    for number, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if in_block:
            in_block = not (s.startswith("*/") or s.endswith("*/"))
            continue
        if s.startswith("/*"):
            in_block = not (len(s) >= 4 and s.endswith("*/"))
            continue
        code = _COMMENT_RE.split(line, maxsplit=1)[0]
        if code.strip():
            yield number, code
