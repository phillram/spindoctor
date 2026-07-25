"""Tests for blanking keycode-driven admin buttons (Search / mouse).

These aren't their own LED control — their send-key rides on another
always-active control's inputCodes (e.g. Search's "/" on UI_PAUSE), so "off"
strips just that keycode token, leaving the other buttons (Pause) lit.
"""
import re
import xml.etree.ElementTree as ET

import pytest

from spindoctor import ledblinky as lb
from spindoctor.config import Config

# Reproduces the real GameCube quirk: UI_PAUSE carries Search's "/" and Pause's
# "P"; a game button carries a mouse code with alwaysActive="0" (must be left
# alone — mouse is dark in-game).
FIXTURE = """<?xml version="1.0"?>
<dat>
  <emulator emuname="Nintendo_GameCube" emuDesc="">
    <controlGroup groupName="DEFAULT" numPlayers="2" defaultInactive="0,0,0,0">
      <player number="0">
        <control name="UI_CANCEL" alwaysActive="1" color="Plum" inputCodes="KEYCODE_ESC" />
        <control name="UI_PAUSE" alwaysActive="1" color="Amber" inputCodes="KEYCODE_SLASH|KEYCODE_P" />
        <control name="UI_SELECT" alwaysActive="0" color="Green" inputCodes="KEYCODE_ENTER" />
      </player>
      <player number="1">
        <control name="P1_BUTTON1" alwaysActive="0" color="White" inputCodes="KEYCODE_A|MOUSECODE_1_BUTTON1" />
      </player>
    </controlGroup>
  </emulator>
</dat>
"""


@pytest.fixture
def led_dir(tmp_path):
    # open(newline="") disables newline translation so FIXTURE is written verbatim;
    # write_text(newline=) only exists on Python 3.10+ and the CI matrix still
    # includes 3.8 (mirrors spindoctor/ledblinky.py's writer).
    with (tmp_path / "LEDBlinkyControls.xml").open("w", encoding="utf-8", newline="") as fh:
        fh.write(FIXTURE)
    return tmp_path


@pytest.fixture
def config(led_dir):
    return Config(ledblinky_dir=str(led_dir))


def _pause_ic(led_dir):
    text = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    return re.search(r'<control name="UI_PAUSE"[^>]*inputCodes="([^"]*)"', text).group(1)


def test_search_off_strips_only_the_slash_key(config, led_dir):
    result = lb.set_admin_led_controls(config, off_buttons=["search"], dry_run=False, backup=False)
    assert result.keycode_changes == 1
    assert result.already_dark == []
    # Search's key gone, Pause's key kept → Pause still lit.
    assert _pause_ic(led_dir) == "KEYCODE_P"
    text = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    assert 'name="UI_PAUSE" alwaysActive="1"' in text   # Pause stays always-active
    ET.fromstring(text)


def test_search_off_is_idempotent(config):
    lb.set_admin_led_controls(config, off_buttons=["search"], dry_run=False, backup=False)
    again = lb.set_admin_led_controls(config, off_buttons=["search"], dry_run=False, backup=False)
    assert again.keycode_changes == 0


def test_mouse_off_reports_already_dark(config, led_dir):
    """Mouse code sits on an alwaysActive='0' game control, so it's not lit
    in-game — off finds nothing to strip and reports it."""
    before = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    result = lb.set_admin_led_controls(config, off_buttons=["lmouse", "rmouse"],
                                       dry_run=False, backup=False)
    assert result.keycode_changes == 0
    assert set(result.already_dark) == {"lmouse", "rmouse"}
    # The game button's mouse code is untouched (only always-active controls change).
    assert (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8") == before


def test_search_off_does_not_touch_game_controls(config, led_dir):
    lb.set_admin_led_controls(config, off_buttons=["search"], dry_run=False, backup=False)
    text = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    # P1_BUTTON1 (a game control) keeps both its codes.
    assert 'name="P1_BUTTON1" alwaysActive="0" color="White" inputCodes="KEYCODE_A|MOUSECODE_1_BUTTON1"' in text


def test_combined_select_off_plus_search_off(config, led_dir):
    result = lb.set_admin_led_controls(config, updates={"select": "off"},
                                       off_buttons=["search"], dry_run=False, backup=False)
    assert result.keycode_changes == 1
    text = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    assert 'name="UI_SELECT" alwaysActive="0"' in text
    assert _pause_ic(led_dir) == "KEYCODE_P"


def test_dry_run_writes_nothing(config, led_dir):
    before = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    result = lb.set_admin_led_controls(config, off_buttons=["search"], dry_run=True)
    assert result.keycode_changes == 1     # reports what it would do
    assert (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8") == before


def test_unknown_off_button_rejected(config):
    with pytest.raises(ValueError, match="Unknown button"):
        lb.set_admin_led_controls(config, off_buttons=["banana"], dry_run=True)


def test_no_updates_and_no_off_raises(config):
    with pytest.raises(ValueError, match="No admin LED updates"):
        lb.set_admin_led_controls(config, dry_run=True)


def test_search_off_then_on_restores(config, led_dir):
    lb.set_admin_led_controls(config, off_buttons=["search"], dry_run=False, backup=False)
    assert _pause_ic(led_dir) == "KEYCODE_P"                 # search removed
    r = lb.set_admin_led_controls(config, on_buttons=["search"], dry_run=False, backup=False)
    assert r.keycode_changes == 1 and r.no_host == []
    assert set(_pause_ic(led_dir).split("|")) == {"KEYCODE_P", "KEYCODE_SLASH"}  # back on Pause
    ET.fromstring((led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8"))


def test_search_on_is_idempotent(config):
    # Fixture already has Search on Pause → turning it on again changes nothing.
    r = lb.set_admin_led_controls(config, on_buttons=["search"], dry_run=False, backup=False)
    assert r.keycode_changes == 0


def test_cant_turn_same_button_on_and_off(config):
    with pytest.raises(ValueError, match="both on and off"):
        lb.set_admin_led_controls(config, off_buttons=["search"], on_buttons=["search"],
                                  dry_run=True)


def test_on_with_no_host_reports_no_host(tmp_path):
    # A group with no UI_PAUSE control → nowhere to attach the key.
    # open(newline="") is used instead of write_text(newline=), which is 3.10+ only.
    with (tmp_path / "LEDBlinkyControls.xml").open("w", encoding="utf-8", newline="") as fh:
        fh.write(
            '<?xml version="1.0"?>\n<dat>\n'
            '  <emulator emuname="X">\n'
            '    <controlGroup groupName="DEFAULT">\n'
            '      <player number="0">\n'
            '        <control name="UI_CANCEL" alwaysActive="1" color="Red" inputCodes="KEYCODE_ESC" />\n'
            '      </player>\n'
            '    </controlGroup>\n'
            '  </emulator>\n</dat>\n'
        )
    cfg = Config(ledblinky_dir=str(tmp_path))
    r = lb.set_admin_led_controls(cfg, on_buttons=["search"], dry_run=False, backup=False)
    assert r.keycode_changes == 0
    assert r.no_host == ["search"]


def test_emulator_scope_on_off(config):
    # Wrong emulator name → error (scoping guard).
    with pytest.raises(ValueError, match="not found"):
        lb.set_admin_led_controls(config, off_buttons=["search"], emulator="Nope", dry_run=True)
