#!/usr/bin/env python3
"""Standalone entry point for the LEDBlinky pattern batch generator.

Thin wrapper around ``spindoctor.lwax_patterns`` so the documented
``python scripts/generate_lwax_patterns.py`` command keeps working from a
checkout without ``pip install``. The real logic — shared with the
``spindoctor ledblinky lwax batch`` CLI command and the GUI — lives in the
package module.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spindoctor.lwax_patterns import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
