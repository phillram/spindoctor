"""Tests for adding a brand-new named color (ledblinky colors add)."""
import pytest

from spindoctor import ledblinky as lb
from spindoctor.config import Config

SAMPLE = "; header\r\n\r\n[Colors]\r\nRed=48,0,0\r\nBlue=0,0,48\r\n"


@pytest.fixture
def led_dir(tmp_path):
    # open(newline="") disables newline translation so SAMPLE's explicit \r\n is
    # written verbatim; write_text(newline=) only exists on Python 3.10+ and the
    # CI matrix still includes 3.8 (mirrors spindoctor/ledblinky.py's writer).
    with (tmp_path / "Color-RGB.ini").open("w", encoding="utf-8", newline="") as fh:
        fh.write(SAMPLE)
    return tmp_path


@pytest.fixture
def config(led_dir):
    return Config(ledblinky_dir=str(led_dir))


def _names(led_dir):
    _, entries = lb.parse_color_rgb_ini(led_dir / "Color-RGB.ini")
    return [e.name for e in entries]


def test_add_appends_new_color(config, led_dir):
    result = lb.add_color(config, "Turquoise", 1, 36, 42, dry_run=False, backup=False)
    assert result.name == "Turquoise"
    entries = {e.name: e for e in lb.parse_color_rgb_ini(led_dir / "Color-RGB.ini")[1]}
    assert entries["Turquoise"].r == 1
    assert entries["Turquoise"].g == 36
    assert entries["Turquoise"].b == 42
    # Existing colors preserved.
    assert "Red" in entries and "Blue" in entries


def test_dry_run_writes_nothing(config, led_dir):
    before = (led_dir / "Color-RGB.ini").read_text(encoding="utf-8")
    lb.add_color(config, "Turquoise", 1, 36, 42, dry_run=True)
    assert (led_dir / "Color-RGB.ini").read_text(encoding="utf-8") == before


def test_header_and_crlf_preserved(config, led_dir):
    lb.add_color(config, "Teal", 0, 44, 36, dry_run=False, backup=False)
    raw = (led_dir / "Color-RGB.ini").read_bytes()
    assert b"; header" in raw            # comment header kept
    assert b"\r\n" in raw and b"\r\r" not in raw   # CRLF, not doubled


def test_duplicate_name_rejected_case_insensitive(config):
    with pytest.raises(ValueError, match="already exists"):
        lb.add_color(config, "red", 1, 2, 3, dry_run=True)


def test_bad_characters_rejected(config):
    for bad in ("Bad=Name", "a,b", "x;y", "[oops]"):
        with pytest.raises(ValueError, match="aren't allowed"):
            lb.add_color(config, bad, 1, 2, 3, dry_run=True)


def test_empty_or_symbol_only_name_rejected(config):
    with pytest.raises(ValueError):
        lb.add_color(config, "   ", 1, 2, 3, dry_run=True)
    with pytest.raises(ValueError, match="letter or digit"):
        lb.add_color(config, "!!!", 1, 2, 3, dry_run=True)


def test_out_of_range_rejected(config):
    with pytest.raises(ValueError, match="0-48"):
        lb.add_color(config, "TooBig", 99, 0, 0, dry_run=True)


def test_missing_file_raises(tmp_path):
    cfg = Config(ledblinky_dir=str(tmp_path))
    with pytest.raises(ValueError, match="not found"):
        lb.add_color(cfg, "X", 1, 1, 1, dry_run=True)


def test_added_color_is_usable_elsewhere(config, led_dir):
    """A freshly-added color validates in the shared palette check used by
    admin buttons / fill-defaults, proving it's usable across the tool."""
    lb.add_color(config, "Turquoise", 1, 36, 42, dry_run=False, backup=False)
    # Should not raise — the new name is now a known palette color.
    lb._validate_admin_colors(config, ["Turquoise"])
    with pytest.raises(ValueError):
        lb._validate_admin_colors(config, ["Nonexistent"])
