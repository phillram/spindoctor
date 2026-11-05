"""Persist only unfinished work when an undo operation needs to be retried."""
import json

from ._utils import atomic_write_bytes


def finish_undo(path, data, key, completed, errors):
    if errors:
        data[key] = [entry for entry in data.get(key, []) if entry["dest"] not in completed]
        try:
            atomic_write_bytes(path, json.dumps(data, indent=2).encode("utf-8"))
        except OSError as exc:
            errors.append(f"Could not save undo progress: {exc}")
    else:
        try:
            path.unlink()
        except OSError as exc:
            errors.append(f"Could not remove completed undo manifest: {exc}")
