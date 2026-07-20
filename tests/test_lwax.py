"""LEDBlinky .lwax animation builder tests."""
from __future__ import annotations

import textwrap
import xml.etree.ElementTree as ET

import pytest

from spindoctor.lwax import (
    LwaxAnimation,
    build_color_cycle,
    controls_by_label,
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
