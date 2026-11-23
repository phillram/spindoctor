"""CHANGELOG.md keeps the format the release-note extractor and GitHub Releases need."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    spec = importlib.util.spec_from_file_location(
        "check_changelog_unreleased", ROOT / "scripts" / "check_changelog_unreleased.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_changelog_passes_its_format_check():
    assert _checker().main() == 0


def test_wrapped_entries_are_found():
    text = (
        "## [1.0.0] - 2026-01-01\n"
        "\n"
        "Summary paragraph that was\n"
        "wrapped.\n"
        "\n"
        "### Added\n"
        "\n"
        "- **An entry.** That runs on\n"
        "  to a second line.\n"
        "- A whole entry.\n"
        "  - A nested item.\n"
        "  - Another nested item.\n"
        "  A note glued to the nested list.\n"
        "\n"
        "  A note after a blank line.\n"
    )
    assert _checker().wrapped_lines(text) == [4, 9, 13]


def test_lists_tables_code_and_links_are_not_wrapping():
    text = (
        "### Added\n"
        "- One.\n"
        "- Two.\n"
        "  - Nested.\n"
        "1. Numbered.\n"
        "| a | b |\n"
        "|---|---|\n"
        "```text\n"
        "spindoctor audit\n"
        "  --all\n"
        "```\n"
        "[1.0.0]: https://example.com/a\n"
        "[0.9.0]: https://example.com/b\n"
    )
    assert _checker().wrapped_lines(text) == []
