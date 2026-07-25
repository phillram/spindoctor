"""Tests for the in-game admin LED controls (ledblinky admin-leds).

Exercises reading and rewriting the UI_CANCEL/UI_PAUSE/UI_SELECT controls in
LEDBlinkyControls.xml against the committed trimmed sample, which mirrors the
real cabinet's structure (per-group admin block + a trailing global control
definition block that must never be touched).
"""
import re
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


# ── emulator scoping (uniform set) ────────────────────────────────────────────

def test_set_scoped_to_one_emulator(config, led_dir):
    """--emulator confines changes to that emulator's groups."""
    # The sample has MAME (2 groups: DEFAULT + 005) and Atari_2600 (1 group).
    result = lb.set_admin_led_controls(
        config, {"exit": "Blue"}, emulator="Atari_2600", dry_run=False, backup=False,
    )
    assert result.groups_changed == 1          # only Atari's one group
    text = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    mame = text.split('emuname="MAME"')[1].split("</emulator>")[0]
    atari = text.split('emuname="Atari_2600"')[1].split("</emulator>")[0]
    # Check the Exit admin control (UI_CANCEL) specifically, not unrelated buttons.
    assert re.search(r'name="UI_CANCEL"[^>]*color="Blue"', atari)   # Atari's Exit changed
    assert not re.search(r'name="UI_CANCEL"[^>]*color="Blue"', mame)  # MAME's Exit still Red


def test_unknown_emulator_raises(config):
    with pytest.raises(ValueError, match="not found"):
        lb.set_admin_led_controls(config, {"exit": "Blue"}, emulator="Nope", dry_run=True)


# ── randomize ─────────────────────────────────────────────────────────────────

def test_randomize_is_deterministic(config, led_dir):
    r1 = lb.randomize_admin_led_controls(config, seed=42, dry_run=False, backup=False)
    out1 = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    # Reset and run again with the same seed → identical output.
    shutil.copy(SAMPLE, led_dir / "LEDBlinkyControls.xml")
    lb.randomize_admin_led_controls(config, seed=42, dry_run=False, backup=False)
    out2 = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    assert out1 == out2
    assert r1.color_changes > 0
    ET.fromstring(out1)


def test_randomize_only_selected_buttons(config, led_dir):
    lb.randomize_admin_led_controls(config, buttons=["exit"], seed=1, dry_run=False, backup=False)
    st = _state(config)
    # Pause/Select keep their sample colors; only exit may have changed.
    assert st["pause"].colors == {"Yellow": 3}
    assert st["select"].colors == {"Green": 3}


# ── add / remove ──────────────────────────────────────────────────────────────

def test_add_inserts_controls_where_missing(config, led_dir):
    """The sample's Atari_2600 DEFAULT already has admin controls, so add a
    control group without them first, then confirm add fills it."""
    # Remove from Atari, then add back.
    lb.remove_admin_led_controls(config, emulator="Atari_2600", dry_run=False, backup=False)
    st = _state(config)
    # Atari removal drops 1 group's worth (sample MAME still has 2 lit groups).
    assert st["exit"].always_active_count == 2
    result = lb.add_admin_led_controls(config, emulator="Atari_2600", dry_run=False, backup=False)
    assert result.groups_changed == 1
    st = _state(config)
    assert st["exit"].always_active_count == 3   # back to all three groups
    ET.parse(led_dir / "LEDBlinkyControls.xml")


def test_add_is_idempotent(config):
    lb.add_admin_led_controls(config, dry_run=False, backup=False)  # sample already full
    result = lb.add_admin_led_controls(config, dry_run=False, backup=False)
    assert result.groups_changed == 0


def test_remove_then_show_reports_dark(config):
    lb.remove_admin_led_controls(config, dry_run=False, backup=False)
    st = _state(config)
    assert st["exit"].always_active_count == 0
    assert st["pause"].always_active_count == 0
    assert st["select"].always_active_count == 0


