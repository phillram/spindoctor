#!/usr/bin/env python3
"""Standalone Favorites wheel manager.

Thin wrapper around spindoctor.favorites:main. Designed to be invoked
directly from Windows startup, scheduled tasks, or the HyperSpin Tools
menu — no need to load the full SpinDoctor CLI surface.

Usage examples::

    python scripts/spindoctor-fav.py rebuild
    python scripts/spindoctor-fav.py add "Super Nintendo" "Chrono Trigger"
    python scripts/spindoctor-fav.py list
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow direct invocation from a clone before `pip install -e .`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spindoctor.favorites import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
