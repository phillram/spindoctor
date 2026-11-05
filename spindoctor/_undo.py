"""Persist only unfinished work when an undo operation needs to be retried."""
import json

from ._utils import atomic_write_bytes


def checkpoint(path, data):
    """Replace a recovery record before starting the next filesystem change."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, json.dumps(data, indent=2).encode("utf-8"))


def begin_step(path, data, key, entry):
    data.setdefault(key, []).append(entry)
    data.setdefault("pending", []).append(entry["dest"])
    checkpoint(path, data)


def complete_step(path, data, entry):
    data["pending"].remove(entry["dest"])
    checkpoint(path, data)


def undo_entries(data, key, completed, errors):
    """Reconcile write-ahead intents without guessing about partial moves.

    A pending copy belongs to this operation and can be removed. A pending
    move with both paths still present may be a cross-drive partial move:
    retain it for manual investigation rather than deleting either copy.
    """
    pending = set(data.get("pending", []))
    from pathlib import Path

    for entry in data.get(key, []):
        if entry["dest"] not in pending:
            yield entry
            continue
        src, dest = Path(entry["src"]), Path(entry["dest"])
        src_exists = src.exists() or src.is_symlink()
        dest_exists = dest.exists() or dest.is_symlink()
        copying = (data.get("clone") or data.get("keep_source")
                   or entry.get("action") in ("copy", "link", "restore-backup"))
        if not dest_exists and src_exists and not entry.get("backup"):
            completed.add(entry["dest"])
        elif copying and entry.get("backup"):
            yield entry
        elif dest_exists and (copying or not src_exists or src == dest):
            yield entry
        else:
            errors.append(f"Interrupted operation requires investigation: {src} -> {dest}")


def finish_undo(path, data, key, completed, errors):
    if errors:
        data[key] = [entry for entry in data.get(key, []) if entry["dest"] not in completed]
        try:
            data["pending"] = [dest for dest in data.get("pending", []) if dest not in completed]
            checkpoint(path, data)
        except OSError as exc:
            errors.append(f"Could not save undo progress: {exc}")
    else:
        try:
            path.unlink()
        except OSError as exc:
            errors.append(f"Could not remove completed undo manifest: {exc}")
