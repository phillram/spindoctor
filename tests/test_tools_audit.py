"""Registry-driven scan for installed arcade tools."""
from __future__ import annotations

from pathlib import Path

from spindoctor.config import Config
from spindoctor.tools_audit import (
    CATEGORY_INPUT,
    CATEGORY_LIGHTGUN,
    CATEGORY_ORDER,
    CATEGORY_ROM_TOOL,
    TOOL_REGISTRY,
    ToolEntry,
    default_scan_roots,
    scan_for_tools,
)


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


def test_registry_has_lightgun_and_rom_entries():
    cats = {e.category for e in TOOL_REGISTRY}
    assert CATEGORY_ROM_TOOL in cats
    assert CATEGORY_LIGHTGUN in cats
    assert CATEGORY_INPUT in cats
    # Every entry has at least one detection signal.
    for entry in TOOL_REGISTRY:
        assert entry.executables or entry.folder_hints, entry.name


def test_category_order_covers_all_known_categories():
    cats = {e.category for e in TOOL_REGISTRY}
    assert cats.issubset(set(CATEGORY_ORDER))


def test_scan_finds_executable_match(tmp_path):
    _touch(tmp_path / "Tools" / "Tur-RemoveDupes.exe")
    _touch(tmp_path / "Tools" / "DemulShooter" / "DemulShooter.exe")

    result = scan_for_tools([tmp_path])

    names = {f.entry.name for f in result.findings}
    assert "Tur-RemoveDupes" in names
    assert "DemulShooter" in names

    demul = next(f for f in result.findings if f.entry.name == "DemulShooter")
    assert demul.matched_executables  # exe path was captured
    assert demul.entry.category == CATEGORY_LIGHTGUN


def test_scan_finds_folder_hint_without_executable(tmp_path):
    # FuzzyRename installed but binary not the expected name.
    (tmp_path / "FuzzyRename").mkdir()

    result = scan_for_tools([tmp_path])

    names = {f.entry.name for f in result.findings}
    assert "FuzzyRename 3" in names


def test_scan_dedupes_same_tool_across_paths(tmp_path):
    _touch(tmp_path / "a" / "DemulShooter.exe")
    _touch(tmp_path / "b" / "DemulShooter.exe")
    result = scan_for_tools([tmp_path])
    findings = [f for f in result.findings if f.entry.name == "DemulShooter"]
    assert len(findings) == 1
    assert len(findings[0].matched_executables) == 2


def test_scan_records_missing_roots(tmp_path):
    missing = tmp_path / "does-not-exist"
    real = tmp_path / "real"
    real.mkdir()
    result = scan_for_tools([missing, real])
    assert missing in result.missing_roots
    assert real in result.scanned_roots


def test_scan_reports_unknown_executables_only_when_requested(tmp_path):
    _touch(tmp_path / "stuff" / "totally_random_thing.exe")
    quiet = scan_for_tools([tmp_path])
    assert quiet.unknown_executables == []
    loud = scan_for_tools([tmp_path], report_unknown=True)
    assert any(u.path.name == "totally_random_thing.exe"
               for u in loud.unknown_executables)


def test_scan_respects_max_depth(tmp_path):
    deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "DemulShooter.exe"
    _touch(deep)
    shallow_only = scan_for_tools([tmp_path], max_depth=2)
    assert all(
        f.entry.name != "DemulShooter" for f in shallow_only.findings
    )
    deep_enough = scan_for_tools([tmp_path], max_depth=10)
    assert any(f.entry.name == "DemulShooter" for f in deep_enough.findings)


def test_default_scan_roots_uses_configured_paths(tmp_path):
    cfg = Config(
        roms_dir=str(tmp_path / "roms"),
        hyperspin_dir=str(tmp_path / "hs"),
        rocketlauncher_dir=str(tmp_path / "rl"),
        emulators_dir=str(tmp_path / "emu"),
    )
    roots = default_scan_roots(cfg)
    root_strs = [str(r) for r in roots]
    assert any("hs" in s and "Tools" in s for s in root_strs)
    assert any("rl" in s and "Modules" in s for s in root_strs)
    assert any(s.endswith("emu") for s in root_strs)


def test_extra_roots_are_scanned(tmp_path):
    extra = tmp_path / "custom"
    _touch(extra / "JoyToKey.exe")
    result = scan_for_tools(roots=[], extra_roots=[extra])
    assert any(f.entry.name == "JoyToKey" for f in result.findings)


def test_by_category_groups_results(tmp_path):
    _touch(tmp_path / "Tur-RemoveDupes.exe")
    _touch(tmp_path / "DemulShooter.exe")
    _touch(tmp_path / "JoyToKey.exe")
    result = scan_for_tools([tmp_path])
    grouped = result.by_category()
    assert CATEGORY_ROM_TOOL in grouped
    assert CATEGORY_LIGHTGUN in grouped
    assert CATEGORY_INPUT in grouped


def test_tool_entry_is_immutable():
    e = ToolEntry(name="X", category=CATEGORY_INPUT)
    try:
        e.name = "Y"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ToolEntry should be frozen")
