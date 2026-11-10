"""Files the games create during a ``spindoctor test`` run.

Emulators write save files, configs and folders when a game runs (a MAME
``cfg\\<game>.cfg``, a RetroArch ``saves\\<game>.srm``, RocketLauncher's own
``Settings\\<System>\\<game>\\Bezel.ini``).  A test run can list them, or back
them up and remove them so the cabinet is left as it was found:

* ``report`` (the default): list them in ``cleanup.csv`` and the report.
* ``remove``: copy each new file to a backup folder, then delete it; empty
  new folders go too, deepest first.
* ``off``: don't look.

**Nothing that existed when the run started is ever touched.**  Before the
first launch every path under the watched folders is recorded as a 64-bit
hash in ``baseline.bin`` (kept on disk, so a recovery after a kill can use
it); a folder that can't be read is protected whole.  A path also needs a
creation time inside the run.  Folders the run must not look in
(``test_cleanup_skip``, by default RocketLauncher's 7-Zip ``cache`` and its
statistics, which the run restores itself) and the folders of programs
that were already running from a watched folder (DS4Windows, LEDBlinky) are
left alone.

The watched folders are ``hyperspin_dir``, plus ``rocketlauncher_dir`` and
``emulators_dir`` when they aren't inside it.  A watcher
(``ReadDirectoryChangesW``) names what appeared after each game; when it
overflows, and at the end of the run, every watched folder is listed again.
"""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
import time
from array import array
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config

MODES = ("report", "remove", "off")
CLEANUP_FIELDS = ["Time", "After", "Action", "Path", "Bytes", "Backup"]


def path_hash(path: str) -> int:
    """A stable 64-bit hash of *path* (case-insensitive on Windows)."""
    data = os.path.normcase(os.path.normpath(path)).encode("utf-8", "surrogatepass")
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "little")


def watched_roots(config: Config) -> list[str]:
    """``hyperspin_dir``, then ``rocketlauncher_dir`` and ``emulators_dir`` when
    they are set, exist and aren't already inside a watched folder."""
    roots: list[str] = []
    for value in (config.hyperspin_dir, config.rocketlauncher_dir, config.emulators_dir):
        if not value or not Path(value).is_dir():
            continue
        path = os.path.normpath(str(Path(value).resolve()))
        if not any(_under(path, r) for r in roots):
            roots = [r for r in roots if not _under(r, path)] + [path]
    return roots


def _under(path: str, folder: str) -> bool:
    p, f = os.path.normcase(path), os.path.normcase(folder).rstrip("\\/")
    return p == f or p.startswith(f + os.sep)


def skip_folders(config: Config, roots: list[str], running_images: list[str]) -> list[str]:
    """Folders the cleanup never looks in: ``test_cleanup_skip`` (relative to
    ``hyperspin_dir``, or absolute); RocketLauncher's ``Data\\Statistics``
    (the run restores it itself) and its 7-Zip extract folder (``[7z]
    7z_Extract_Path``, which RocketLauncher empties itself); and the folders
    of programs already running from a watched folder, except the watched
    folders themselves."""
    out: list[str] = []
    base = Path(config.hyperspin_dir)
    for entry in config.test_cleanup_skip:
        entry = entry.strip().strip('"')
        if entry:
            p = Path(entry)
            out.append(os.path.normpath(str(p if p.is_absolute() else base / Path(*entry.replace("\\", "/").split("/")))))
    if config.rocketlauncher_dir:
        from .rl_rom_paths import _resolve_rom_path
        from .rocketlauncher import _read_rl_ini

        rl = Path(config.rocketlauncher_dir)
        out.append(os.path.normpath(str(rl / "Data" / "Statistics")))
        extract = _read_rl_ini(rl / "Settings" / "Global RocketLauncher.ini").get(
            "7z", {}).get("7z_extract_path", "").strip().strip('"')
        folder = _resolve_rom_path(extract, rl) if extract else None
        if folder is not None:
            out.append(os.path.normpath(str(folder)))
    keep = {os.path.normcase(r) for r in roots}
    if config.rocketlauncher_dir:
        keep.add(os.path.normcase(os.path.normpath(config.rocketlauncher_dir)))
    for image in running_images:
        folder = os.path.normpath(os.path.dirname(image))
        if os.path.normcase(folder) in keep or not any(_under(folder, r) for r in roots):
            continue
        out.append(folder)
    seen, unique = set(), []
    for f in out:
        if os.path.normcase(f) not in seen:
            seen.add(os.path.normcase(f))
            unique.append(f)
    return unique


