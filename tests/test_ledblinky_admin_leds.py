"""Tests for the in-game admin LED controls (ledblinky admin-leds).

Exercises reading and rewriting the UI_CANCEL/UI_PAUSE/UI_SELECT controls in
LEDBlinkyControls.xml against the committed trimmed sample, which mirrors the
real cabinet's structure (per-group admin block + a trailing global control
definition block that must never be touched).
"""
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from spindoctor import ledblinky as lb
from spindoctor.config import Config

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "reference" / "LEDBlinkyControls.sample.xml"


@pytest.fixture
def led_dir(tmp_path):
    """A throwaway ledblinky_dir seeded with the sample XML + a small palette."""
    d = tmp_path / "led"
    d.mkdir()
    shutil.copy(SAMPLE, d / "LEDBlinkyControls.xml")
    (d / "Color-RGB.ini").write_text(
        "[Colors]\nRed=48,0,0\nYellow=48,48,0\nGreen=0,48,0\nBlue=0,0,48\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def config(led_dir):
    return Config(ledblinky_dir=str(led_dir))


def _state(config):
    return {s.friendly: s for s in lb.read_admin_led_state(config)}


def test_sample_has_three_admin_controls_lit(config):
    st = _state(config)
    assert set(st) == {"exit", "pause", "select"}
    # 3 control groups in the sample each carry the admin block.
    assert st["exit"].always_active_count == 3
    assert st["pause"].always_active_count == 3
    assert st["select"].always_active_count == 3
    assert st["exit"].colors == {"Red": 3}
    assert st["pause"].colors == {"Yellow": 3}
    assert st["select"].colors == {"Green": 3}


def test_turn_select_off_sweeps_every_group(config, led_dir):
    result = lb.set_admin_led_controls(config, {"select": "off"}, dry_run=False, backup=False)
    assert result.active_changes == 3      # one per control group
    assert result.color_changes == 0
    st = _state(config)
    assert st["select"].always_active_count == 0   # dark in-game now
    assert st["exit"].always_active_count == 3      # Exit/Pause untouched
    assert st["pause"].always_active_count == 3


def test_recolor_admin_button(config):
    result = lb.set_admin_led_controls(config, {"exit": "Blue"}, dry_run=False, backup=False)
    assert result.color_changes == 3
    st = _state(config)
    assert st["exit"].colors == {"Blue": 3}
    assert st["exit"].always_active_count == 3      # stays lit


def test_global_control_definitions_are_not_touched(config, led_dir):
    """The trailing <controlDefaults> block has bare UI_* entries with no
    alwaysActive/color — they must survive a sweep unchanged."""
    before = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    lb.set_admin_led_controls(config, {"select": "off"}, dry_run=False, backup=False)
    after = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    for text in (before, after):
        assert 'name="UI_SELECT" inputCodes="|KEYCODE_ENTER|JOYCODE_1_BUTTON1" allowConfigPlayerNum="0"' in text


def test_output_stays_valid_xml(config, led_dir):
    lb.set_admin_led_controls(config, {"select": "off", "exit": "Blue"}, dry_run=False, backup=False)
    ET.parse(led_dir / "LEDBlinkyControls.xml")  # raises if malformed


def test_dry_run_writes_nothing(config, led_dir):
    before = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    result = lb.set_admin_led_controls(config, {"select": "off"}, dry_run=True)
    assert result.active_changes == 3          # reports what it *would* do
    assert (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8") == before


def test_bad_color_rejected(config):
    with pytest.raises(ValueError, match="Unknown color"):
        lb.set_admin_led_controls(config, {"exit": "Fuchsia"}, dry_run=True)


def test_unknown_button_rejected(config):
    with pytest.raises(ValueError, match="Unknown admin button"):
        lb.set_admin_led_controls(config, {"coin": "Red"}, dry_run=True)


def test_missing_xml_raises(tmp_path):
    cfg = Config(ledblinky_dir=str(tmp_path))
    with pytest.raises(ValueError, match="not found"):
        lb.read_admin_led_state(cfg)
