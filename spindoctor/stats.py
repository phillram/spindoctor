"""Coverage dashboard: aggregate audit results into a top-level summary.

Reuses ``audit_system`` so the figures here always agree with what the
``audit`` command reports for individual systems. For each system we
compute:

  * total ROMs / DB entries
  * % of ROMs that have a DB entry
  * % of DB entries with complete metadata
  * % of DB entries with all media types present
  * top missing media types
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from .audit import SystemAuditResult, audit_system
from .config import MEDIA_TYPES, Config


@dataclass
class SystemStats:
    system: str
    total_roms: int
    total_db_entries: int
    matched: int
    metadata_complete: int
    media_complete: int
    missing_media_counter: Counter = field(default_factory=Counter)

    @property
    def rom_coverage(self) -> float:
        if self.total_roms == 0:
            return 0.0
        return self.matched / self.total_roms

    @property
    def metadata_coverage(self) -> float:
        if self.total_db_entries == 0:
            return 0.0
        return self.metadata_complete / self.total_db_entries

    @property
    def media_coverage(self) -> float:
        if self.total_db_entries == 0:
            return 0.0
        return self.media_complete / self.total_db_entries


@dataclass
class StatsReport:
    per_system: list[SystemStats] = field(default_factory=list)

    @property
    def total_roms(self) -> int:
        return sum(s.total_roms for s in self.per_system)

    @property
    def total_db_entries(self) -> int:
        return sum(s.total_db_entries for s in self.per_system)

    @property
    def overall_media_missing(self) -> Counter:
        c: Counter = Counter()
        for s in self.per_system:
            c.update(s.missing_media_counter)
        return c


def _stats_from_audit(result: SystemAuditResult) -> SystemStats:
    metadata_complete = sum(
        1 for e in result.entries
        if e.in_database and not e.missing_metadata and not e.ignored
    )
    media_complete = sum(
        1 for e in result.entries
        if e.in_database and e.media.has_all() and not e.ignored
    )
    counter: Counter = Counter()
    for e in result.entries:
        if e.in_database and not e.ignored:
            for missing in e.media.missing():
                counter[missing] += 1
    return SystemStats(
        system=result.system_name,
        total_roms=result.total_roms,
        total_db_entries=result.total_db_entries,
        matched=result.roms_in_db,
        metadata_complete=metadata_complete,
        media_complete=media_complete,
        missing_media_counter=counter,
    )


def collect_stats(systems: Iterable[str], config: Config) -> StatsReport:
    """Run an audit per system and roll the results into a stats report."""
    report = StatsReport()
    for sys_name in systems:
        result = audit_system(
            sys_name, config,
            check_media_flag=True,
            fuzzy=False,
            check_mame_controls=False,
        )
        report.per_system.append(_stats_from_audit(result))
    return report


def top_missing_media(report: StatsReport, limit: int = 5) -> list[tuple[str, int]]:
    """Return the *limit* media types that are most commonly absent overall."""
    counter = report.overall_media_missing
    # Preserve MEDIA_TYPES ordering when counts tie so output is stable.
    order = {name: i for i, name in enumerate(MEDIA_TYPES)}
    return sorted(
        counter.items(),
        key=lambda kv: (-kv[1], order.get(kv[0], 99)),
    )[:limit]