class Baseline:
    """Every path that existed under the watched folders when the run started."""

    def __init__(self, hashes: set[int], unreadable: list[str], count: int):
        self.hashes = hashes
        self.unreadable = unreadable
        self.count = count

    @classmethod
    def take(cls, roots: list[str], skip: list[str]) -> "Baseline":
        hashes: set[int] = set()
        unreadable: list[str] = []
        count = 0
        for root in roots:
            stack = [root]
            while stack:
                folder = stack.pop()
                try:
                    with os.scandir(folder) as it:
                        entries = list(it)
                except OSError:
                    unreadable.append(folder)
                    continue
                for e in entries:
                    if any(_under(e.path, s) for s in skip):
                        continue
                    hashes.add(path_hash(e.path))
                    count += 1
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                    except OSError:
                        unreadable.append(e.path)
        return cls(hashes, unreadable, count)

    def existed(self, path: str) -> bool:
        return path_hash(path) in self.hashes or any(_under(path, u) for u in self.unreadable)

    def save(self, folder: Path) -> None:
        arr = array("Q", sorted(self.hashes))
        with open(folder / "baseline.bin", "wb") as fh:
            arr.tofile(fh)
        (folder / "baseline-unreadable.txt").write_text("\n".join(self.unreadable), encoding="utf-8")

    @classmethod
    def load(cls, folder: Path) -> Optional["Baseline"]:
        path = folder / "baseline.bin"
        try:
            arr = array("Q")
            with open(path, "rb") as fh:
                arr.frombytes(fh.read())
            unreadable_file = folder / "baseline-unreadable.txt"
            text = unreadable_file.read_text(encoding="utf-8") if unreadable_file.exists() else ""
        except OSError:
            return None
        return cls(set(arr), [u for u in text.splitlines() if u], len(arr))


