"""Where ``spindoctor test`` keeps its runs, and whether one is unfinished.

Kept to the standard library so the standalone ``spindoctor-recent`` and
``spindoctor-stats`` builds (no click, rich or Pillow) can check it too:
while a test run is going on, or after one was killed before it could put
RocketLauncher's play statistics back, those statistics hold test launches,
and a Recently Played / Most Played rebuild would copy them into the wheel.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import config as _config
from ._utils import atomic_write_bytes


class ActiveRunError(RuntimeError):
    """A game test run is in progress, or was interrupted and not recovered."""


def tests_dir(cfg=None) -> Path:
    """The folder that holds one sub-folder per test run."""
    custom = getattr(cfg, "test_results_dir", "") if cfg is not None else ""
    return Path(custom) if custom else _config.CONFIG_DIR / "tests"


def active_file() -> Path:
    """The pointer to the unfinished run.  Always under ``~/.spindoctor`` so
    it is found whatever ``test_results_dir`` says."""
    return _config.CONFIG_DIR / "tests" / "active.json"


def active_run() -> Optional[dict]:
    """``{"run_dir": …, "worker": {"pid": …, "started": …}}`` of the unfinished
    run, or None.  An unreadable pointer still counts as a run."""
    path = active_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"run_dir": "", "worker": {}}
    return data if isinstance(data, dict) else {"run_dir": "", "worker": {}}


def set_active(run_dir: Path, worker: dict) -> None:
    path = active_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"run_dir": str(run_dir), "worker": worker}
    atomic_write_bytes(path, json.dumps(data, indent=2).encode("utf-8"))


def clear_active() -> None:
    try:
        active_file().unlink()
    except FileNotFoundError:
        pass


def refuse_during_test_run(what: str) -> None:
    """Raise :class:`ActiveRunError` when a test run hasn't finished."""
    run = active_run()
    if run is None:
        return
    where = f" ({run['run_dir']})" if run.get("run_dir") else ""
    raise ActiveRunError(
        f"Can't {what}: a game test run{where} is in progress or was interrupted, "
        "so RocketLauncher's play statistics may still hold test launches. "
        "If no test is running, run `spindoctor test --recover` first."
    )
