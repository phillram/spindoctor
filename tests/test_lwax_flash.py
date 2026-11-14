"""Tests for the .lwax flash scorer (spindoctor.lwax_flash) and `ledblinky lwax flash-check`.

The scorer is checked against the example cabinet's own report in
tests/test_lwax_patterns.py; these tests pin its parts on small,
hand-sized animations.
"""
from __future__ import annotations

import textwrap

import pytest
from click import unstyle
from click.testing import CliRunner

from spindoctor import lwax_flash
from spindoctor.cli import cli
from spindoctor.config import Config, save_config
from spindoctor.lwax import build_alternate, build_color_cycle, build_fill, parse_input_map
from spindoctor.lwax_flash import (
    decode_lwax,
    score_animation,
    score_lwax,
    score_xml,
)

# Two RGB buttons and one single-colour coin light, as in test_lwax.py.
INPUT_MAP = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <dat>
      <ledController type="3" id="1" name="PACLED64">
        <port number="1" label="P1B1" type="R"/>
        <port number="2" label="P1B1" type="G"/>
        <port number="3" label="P1B1" type="B"/>
        <port number="4" label="" type=""/>
      </ledController>
      <ledController type="3" id="2" name="PACLED64">
        <port number="1" label="P1B2" type="R"/>
        <port number="2" label="P1B2" type="G"/>
        <port number="3" label="P1B2" type="B"/>
        <port number="4" label="COIN" type=""/>
      </ledController>
    </dat>
    """)


@pytest.fixture
def controllers(tmp_path):
    path = tmp_path / "LEDBlinkyInputMap.xml"
    path.write_text(INPUT_MAP, encoding="utf-8")
    return parse_input_map(path)


def _strobe(controllers, on=2, off=2, ms=30, cycles=10):
    from spindoctor.lwax import LwaxAnimation

    anim = LwaxAnimation(controllers)
    lit = {label: (48, 48, 48) for label in anim.labels}
    dark = {label: (0, 0, 0) for label in anim.labels}
    for _ in range(cycles):
        for _ in range(on):
            anim.add_frame(ms, lit)
        for _ in range(off):
            anim.add_frame(ms, dark)
    return anim


def test_whole_panel_strobe_is_strobe(controllers):
    score = score_animation(_strobe(controllers))
    # One flash per 4 x 30 ms = 8.33 a second, every button snapping each time.
    assert score.panel_flash_hz == 8.33
    assert score.sync_blink_hz == 16.67
    assert score.tier == "strobe"
    assert score.tier_title == "Strobe"


def test_lockstep_swap_with_steady_brightness_is_blink(controllers):
    # The two RGB buttons swap red and blue 10 times a second: the panel's
    # brightness never changes, but 2 of the 3 controls hard-cut together.
    # (Not COIN: it's single-colour, so "blue" would turn it off.)
    anim = build_alternate(controllers, ["P1B1"], ["P1B2"], (48, 0, 0), (0, 0, 48),
                           hold_ms=100, cycles=5)
    score = score_animation(anim)
    assert score.panel_flash_hz == 0
    assert score.sync_blink_hz == 10
    assert score.tier == "blink"


def test_slow_fade_is_smooth(controllers):
    anim = build_color_cycle(controllers, [(0, 0, 0), (48, 0, 0)], steps_per_leg=48, duration_ms=40)
    score = score_animation(anim)
    assert score.snaps_per_led_hz == 0
    assert score.panel_flash_hz == pytest.approx(0.26, abs=0.01)  # one breath per 3.84 s
    assert score.tier == "smooth"


def test_fill_flash_versus_fade_reset(controllers):
    groups = [["P1B1"], ["P1B2"], ["COIN"]]
    flashing = build_fill(controllers, groups, (0, 48, 48), frames_per_step=2, duration_ms=30)
    soft = build_fill(controllers, groups, (0, 48, 48), frames_per_step=2, duration_ms=30,
                      fade_reset_frames=20, fade_reset_dark_frames=6)
    assert score_animation(flashing).tier != "smooth"
    soft_score = score_animation(soft)
    assert soft_score.tier == "smooth"
    assert soft_score.sync_blink_hz == 0


def test_loop_seam_counts(controllers):
    # Lit for 9 frames, dark for 1: the only swings are around the wrap.
    from spindoctor.lwax import LwaxAnimation

    anim = LwaxAnimation(controllers)
    for i in range(10):
        anim.add_frame(100, {label: (0, 0, 0) if i == 9 else (48, 0, 0) for label in anim.labels})
    score = score_animation(anim)
    assert score.panel_flash_hz == 1      # one flash in the 1 s loop
    assert score.sync_blink_hz == 2       # off at frame 9, back on at the wrap


def test_single_colour_port_lights_every_channel(controllers):
    from spindoctor.lwax import LwaxAnimation

    anim = LwaxAnimation(controllers)
    anim.add_frame(40, {"COIN": (30, 0, 0)})
    durations, colors = decode_lwax(anim.render(), controllers)
    assert durations == [40]
    labels = sorted({"P1B1", "P1B2", "COIN"})
    assert colors[0][labels.index("COIN")] == (30, 30, 30)


def test_values_carry_forward_between_frames(controllers):
    xml = textwrap.dedent("""\
        <LEDAnimation>
          <Frame Number="1" Duration="50">
            <Intensity LedHwType="3" Id="1" Value="48,0,0,0"/>
          </Frame>
          <Frame Number="2" Duration="50">
          </Frame>
        </LEDAnimation>
        """)
    _durations, colors = decode_lwax(xml, controllers)
    p1b1 = sorted({"P1B1", "P1B2", "COIN"}).index("P1B1")
    assert colors[0][p1b1] == colors[1][p1b1] == (48, 0, 0)


def test_rounds_like_dotnet():
    assert lwax_flash._net_round(2.5, 0) == 2.0
    assert lwax_flash._net_round(0.125, 2) == 0.12
    assert lwax_flash._net_round(2.777, 2) == 2.78


def test_score_lwax_reads_files_and_rejects_junk(controllers, tmp_path):
    good = tmp_path / "strobe.lwax"
    with good.open("w", encoding="utf-8", newline="") as fh:
        fh.write(_strobe(controllers).render())
    assert score_lwax(good, controllers).tier == "strobe"
    assert score_xml(good.read_text(encoding="utf-8"), controllers).tier == "strobe"
    junk = tmp_path / "junk.lwax"
    junk.write_text("not xml", encoding="utf-8")
    with pytest.raises(ValueError):
        score_lwax(junk, controllers)
    empty = tmp_path / "empty.lwax"
    empty.write_text("<LEDAnimation></LEDAnimation>", encoding="utf-8")
    with pytest.raises(ValueError, match="No <Frame>"):
        score_lwax(empty, controllers)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_flash_check_sorts_worst_first(home, tmp_path):
    save_config(Config())
    from spindoctor import lwax_patterns
    from spindoctor.lwax_cute import build_cute, find_theme
    from spindoctor.lwax_patterns import build_strobe

    ref = parse_input_map(lwax_patterns.reference_input_map())
    folder = tmp_path / "anims"
    folder.mkdir()
    for name, anim in (("calm.lwax", build_cute(ref, find_theme("cute_koi_pond"))),
                       ("zap.lwax", build_strobe(ref, (48, 0, 0)))):
        with (folder / name).open("w", encoding="utf-8", newline="") as fh:
            fh.write(anim.render())
    (folder / "broken.lwax").write_text("nope", encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")

    result = CliRunner().invoke(cli, ["ledblinky", "lwax", "flash-check", str(folder)])
    assert result.exit_code == 0, result.output
    assert result.output.index("zap.lwax") < result.output.index("calm.lwax")
    assert "Skipped broken.lwax" in result.output
    assert "notes.txt" not in result.output
    assert "Strobe: 1, Smooth: 1" in unstyle(result.output)


def test_cli_flash_check_needs_a_lwax(home, tmp_path):
    save_config(Config())
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    result = CliRunner().invoke(cli, ["ledblinky", "lwax", "flash-check", str(tmp_path)])
    assert result.exit_code == 1
    assert "No .lwax files" in result.output