def test_add_remove_roundtrip_keeps_valid_xml(config, led_dir):
    lb.remove_admin_led_controls(config, dry_run=False, backup=False)
    lb.add_admin_led_controls(config, dry_run=False, backup=False)
    ET.parse(led_dir / "LEDBlinkyControls.xml")


def test_list_emulators(config):
    emus = lb.list_admin_led_emulators(config)
    assert "MAME" in emus and "Atari_2600" in emus


# ── randomize --games (per-game groups) ───────────────────────────────────────

def test_randomize_per_game_clones_default(config, led_dir):
    # The sample's MAME has DEFAULT + 005; ask for a game that has no group yet.
    result = lb.randomize_admin_led_controls(
        config, emulator="MAME", games=["galaga"], seed=1, dry_run=False, backup=False,
    )
    assert result.groups_added == 1
    text = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    mame = text.split('emuname="MAME"')[1].split("</emulator>")[0]
    assert '<controlGroup groupName="galaga"' in mame
    # The cloned group carries the admin controls (inherited from DEFAULT).
    galaga = re.search(r'<controlGroup groupName="galaga".*?</controlGroup>', mame, re.S).group(0)
    assert 'name="UI_CANCEL"' in galaga and 'name="UI_SELECT"' in galaga
    ET.fromstring(text)


def test_randomize_per_game_is_deterministic(config, led_dir):
    lb.randomize_admin_led_controls(config, emulator="MAME", games=["galaga", "dkong"],
                                    seed=9, dry_run=False, backup=False)
    out1 = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8")
    shutil.copy(SAMPLE, led_dir / "LEDBlinkyControls.xml")
    lb.randomize_admin_led_controls(config, emulator="MAME", games=["galaga", "dkong"],
                                    seed=9, dry_run=False, backup=False)
    assert (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8") == out1


def test_randomize_games_requires_emulator(config):
    with pytest.raises(ValueError, match="requires --emulator"):
        lb.randomize_admin_led_controls(config, games=["galaga"], dry_run=True)


def test_randomize_per_game_existing_group_not_duplicated(config, led_dir):
    # 005 already has its own group in the sample — must not be cloned again.
    result = lb.randomize_admin_led_controls(
        config, emulator="MAME", games=["005"], seed=2, dry_run=False, backup=False,
    )
    assert result.groups_added == 0
    mame = (led_dir / "LEDBlinkyControls.xml").read_text(encoding="utf-8") \
        .split('emuname="MAME"')[1].split("</emulator>")[0]
    assert mame.count('groupName="005"') == 1


# ── per-system show (read_admin_led_state emulator scope + by-emulator) ────────

def test_read_state_scoped_to_emulator(config):
    """The sample: MAME has 2 admin groups, Atari_2600 has 1."""
    mame = {s.friendly: s for s in lb.read_admin_led_state(config, emulator="MAME")}
    atari = {s.friendly: s for s in lb.read_admin_led_state(config, emulator="Atari_2600")}
    assert mame["exit"].always_active_count == 2
    assert atari["exit"].always_active_count == 1
    # Total (unscoped) is the sum.
    total = {s.friendly: s for s in lb.read_admin_led_state(config)}
    assert total["exit"].always_active_count == 3


def test_read_state_by_emulator(config):
    per = dict(lb.read_admin_led_state_by_emulator(config))
    assert set(per) == {"MAME", "Atari_2600"}
    mame = {s.friendly: s for s in per["MAME"]}
    assert mame["select"].always_active_count == 2
    assert mame["select"].colors == {"Green": 2}


def test_by_emulator_flags_console_with_no_admin_controls(config, led_dir):
    """A console whose groups have no admin controls shows all-zero counts —
    the signal that its games can't light admin buttons until 'add' is run."""
    lb.remove_admin_led_controls(config, emulator="Atari_2600", dry_run=False, backup=False)
    per = dict(lb.read_admin_led_state_by_emulator(config))
    atari = {s.friendly: s for s in per["Atari_2600"]}
    assert all(s.always_active_count == 0 for s in atari.values())
    # MAME still lit.
    mame = {s.friendly: s for s in per["MAME"]}
    assert mame["exit"].always_active_count == 2
