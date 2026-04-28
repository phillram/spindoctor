#!/usr/bin/env python3
"""Standalone playtime / Most Played wheel helper.

Thin wrapper around spindoctor.playtime:main. Reads RocketLauncher's
Statistics.ini files, prints summary / top / recent / per-system
reports, and (with ``build-wheel --apply``) regenerates the synthetic
"Most Played" HyperSpin wheel. Designed to be invoked directly from
HyperSpin's Tools menu without loading the full SpinDoctor CLI.

Usage examples::

    python scripts/spindoctor-stats.py summary
    python scripts/spindoctor-stats.py top --top 25
    python scripts/spindoctor-stats.py system MAME
    python scripts/spindoctor-stats.py build-wheel --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow direct invocation from a clone before `pip install -e .`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spindoctor.playtime import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
