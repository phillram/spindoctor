"""LEDBlinky .lwax animation builder tests."""
from __future__ import annotations

import textwrap
import xml.etree.ElementTree as ET

import pytest

from spindoctor.lwax import (
    LwaxAnimation,
    build_alternate,
    build_color_cycle,
    build_drain,
    build_fill,
    build_rain,
    build_rainbow_scroll,
    build_wave,
    controls_by_label,
    merge_animations,
    parse_input_map,
)

# A small, deliberately simplified two-board input map: board 1 has one RGB
# control (P1B1) and one unwired port; board 2 has one RGB control (P1B2)
# and a single-color (blank-channel) control (COIN).
SAMPLE_INPUT_MAP = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <dat>
      <ledController type="3" id="1" name="PACLED64">
        <port number="1" label="P1B1" type="R" inputCodes="KEYCODE_A"/>
        <port number="2" label="P1B1" type="G" inputCodes="KEYCODE_A"/>
        <port number="3" label="P1B1" type="B" inputCodes="KEYCODE_A"/>
        <port number="4" label="" type="" inputCodes=""/>
      </ledController>
      <ledController type="3" id="2" name="PACLED64">
        <port number="1" label="P1B2" type="R" inputCodes="KEYCODE_B"/>
        <port number="2" label="P1B2" type="G" inputCodes="KEYCODE_B"/>
        <port number="3" label="P1B2" type="B" inputCodes="KEYCODE_B"/>
        <port number="4" label="COIN" type="" inputCodes="KEYCODE_S"/>
      </ledController>
    </dat>
    """)


@pytest.fixture
def input_map_path(tmp_path):
    p = tmp_path / "LEDBlinkyInputMap.xml"
    p.write_text(SAMPLE_INPUT_MAP, encoding="utf-8")
    return p


def test_parse_input_map(input_map_path):
    controllers = parse_input_map(input_map_path)
    assert len(controllers) == 2
    board1, board2 = controllers
    assert board1.hw_type == "3"
    assert board1.id == "1"
    assert board1.name == "PACLED64"
    assert len(board1.ports) == 4
    assert board1.ports[0].label == "P1B1"
    assert board1.ports[0].channel == "R"
    assert board1.ports[3].label == ""


def test_parse_input_map_missing_file(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        parse_input_map(tmp_path / "nope.xml")


def test_controls_by_label_groups_rgb_triples(input_map_path):
    controllers = parse_input_map(input_map_path)
    mapping = controls_by_label(controllers)

    assert set(mapping.keys()) == {"P1B1", "P1B2", "COIN"}

    (controller, ports) = mapping["P1B1"][0]
    assert controller.id == "1"
    assert [p.channel for p in ports] == ["R", "G", "B"]

    (controller2, ports2) = mapping["P1B2"][0]
    assert controller2.id == "2"
    assert [p.channel for p in ports2] == ["R", "G", "B"]

    # Single-color control: one port, no RGB grouping needed.
    (coin_controller, coin_ports) = mapping["COIN"][0]
    assert coin_controller.id == "2"
    assert len(coin_ports) == 1


def test_animation_unknown_label_rejected(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = LwaxAnimation(controllers)
    with pytest.raises(ValueError, match="Unknown control label"):
        anim.add_frame(40, {"NOT_A_REAL_LABEL": (48, 0, 0)})


def test_animation_color_out_of_range_rejected(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = LwaxAnimation(controllers)
    with pytest.raises(ValueError, match="out of range"):
        anim.add_frame(40, {"P1B1": (49, 0, 0)})


def test_render_is_well_formed_xml(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = LwaxAnimation(controllers)
    anim.add_frame(40, {"P1B1": (48, 0, 0), "P1B2": (0, 48, 0), "COIN": (10, 0, 0)})
    anim.add_frame(40, {"P1B1": (24, 24, 0)})
    xml_text = anim.render()

    root = ET.fromstring(xml_text)
    assert root.tag == "LEDAnimation"
    frames = root.findall("Frame")
    assert len(frames) == 2
    assert frames[0].get("Number") == "1"
    assert frames[0].get("Duration") == "40"


def test_render_frame1_declares_all_controllers_once(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = LwaxAnimation(controllers)
    anim.add_frame(40, {"P1B1": (48, 0, 0)})
    xml_text = anim.render()
    root = ET.fromstring(xml_text)
    frame1 = root.findall("Frame")[0]

    # Both controllers (Id=1 and Id=2) must appear, each with Intensity + State.
    intensities = frame1.findall("Intensity")
    states = frame1.findall("State")
    assert {el.get("Id") for el in intensities} == {"1", "2"}
    assert {el.get("Id") for el in states} == {"1", "2"}

    # Board 1 has 4 ports: P1B1 = R,G,B = 48,0,0, then unwired port = 0.
    board1_intensity = next(el for el in intensities if el.get("Id") == "1")
    assert board1_intensity.get("Value") == "48,0,0,0"
    board1_state = next(el for el in states if el.get("Id") == "1")
    # Wired ports (first 3) are "enabled" (1); the unwired 4th port is 0.
    assert board1_state.get("Value") == "1,1,1,0"


def test_render_only_emits_intensity_delta_after_frame1(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = LwaxAnimation(controllers)
    anim.add_frame(40, {"P1B1": (48, 0, 0), "P1B2": (0, 48, 0)})
    # Second frame only changes P1B1's color — board 2 (P1B2's controller)
    # should not redeclare Intensity, and neither board should redeclare State.
    anim.add_frame(40, {"P1B1": (24, 24, 0)})
    xml_text = anim.render()
    root = ET.fromstring(xml_text)
    frame2 = root.findall("Frame")[1]

    assert [el.get("Id") for el in frame2.findall("Intensity")] == ["1"]
    assert frame2.findall("State") == []


def test_build_color_cycle_boundaries(input_map_path):
    controllers = parse_input_map(input_map_path)
    red = (48, 0, 0)
    green = (0, 48, 0)
    blue = (0, 0, 48)
    anim = build_color_cycle(controllers, [red, green, blue], steps_per_leg=48, duration_ms=40)

    assert len(anim.frames) == 3 * 48
    resolved = anim._resolved_colors()
    # Frame 0 = pure red, frame 48 = pure green, frame 96 = pure blue.
    assert resolved[0]["P1B1"] == red
    assert resolved[48]["P1B1"] == green
    assert resolved[96]["P1B1"] == blue
    # All target labels move together (uniform fade) unless a subset is given.
    assert resolved[0]["P1B2"] == red
    assert resolved[0]["COIN"] == red


def test_build_color_cycle_respects_label_subset(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = build_color_cycle(
        controllers, [(48, 0, 0), (0, 48, 0)], steps_per_leg=4, duration_ms=40, labels=["P1B1"]
    )
    resolved = anim._resolved_colors()
    # P1B2/COIN were never targeted, so they stay at the implicit (0,0,0) default.
    assert resolved[0]["P1B2"] == (0, 0, 0)
    assert resolved[0]["COIN"] == (0, 0, 0)


def test_build_color_cycle_requires_two_colors(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="at least 2 colors"):
        build_color_cycle(controllers, [(48, 0, 0)])


def test_build_color_cycle_rejects_unknown_label(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="Unknown control label"):
        build_color_cycle(controllers, [(48, 0, 0), (0, 48, 0)], labels=["NOPE"])


# ─── build_wave ────────────────────────────────────────────────────────────────

def test_build_wave_leading_edge_advances_through_groups(input_map_path):
    controllers = parse_input_map(input_map_path)
    groups = [["P1B1"], ["P1B2"], ["COIN"]]
    red = (48, 0, 0)
    anim = build_wave(controllers, groups, lead_color=red, frames_per_step=2)

    assert len(anim.frames) == 3 * 2  # 3 groups * 2 frames_per_step
    resolved = anim._resolved_colors()
    # Frames 0-1: P1B1 lit. Frames 2-3: P1B2 lit, P1B1 off (no trail set).
    assert resolved[0]["P1B1"] == red
    assert resolved[0]["P1B2"] == (0, 0, 0)
    assert resolved[2]["P1B2"] == red
    assert resolved[2]["P1B1"] == (0, 0, 0)
    assert resolved[4]["COIN"] == red


def test_build_wave_trail_color_follows_behind(input_map_path):
    controllers = parse_input_map(input_map_path)
    groups = [["P1B1"], ["P1B2"], ["COIN"]]
    red, blue = (48, 0, 0), (0, 0, 48)
    anim = build_wave(
        controllers, groups, lead_color=red, trail_color=blue, lag=1, frames_per_step=1
    )
    resolved = anim._resolved_colors()
    # At position 1 (P1B2 leads), the trail (lag=1) should be on P1B1.
    assert resolved[1]["P1B2"] == red
    assert resolved[1]["P1B1"] == blue
    # Wraps around: at position 0 (P1B1 leads), trail wraps to the last group (COIN).
    assert resolved[0]["P1B1"] == red
    assert resolved[0]["COIN"] == blue


def test_build_wave_reversed_groups_reverses_direction(input_map_path):
    controllers = parse_input_map(input_map_path)
    groups = [["P1B1"], ["P1B2"], ["COIN"]]
    red = (48, 0, 0)
    forward = build_wave(controllers, groups, lead_color=red, frames_per_step=1)
    backward = build_wave(controllers, groups[::-1], lead_color=red, frames_per_step=1)

    forward_resolved = forward._resolved_colors()
    backward_resolved = backward._resolved_colors()
    assert forward_resolved[0]["P1B1"] == red
    assert backward_resolved[0]["COIN"] == red


def test_build_wave_rejects_unknown_label(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="Unknown control label"):
        build_wave(controllers, [["NOPE"]], lead_color=(48, 0, 0))


def test_build_wave_rejects_empty_groups(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="at least 1 group"):
        build_wave(controllers, [], lead_color=(48, 0, 0))


# ─── build_rain ────────────────────────────────────────────────────────────────

def test_build_rain_is_deterministic_given_seed(input_map_path):
    controllers = parse_input_map(input_map_path)
    groups = [["P1B1"], ["P1B2"]]
    red = (48, 0, 0)
    anim1 = build_rain(controllers, groups, colors=[red], total_frames=50, seed=42)
    anim2 = build_rain(controllers, groups, colors=[red], total_frames=50, seed=42)
    assert anim1._resolved_colors() == anim2._resolved_colors()


def test_build_rain_different_seeds_differ(input_map_path):
    controllers = parse_input_map(input_map_path)
    groups = [["P1B1"], ["P1B2"]]
    red = (48, 0, 0)
    anim1 = build_rain(controllers, groups, colors=[red], total_frames=200, seed=1)
    anim2 = build_rain(controllers, groups, colors=[red], total_frames=200, seed=2)
    assert anim1._resolved_colors() != anim2._resolved_colors()


def test_build_rain_produces_correct_frame_count(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = build_rain(controllers, [["P1B1"]], colors=[(48, 0, 0)], total_frames=123)
    assert len(anim.frames) == 123


def test_build_rain_rejects_empty_colors(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="at least 1 color"):
        build_rain(controllers, [["P1B1"]], colors=[])


def test_build_rain_rejects_unknown_label(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="Unknown control label"):
        build_rain(controllers, [["NOPE"]], colors=[(48, 0, 0)])


# ─── build_rainbow_scroll ───────────────────────────────────────────────────────

def test_build_rainbow_scroll_frame_count(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = build_rainbow_scroll(controllers, [["P1B1"], ["P1B2"], ["COIN"]], total_frames=30)
    assert len(anim.frames) == 30


def test_build_rainbow_scroll_hues_spread_across_groups(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim = build_rainbow_scroll(controllers, [["P1B1"], ["P1B2"], ["COIN"]], total_frames=12)
    resolved = anim._resolved_colors()
    # At frame 0, the 3 groups should have 3 distinct colors (spread evenly
    # around the hue wheel), not all the same.
    frame0_colors = {resolved[0]["P1B1"], resolved[0]["P1B2"], resolved[0]["COIN"]}
    assert len(frame0_colors) == 3


def test_build_rainbow_scroll_colocated_labels_share_hue(input_map_path):
    controllers = parse_input_map(input_map_path)
    # P1B1 and P1B2 share one group -- they should always match exactly,
    # unlike two labels in separate groups which only differ by a hue step.
    anim = build_rainbow_scroll(controllers, [["P1B1", "P1B2"], ["COIN"]], total_frames=10)
    resolved = anim._resolved_colors()
    for frame_colors in resolved:
        assert frame_colors["P1B1"] == frame_colors["P1B2"]


def test_build_rainbow_scroll_rejects_unknown_label(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="Unknown control label"):
        build_rainbow_scroll(controllers, [["NOPE"]])


def test_build_rainbow_scroll_rejects_empty_groups(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="at least 1 group"):
        build_rainbow_scroll(controllers, [])


# ─── build_fill ────────────────────────────────────────────────────────────────

def test_build_fill_accumulates_without_clearing_earlier_groups(input_map_path):
    controllers = parse_input_map(input_map_path)
    red = (48, 0, 0)
    anim = build_fill(
        controllers, [["P1B1"], ["P1B2"], ["COIN"]], fill_color=red,
        frames_per_step=1, hold_frames=1, flash_color=None,
    )
    resolved = anim._resolved_colors()
    # After the 3rd group joins, all 3 should still be lit (accumulating fill).
    assert resolved[2]["P1B1"] == red
    assert resolved[2]["P1B2"] == red
    assert resolved[2]["COIN"] == red
    # Before the 2nd group joins, only the 1st should be lit.
    assert resolved[0]["P1B1"] == red
    assert resolved[0]["P1B2"] == (0, 0, 0)


def test_build_fill_flashes_then_holds(input_map_path):
    controllers = parse_input_map(input_map_path)
    red, white = (48, 0, 0), (48, 48, 48)
    anim = build_fill(
        controllers, [["P1B1"]], fill_color=red, flash_color=white,
        frames_per_step=1, hold_frames=2, flash_cycles=1, flash_frames=2,
    )
    # 1 fill frame + 2 hold frames + 2 flash-on + 2 flash-off = 7 frames.
    assert len(anim.frames) == 7
    resolved = anim._resolved_colors()
    assert resolved[0]["P1B1"] == red        # filling
    assert resolved[1]["P1B1"] == red        # holding
    assert resolved[3]["P1B1"] == white       # flash on
    assert resolved[5]["P1B1"] == (0, 0, 0)  # flash off


def test_build_fill_rejects_empty_groups(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="at least 1 group"):
        build_fill(controllers, [], fill_color=(48, 0, 0))


def test_build_fill_rejects_unknown_label(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="Unknown control label"):
        build_fill(controllers, [["NOPE"]], fill_color=(48, 0, 0))


# ─── merge_animations ───────────────────────────────────────────────────────────

def test_merge_animations_combines_disjoint_labels(input_map_path):
    controllers = parse_input_map(input_map_path)
    red, blue = (48, 0, 0), (0, 0, 48)
    anim1 = build_wave(controllers, [["P1B1"], ["P1B2"]], lead_color=red, frames_per_step=1)
    anim2 = build_wave(controllers, [["COIN"]], lead_color=blue, frames_per_step=1)
    # anim2 only has 1 group -> 1 frame; pad it to match anim1's 2 frames by
    # building with a repeated group instead.
    anim2 = build_wave(controllers, [["COIN"], ["COIN"]], lead_color=blue, frames_per_step=1)

    merged = merge_animations(anim1, anim2)
    resolved = merged._resolved_colors()
    assert resolved[0]["P1B1"] == red
    assert resolved[0]["COIN"] == blue
    assert resolved[1]["P1B2"] == red
    assert resolved[1]["COIN"] == blue


def test_merge_animations_rejects_mismatched_frame_counts(input_map_path):
    controllers = parse_input_map(input_map_path)
    anim1 = build_wave(controllers, [["P1B1"], ["P1B2"]], lead_color=(48, 0, 0), frames_per_step=1)
    anim2 = build_wave(controllers, [["COIN"]], lead_color=(0, 0, 48), frames_per_step=1)
    with pytest.raises(ValueError, match="same frame count"):
        merge_animations(anim1, anim2)


# ─── build_drain ───────────────────────────────────────────────────────────────

def test_build_drain_extinguishes_in_order_without_relighting(input_map_path):
    controllers = parse_input_map(input_map_path)
    red = (48, 0, 0)
    anim = build_drain(
        controllers, [["P1B1"], ["P1B2"], ["COIN"]], fill_color=red,
        frames_per_step=1, hold_full_frames=1, hold_empty_frames=1, flash_color=None,
    )
    resolved = anim._resolved_colors()
    # Frame 0: everything still lit (hold_full).
    assert resolved[0]["P1B1"] == red
    assert resolved[0]["P1B2"] == red
    assert resolved[0]["COIN"] == red
    # After P1B1's group drains (frame 1): P1B1 off, rest still lit.
    assert resolved[1]["P1B1"] == (0, 0, 0)
    assert resolved[1]["P1B2"] == red
    assert resolved[1]["COIN"] == red
    # After all 3 drain: everything off.
    assert resolved[3]["P1B1"] == (0, 0, 0)
    assert resolved[3]["P1B2"] == (0, 0, 0)
    assert resolved[3]["COIN"] == (0, 0, 0)


def test_build_drain_flashes_after_emptying(input_map_path):
    controllers = parse_input_map(input_map_path)
    red, white = (48, 0, 0), (48, 48, 48)
    anim = build_drain(
        controllers, [["P1B1"]], fill_color=red, flash_color=white,
        frames_per_step=1, hold_full_frames=1, hold_empty_frames=1,
        flash_cycles=1, flash_frames=1,
    )
    # 1 hold-full + 1 drain step + 1 hold-empty + 1 flash-on + 1 flash-off = 5 frames.
    assert len(anim.frames) == 5
    resolved = anim._resolved_colors()
    assert resolved[0]["P1B1"] == red    # holding full
    assert resolved[1]["P1B1"] == (0, 0, 0)  # drained
    assert resolved[3]["P1B1"] == white  # flash on
    assert resolved[4]["P1B1"] == (0, 0, 0)  # flash off


def test_build_drain_rejects_empty_groups(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="at least 1 group"):
        build_drain(controllers, [], fill_color=(48, 0, 0))


def test_build_drain_rejects_unknown_label(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="Unknown control label"):
        build_drain(controllers, [["NOPE"]], fill_color=(48, 0, 0))


# ─── build_alternate ────────────────────────────────────────────────────────────

def test_build_alternate_swaps_colors_in_lockstep(input_map_path):
    controllers = parse_input_map(input_map_path)
    red, blue = (48, 0, 0), (0, 0, 48)
    anim = build_alternate(
        controllers, group_a=["P1B1"], group_b=["P1B2"],
        color_a=red, color_b=blue, hold_ms=100, cycles=2,
    )
    assert len(anim.frames) == 4  # 2 phases * 2 cycles
    resolved = anim._resolved_colors()
    assert resolved[0]["P1B1"] == red
    assert resolved[0]["P1B2"] == blue
    assert resolved[1]["P1B1"] == blue
    assert resolved[1]["P1B2"] == red
    assert resolved[2]["P1B1"] == red
    assert resolved[2]["P1B2"] == blue


def test_build_alternate_rejects_unknown_label(input_map_path):
    controllers = parse_input_map(input_map_path)
    with pytest.raises(ValueError, match="Unknown control label"):
        build_alternate(controllers, group_a=["NOPE"], group_b=["P1B2"], color_a=(48, 0, 0), color_b=(0, 0, 48))
