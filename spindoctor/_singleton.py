"""Single-instance lock for the GUI.

Two GUI windows on the same machine writing to the same HyperSpin XML
race each other and the loser silently overwrites the winner's work.
Cabinet owners hit this when they double-click the launcher twice
before the splash has rendered.

The lock is a stamped file in the user's config dir. Acquire takes a
``cross-process exclusive`` file handle:

- POSIX: ``fcntl.flock(LOCK_EX | LOCK_NB)``
- Windows: ``msvcrt.locking(LK_NBLCK, 1)``

Both APIs release the lock automatically when the process exits, so a
crashed first instance never poisons future launches. Tests can opt
out via ``SPINDOCTOR_DISABLE_SINGLETON=1``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


class SingletonLock:
    """RAII lock guarding a single GUI instance per machine."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fh: Optional[object] = None

    def acquire(self) -> bool:
        """Try to take the lock. Returns False if another GUI holds it."""
        if os.environ.get("SPINDOCTOR_DISABLE_SINGLETON") == "1":
            return True
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.lock_path, "a+b")
        except OSError:
            # If we can't even open the lock file, fail open — better
            # to launch with a tiny race window than to refuse to start
            # on a read-only or weirdly-permissioned config dir.
            return True

        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False

        try:
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()).encode("ascii"))
            fh.flush()
        except OSError:
            pass

        self._fh = fh
        return True

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            fh.close()
        except OSError:
            pass
        self._fh = None
        try:
            self.lock_path.unlink()
        except OSError:
            pass

    def __enter__(self) -> "SingletonLock":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def default_lock_path() -> Path:
    """Where the GUI lock file lives. Mirrors the config dir convention."""
    from . import config

    return config.CONFIG_DIR / "gui.lock"
