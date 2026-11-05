"""Shared JSON-cache primitive.

SpinDoctor keeps several per-system decision caches (metadata picks,
media picks, PC title picks) under ``~/.spindoctor/<name>/<system>.json``.
The load/save/clear pattern is identical for each; this module is the
single implementation that the other modules delegate to.

A single sentinel string is reserved across all caches to record a
deliberate "skip" decision so re-runs don't keep re-prompting.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from ._utils import atomic_write_bytes


SKIP_SENTINEL = "__skip__"


def _path(cache_dir: Path, system_name: str) -> Path:
    return cache_dir / f"{system_name}.json"


def _load_path(path: Path) -> Optional[dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            return data
    except (ValueError, OSError):
        pass
    return None


def load(cache_dir: Path, system_name: str) -> dict[str, str]:
    """Read a system's cache. Missing or corrupt files yield an empty dict."""
    return _load_path(_path(cache_dir, system_name)) or {}


def save(cache_dir: Path, system_name: str, data: dict[str, str]) -> None:
    """Write a system's cache, creating the directory if needed."""
    p = _path(cache_dir, system_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(p, json.dumps(data, indent=2, sort_keys=True).encode("utf-8"))


def clear(cache_dir: Path, system_name: Optional[str] = None) -> int:
    """Remove cache file(s). Returns count deleted."""
    removed = 0
    if system_name:
        p = _path(cache_dir, system_name)
        if p.exists():
            p.unlink()
            removed = 1
    elif cache_dir.exists():
        for p in cache_dir.glob("*.json"):
            p.unlink()
            removed += 1
    return removed


def list_all(cache_dir: Path, system_name: Optional[str] = None) -> dict[str, dict[str, str]]:
    """Return ``{system_name: cache_dict}`` for one or every system."""
    result: dict[str, dict[str, str]] = {}
    if not cache_dir.exists():
        return result
    paths = [_path(cache_dir, system_name)] if system_name else list(cache_dir.glob("*.json"))
    for p in paths:
        data = _load_path(p)
        if data is not None:
            result[p.stem] = data
    return result
