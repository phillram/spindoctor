"""LEDBlinky synthesis and INI parsing tests."""
from __future__ import annotations

import textwrap

from spindoctor import ledblinky
from spindoctor.ledblinky import (
    parse_ini_sections,
    parse_listxml,
    synth_colors_section,
    synth_controls_section,
    emit_ini,
)


SAMPLE_LISTXML = textwrap.dedent("""\
    <?xml version="1.0"?>
    <mame>
      <machine name="1942">
        <description>1942 (Capcom)</description>
        <input players="2" coins="2">
          <control type="joy" player="1" buttons="2" ways="8"/>
          <control type="joy" player="2" buttons="2" ways="8"/>
        </input>
      </machine>
      <machine name="pacman">
        <description>Pac-Man</description>
        <input players="2" coins="2">
          <control type="joy" player="1" buttons="0" ways="4"/>
        </input>
      </machine>
      <machine name="bios0">
        <description>BIOS</description>
      </machine>
    </mame>
""").encode("utf-8")


def test_parse_listxml_basic():
    info = parse_listxml(SAMPLE_LISTXML)
    assert "1942" in info
    assert info["1942"].num_players == 2
    assert info["1942"].num_buttons == 2
    assert info["1942"].has_input is True
    # Non-input machines are present but have_input=False.
    assert info["bios0"].has_input is False


def test_synth_controls_emits_buttons_and_joystick():
    info = parse_listxml(SAMPLE_LISTXML)["1942"]
    section = synth_controls_section(info)
    body = "\n".join(section.lines)
    assert "numPlayers=2" in body
    assert "BUTTON1" in body
    assert "BUTTON2" in body
    assert "JOYSTICK_8WAY" in body
    assert "P1_NUMBUTTONS=2" in body


def test_synth_colors_uses_palette():
    info = parse_listxml(SAMPLE_LISTXML)["1942"]
    palette = {"button1": "AAAAAA", "button2": "BBBBBB", "joystick": "CCCCCC"}
    section = synth_colors_section(info, palette)
    body = "\n".join(section.lines)
    assert "ledcolor1=AAAAAA" in body
    assert "ledcolor2=BBBBBB" in body
    assert "joystick=CCCCCC" in body


def test_parse_ini_sections_preserves_lines(tmp_path):
    src = tmp_path / "controls.ini"
    src.write_text(
        textwrap.dedent("""\
            [foo]
            description=Foo
            ; user comment
            P1_NUMBUTTONS=3

            [bar]
            description=Bar
        """),
        encoding="utf-8",
    )
    sections = parse_ini_sections(src)
    assert set(sections.keys()) == {"foo", "bar"}
    foo_body = "\n".join(sections["foo"].lines)
    assert "; user comment" in foo_body
    assert "P1_NUMBUTTONS=3" in foo_body


def test_emit_ini_roundtrip(tmp_path):
    src = tmp_path / "controls.ini"
    src.write_text(
        textwrap.dedent("""\
            [foo]
            description=Foo

            [bar]
            description=Bar
        """),
        encoding="utf-8",
    )
    sections = parse_ini_sections(src)
    out = tmp_path / "out.ini"
    emit_ini(sections, out, header_lines=["; generated"])
    text = out.read_text(encoding="utf-8")
    assert "[foo]" in text
    assert "[bar]" in text
    assert "description=Foo" in text


def test_run_mame_listxml_hides_console_window(monkeypatch):
    """``run_mame_listxml`` must pass ``CREATE_NO_WINDOW`` to ``subprocess.run``.

    A full MAME ``-listxml`` dump takes 10-30 seconds on a hot ROM
    set; without ``CREATE_NO_WINDOW`` the cabinet owner stares at a
    black ``cmd`` window for that whole time every time they run
    ``audit`` from the GUI. The flag is harmless on non-Windows
    (Python's ``subprocess`` ignores it).
    """
    captured: dict = {}

    class _FakeProc:
        returncode = 0
        stdout = b"<mame></mame>"
        stderr = b""

    def fake_run(_args, **kwargs):
        captured.update(kwargs)
        return _FakeProc()

    # Pretend we're on Windows so ``_CREATE_NO_WINDOW`` resolves to
    # the real flag value instead of 0 on the host CI runner.
    monkeypatch.setattr(ledblinky, "_CREATE_NO_WINDOW", 0x08000000)
    monkeypatch.setattr(ledblinky.subprocess, "run", fake_run)
    out = ledblinky.run_mame_listxml("mame")
    assert out == b"<mame></mame>"
    # 0x08000000 == CREATE_NO_WINDOW. Assert the literal value so a
    # refactor that accidentally drops the kwarg fails loudly.
    assert captured.get("creationflags") == 0x08000000
