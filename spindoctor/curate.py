"""Region/version curation — pick the best ROM per game and retire the rest.

Where ``find-dupes`` only reports collisions, ``curate`` actively chooses a
preferred variant per normalized title and groups the losers as candidates for
archiving or deletion.

Selection rules (priority order):

  1. Exclude prototypes/demos/betas (unless ``prefer_no_proto=False``).
  2. Pick the highest-priority region — the first region in *preferences*
     that any candidate matches. ``"World"`` and untagged ROMs are treated
     as wildcards when scoring against the preferences list.
  3. Within the preferred region, prefer the highest revision label
     (``"Rev 2"`` > ``"Rev 1"`` > no revision). Pass ``prefer_revision_latest=False``
     to invert this.
  4. Tiebreak by lexicographic filename for determinism.

Apply / undo mirrors :mod:`spindoctor.misplaced` and :mod:`spindoctor.migrate`:
each ``apply_curation`` writes a JSON manifest under
``~/.spindoctor/curation/`` so the action can be reversed in one command.
"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .audit import scan_roms
from .config import CONFIG_DIR, Config
from .romutils import normalize, parse_variant


CURATION_DIR = CONFIG_DIR / "curation"
MANIFEST_PREFIX = "curate-"
RETIRED_SUBFOLDER = "_retired"

DEFAULT_REGION_PREFERENCES: list[str] = ["USA", "World", "Europe", "Japan"]

# Tags from parse_variant that mark a non-final / non-canonical release.
_PROTO_HINTS = {
    "proto", "prototype", "demo", "sample", "promo", "beta", "alpha",
}


# ─── data classes ─────────────────────────────────────────────────────────────


@dataclass
class CurationGroup:
    """One normalized title with multiple variants — keep one, retire the rest."""
    title: str
    keep: Path
    retire: list[Path] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def has_retirements(self) -> bool:
        return bool(self.retire)


# ─── selection scoring ────────────────────────────────────────────────────────


def _is_prototype(info: dict) -> bool:
    """Return True if any region/tag/patch field marks this ROM as proto-class."""
    # is_patched is set for translations/hacks too, not just protos — rely
    # solely on the explicit tag list below.
    haystacks: list[str] = []
    haystacks.extend(info.get("regions") or [])
    haystacks.extend(info.get("tags") or [])
    haystacks.append(info.get("base", "") or "")
    blob = " ".join(haystacks).lower()
    return any(token in blob for token in _PROTO_HINTS)


def _region_rank(regions: list[str], preferences: list[str]) -> int:
    """Lowest index in *preferences* that any region matches.

    Returns ``len(preferences)`` when nothing matches — i.e. last place.
    Comparison is case-insensitive and matches whole region tokens.
    """
    if not regions:
        # Untagged: treat as last-resort, but ahead of "no match" so a ROM
        # with explicit foreign region tags doesn't beat an untagged one
        # when the user's preferences are exhausted.
        return len(preferences)
    lowered = {r.strip().lower() for r in regions}
    for i, pref in enumerate(preferences):
        if pref.strip().lower() in lowered:
            return i
    return len(preferences) + 1


def _revision_rank(revision: Optional[str]) -> tuple[int, str]:
    """Sortable key for revision strings — higher = newer.

    ``"Rev 2"`` > ``"Rev 1"`` > ``"Rev A"`` > no revision. Numeric revisions
    sort numerically; alpha revisions fall back to lexicographic order.
    """
    if not revision:
        return (-1, "")
    rev = revision.strip()
    # Numeric revision like "2" or "1.1"
    head = rev.split()[0] if rev else rev
    try:
        return (int(float(head)), rev.lower())
    except ValueError:
        # Letter revision: A < B < C ...
        return (0, rev.lower())


def _score(info: dict, preferences: list[str], prefer_revision_latest: bool) -> tuple:
    """Lower score wins. Composite of region rank, revision rank, filename."""
    region = _region_rank(info.get("regions") or [], preferences)
    rev_rank = _revision_rank(info.get("revision"))
    # Invert revision rank when caller wants oldest first.
    if prefer_revision_latest:
        rev_key = (-rev_rank[0], rev_rank[1])
    else:
        rev_key = (rev_rank[0], rev_rank[1])
    return (region, rev_key, (info.get("base") or "").lower())


def _explain(info: dict, preferences: list[str]) -> str:
    """One-line human-readable reason describing why this ROM placed where it did."""
    regions = info.get("regions") or []
    rev = info.get("revision")
    parts: list[str] = []
    if regions:
        parts.append(f"region={','.join(regions)}")
    else:
        parts.append("region=untagged")
    if rev:
        parts.append(f"rev={rev}")
    rank = _region_rank(regions, preferences)
    if rank < len(preferences):
        parts.append(f"matches '{preferences[rank]}'")
    return "; ".join(parts)


# ─── curation ─────────────────────────────────────────────────────────────────


def curate_system(
    system_name: str,
    config: Config,
    preferences: Optional[list[str]] = None,
    prefer_revision_latest: bool = True,
    prefer_no_proto: bool = True,
) -> list[CurationGroup]:
    """Return curation groups for *system_name*.

    Each returned :class:`CurationGroup` represents one normalized title with
    at least two variants — single-variant titles are dropped (nothing to
    retire). The ``keep`` field is the chosen ROM; ``retire`` lists every
    other variant; ``reasons`` maps each filename to a short explanation.
    """
    prefs = preferences if preferences is not None else list(DEFAULT_REGION_PREFERENCES)
    roms = scan_roms(system_name, Path(config.roms_dir))
    if not roms:
        return []

    # Bucket ROM paths by normalized title, alongside parsed variant info.
    groups: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    for info in roms.values():
        parsed = parse_variant(info.path.stem)
        title = normalize(info.path.stem)
        if not title:
            continue
        groups[title].append((info.path, parsed))

    out: list[CurationGroup] = []
    for title, members in groups.items():
        if len(members) < 2:
            continue

        # Filter prototypes if requested. If filtering wipes everything we
        # fall back to the unfiltered list so the user still gets a choice.
        if prefer_no_proto:
            non_proto = [(p, v) for (p, v) in members if not _is_prototype(v)]
            if non_proto:
                pool = non_proto
            else:
                pool = members
        else:
            pool = members

        # Pick winner
        ranked = sorted(
            pool,
            key=lambda pv: _score(pv[1], prefs, prefer_revision_latest),
        )
        keep_path, keep_info = ranked[0]
        retire = [p for (p, _v) in members if p != keep_path]

        reasons: dict[str, str] = {
            keep_path.name: f"keep — {_explain(keep_info, prefs)}",
        }
        for path, info in members:
            if path == keep_path:
                continue
            note = _explain(info, prefs)
            if prefer_no_proto and _is_prototype(info):
                note = f"prototype/demo/beta; {note}"
            reasons[path.name] = f"retire — {note}"

        out.append(CurationGroup(
            title=title,
            keep=keep_path,
            retire=sorted(retire, key=lambda p: p.name.lower()),
            reasons=reasons,
        ))

    out.sort(key=lambda g: g.title)
    return out


# ─── apply / undo ─────────────────────────────────────────────────────────────


@dataclass
class CurationResult:
    archived: list[tuple[Path, Path]] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def apply_curation(
    groups: Iterable[CurationGroup],
    config: Config,
    system_name: str,
    action: str = "archive",
    manifest_dir: Optional[Path] = None,
) -> tuple[CurationResult, Optional[Path]]:
    """Execute the retire actions for *groups*.

    ``action`` is ``"archive"`` (move to ``<roms_dir>/<system>/_retired/``) or
    ``"delete"`` (unlink permanently — no undo possible). Returns a
    :class:`CurationResult` and the manifest path (None if nothing was applied
    or action is delete).
    """
    if action not in ("archive", "delete"):
        raise ValueError(f"action must be 'archive' or 'delete', got: {action!r}")

    result = CurationResult()
    entries: list[dict] = []
    roms_root = Path(config.roms_dir)
    retired_dir = roms_root / system_name / RETIRED_SUBFOLDER

    def _write_partial_manifest() -> Optional[Path]:
        if not entries:
            return None
        out_dir = manifest_dir or CURATION_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"{MANIFEST_PREFIX}{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "timestamp": stamp,
                    "system": system_name,
                    "action": action,
                    "moves": entries,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    try:
        for group in groups:
            for path in group.retire:
                if not path.exists():
                    result.skipped.append((path, "source missing"))
                    continue
                if action == "delete":
                    try:
                        path.unlink()
                        result.deleted.append(path)
                    except OSError as e:
                        result.skipped.append((path, f"delete failed: {e}"))
                    continue

                # archive
                dest = retired_dir / path.name
                if dest.exists():
                    result.skipped.append((path, f"target exists: {dest}"))
                    continue
                try:
                    retired_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), str(dest))
                except OSError as e:
                    result.skipped.append((path, f"move failed: {e}"))
                    continue
                result.archived.append((path, dest))
                entries.append({
                    "src": str(path),
                    "dest": str(dest),
                    "title": group.title,
                    "kept": str(group.keep),
                })
    except KeyboardInterrupt:
        # Persist whatever we've already archived so `curate --undo`
        # can roll them back. Without this, a Ctrl+C mid-archive
        # leaves files stranded in _retired with no manifest record.
        try:
            _write_partial_manifest()
        except OSError as exc:
            import sys
            print(
                f"WARNING: curation interrupted and undo manifest could not be "
                f"written ({exc}). Files already moved to _retired cannot be "
                "reversed with `curate --undo`.",
                file=sys.stderr,
            )
        raise

    manifest_path = _write_partial_manifest()
    if manifest_path is None:
        return result, None
    return result, manifest_path


def undo_curation(manifest_path: Path) -> dict:
    """Reverse the archive moves recorded in *manifest_path*.

    Delete-action manifests are not produced by :func:`apply_curation`, so
    the only thing this needs to handle is the archive case.
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary: dict = {"reverted": 0, "errors": []}
    for entry in reversed(data.get("moves", [])):
        src = Path(entry["src"])
        dest = Path(entry["dest"])
        try:
            if not dest.exists():
                summary["errors"].append(f"missing during undo: {dest}")
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(src))
            summary["reverted"] += 1
        except OSError as e:
            summary["errors"].append(f"could not revert {dest} -> {src}: {e}")

    # If the _retired folder is now empty, clean it up.
    if data.get("moves"):
        try:
            retired_parent = Path(data["moves"][0]["dest"]).parent
            if retired_parent.exists() and not any(retired_parent.iterdir()):
                retired_parent.rmdir()
        except OSError:
            pass

    try:
        manifest_path.unlink()
    except OSError:
        pass
    return summary


# ─── manifest helpers ─────────────────────────────────────────────────────────


def list_manifests() -> list[Path]:
    """Return curation manifests sorted oldest -> newest."""
    if not CURATION_DIR.exists():
        return []
    return sorted(CURATION_DIR.glob(f"{MANIFEST_PREFIX}*.json"))


def find_latest_manifest() -> Optional[Path]:
    manifests = list_manifests()
    return manifests[-1] if manifests else None


def parse_regions(value: str) -> list[str]:
    """Split a comma-separated region string into a clean preference list."""
    return [r.strip() for r in value.split(",") if r.strip()]


def manifest_summary(path: Path) -> dict:
    """Best-effort metadata read for a manifest — used by --list-manifests."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"timestamp": "", "system": "", "action": "", "count": 0}
    return {
        "timestamp": data.get("timestamp", ""),
        "system": data.get("system", ""),
        "action": data.get("action", ""),
        "count": len(data.get("moves", [])),
    }