class Cleanup:
    """The cleanup for one run: :meth:`start` before the first launch,
    :meth:`after_game` after each, :meth:`finish` at the end.  A recovery
    after a kill only calls :meth:`finish` (no watcher: a full listing)."""

    def __init__(self, config: Config, run_dir: Path, mode: str, roots: list[str],
                 skip: list[str], since: float, watcher_factory=None):
        self.config = config
        self.run_dir = run_dir
        self.mode = mode
        self.roots = roots
        self.skip = skip
        self.since = since
        self.watcher_factory = watcher_factory
        self.watchers: list = []
        self.baseline: Optional[Baseline] = None
        self.done: set[str] = set()  # paths already reported or removed (normcased)
        self.found = self.removed = self.left = self.overflows = 0
        self.backup_root = _backup_root(config, run_dir)
        for row in _read_rows(run_dir / "cleanup.csv"):  # a resumed run's earlier rows
            if not row.get("Action", "").startswith("removed"):
                self.done.add(os.path.normcase(row.get("Path", "")))

    # -- the run's steps
    def start(self) -> None:
        if self.watcher_factory is not None:
            for root in self.roots:
                try:
                    self.watchers.append(self.watcher_factory(root))
                except OSError:
                    self.overflows += 1  # no watcher: every cleanup lists the folders
        self.baseline = Baseline.take(self.roots, self.skip)
        self.baseline.save(self.run_dir)

    def after_game(self, label: str) -> int:
        """Handle what appeared since the last call; returns how many new paths."""
        candidates: set[str] = set()
        sweep = not self.watchers
        for w in self.watchers:
            added, overflowed = w.drain()
            candidates.update(added)
            if overflowed:
                self.overflows += 1
                sweep = True
        if sweep:
            candidates.update(self._listing())
        return self._handle(candidates, label)

    def finish(self, label: str = "end of run") -> int:
        """A full listing of every watched folder; stops the watchers.

        What the watchers saw since the last game is handled too: the
        listing skips any folder ``os.walk`` cannot read, and a watcher may
        still have seen a file appear there."""
        candidates: set[str] = set()
        for w in self.watchers:
            try:
                added, _over = w.drain()
                candidates.update(added)
            except OSError:
                pass
            finally:
                try:
                    w.close()
                except OSError:
                    pass
        self.watchers = []
        if self.baseline is None:
            self.baseline = Baseline.load(self.run_dir)
            if self.baseline is None:
                return 0  # no baseline: nothing can be told apart from what existed
        candidates.update(self._listing())
        return self._handle(candidates, label)

    def summary(self) -> dict:
        """The whole run's figures, from ``cleanup.csv``, so they also count a
        resumed run's earlier part and what a recovery found."""
        rows = _read_rows(self.run_dir / "cleanup.csv")
        removed = sum(1 for r in rows if r.get("Action", "").startswith("removed"))
        left = sum(1 for r in rows if "left in place" in r.get("Action", ""))
        return {
            "mode": self.mode, "found": len(rows), "removed": removed, "left": left,
            "backup_dir": str(self.backup_root) if self.mode == "remove" else "",
            "baseline": self.baseline.count if self.baseline else 0,
            "unreadable": self.baseline.unreadable if self.baseline else [],
            "skipped": self.skip, "roots": self.roots, "overflows": self.overflows,
        }

    # -- the work
    def _listing(self):
        for root in self.roots:
            for folder, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if not any(_under(os.path.join(folder, d), s) for s in self.skip)]
                for name in dirs + files:
                    yield os.path.join(folder, name)

    def _is_new(self, path: str) -> bool:
        if not any(_under(path, r) for r in self.roots) or any(_under(path, s) for s in self.skip):
            return False
        if self.baseline is None or self.baseline.existed(path):
            return False
        try:
            created = os.stat(path).st_ctime
        except OSError:
            return False  # created and gone again
        # A creation time outside the run rules out files with broken future dates too.
        return self.since - 5 <= created <= time.time() + 60

    def _handle(self, candidates: set[str], label: str) -> int:
        # Everything inside a new folder is new too (the watcher can miss files
        # written the moment a folder appears).
        for path in list(candidates):
            if os.path.isdir(path) and self._is_new(path):
                for folder, dirs, files in os.walk(path):
                    candidates.update(os.path.join(folder, n) for n in dirs + files)
        new = sorted(p for p in candidates
                     if os.path.normcase(p) not in self.done and self._is_new(p))
        rows: list[dict] = []
        files = [p for p in new if not os.path.isdir(p)]
        dirs = sorted((p for p in new if os.path.isdir(p)), key=len, reverse=True)
        for path in files:
            size = _size(path)
            if self.mode != "remove":
                rows.append(self._row(label, "found", path, size, ""))
                continue
            backup = self._backup_path(path)
            try:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
                os.remove(path)
            except OSError as exc:
                self.left += 1
                rows.append(self._row(label, f"left in place: {exc}", path, size, ""))
                continue
            self.removed += 1
            rows.append(self._row(label, "removed", path, size, str(backup)))
        for path in dirs:
            if self.mode != "remove":
                rows.append(self._row(label, "found folder", path, "", ""))
                continue
            try:
                with os.scandir(path) as it:
                    if any(it):
                        raise OSError("not empty")
                os.rmdir(path)
            except OSError as exc:
                self.left += 1
                rows.append(self._row(label, f"folder left in place: {exc}", path, "", ""))
                continue
            self.removed += 1
            rows.append(self._row(label, "removed empty new folder", path, "", ""))
        for row in rows:
            if not row["Action"].startswith("removed"):
                # Reported once.  A removed path is gone; if a later game makes
                # it again, it is new again.
                self.done.add(os.path.normcase(row["Path"]))
        self.found += len(rows)
        _append_rows(self.run_dir / "cleanup.csv", rows)
        return len(rows)

    def _row(self, label, action, path, size, backup) -> dict:
        return {"Time": datetime.now().isoformat(sep=" ", timespec="seconds"), "After": label,
                "Action": action, "Path": path, "Bytes": size, "Backup": backup}

    def _backup_path(self, path: str) -> Path:
        root = next(r for r in self.roots if _under(path, r))
        rel = os.path.relpath(path, root)
        return self.backup_root / Path(root).name / rel


def _backup_root(config: Config, run_dir: Path) -> Path:
    """``<backup_dir>\\test-cleanup\\<run>`` when ``backup_dir`` is set, else the run folder."""
    if config.backup_dir:
        return Path(config.backup_dir) / "test-cleanup" / run_dir.name
    return run_dir / "cleanup-backup"


def _size(path: str):
    try:
        return os.path.getsize(path)
    except OSError:
        return ""


def _read_rows(path: Path) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CLEANUP_FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)
