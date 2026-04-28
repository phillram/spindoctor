#!/usr/bin/env python3
"""Standalone Recently Played wheel rebuild.

Thin wrapper around spindoctor.recent:main. Reads RocketLauncher's
Statistics.ini files, keeps the most-recent N games across every
system, and regenerates the synthetic "Recently Played" HyperSpin
system. Safe to run on every boot or from a HyperSpin Tools entry.

Usage examples::

    python scripts/spindoctor-recent.py rebuild
    python scripts/spindoctor-recent.py rebuild --limit 30
    python scripts/spindoctor-recent.py list
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow direct invocation from a clone before `pip install -e .`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spindoctor.recent import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
