"""LEDBlinky synthesis and INI parsing tests."""
from __future__ import annotations

import textwrap

from spindoctor import ledblinky
from spindoctor.ledblinky import (
    ColorEntry,
    _normalize_scale_entry,
    _patch_admin_buttons_in_text,
    emit_ini,
    parse_ini_sections,
    parse_listxml,
    synth_colors_section,
    synth_controls_section,
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


# ─── _normalize_scale_entry ───────────────────────────────────────────────────


def test_normalize_scale_entry_full_brightness():
    """100 % brings dominant channel to 48 regardless of stored value."""
    # Already-max white: unchanged
    e = ColorEntry(name="White", r=48, g=48, b=48)
    out = _normalize_scale_entry(e, 1.0)
    assert (out.r, out.g, out.b) == (48, 48, 48)

    # Dim white: boosted to max
    e = ColorEntry(name="DimWhite", r=20, g=20, b=20)
    out = _normalize_scale_entry(e, 1.0)
    assert (out.r, out.g, out.b) == (48, 48, 48)

    # Already-max red: unchanged
    e = ColorEntry(name="Red", r=48, g=0, b=0)
    out = _normalize_scale_entry(e, 1.0)
    assert (out.r, out.g, out.b) == (48, 0, 0)

    # Dim red: dominant channel boosted to 48
    e = ColorEntry(name="DimRed", r=24, g=0, b=0)
    out = _normalize_scale_entry(e, 1.0)
    assert out.r == 48
    assert out.g == 0
    assert out.b == 0


def test_normalize_scale_entry_half_brightness():
    """50 % yields dominant channel = 24, ratios preserved."""
    e = ColorEntry(name="White", r=48, g=48, b=48)
    out = _normalize_scale_entry(e, 0.5)
    assert (out.r, out.g, out.b) == (24, 24, 24)

    e = ColorEntry(name="Red", r=48, g=0, b=0)
    out = _normalize_scale_entry(e, 0.5)
    assert (out.r, out.g, out.b) == (24, 0, 0)

    # Dim white at 50% still produces the same result as bright white at 50%
    e = ColorEntry(name="DimWhite", r=20, g=20, b=20)
    out = _normalize_scale_entry(e, 0.5)
    assert (out.r, out.g, out.b) == (24, 24, 24)


def test_normalize_scale_entry_zero():
    """0 % turns every color off."""
    e = ColorEntry(name="White", r=48, g=48, b=48)
    out = _normalize_scale_entry(e, 0.0)
    assert (out.r, out.g, out.b) == (0, 0, 0)


def test_normalize_scale_entry_pure_black_unchanged():
    """Pure-black entries are returned unchanged at any scale."""
    e = ColorEntry(name="Off", r=0, g=0, b=0)
    for factor in (0.0, 0.5, 1.0):
        out = _normalize_scale_entry(e, factor)
        assert (out.r, out.g, out.b) == (0, 0, 0), f"factor={factor}"


def test_normalize_scale_entry_preserves_hue():
    """Hue ratios between channels are preserved after normalization."""
    # Orange: R dominant, G half, B zero
    e = ColorEntry(name="Orange", r=48, g=24, b=0)
    out_full = _normalize_scale_entry(e, 1.0)
    assert out_full.r == 48
    assert out_full.g == 24
    assert out_full.b == 0

    out_half = _normalize_scale_entry(e, 0.5)
    assert out_half.r == 24
    assert out_half.g == 12
    assert out_half.b == 0

    # Dim orange (half intensity stored) should normalize to same values as full orange
    e_dim = ColorEntry(name="DimOrange", r=24, g=12, b=0)
    out_dim_full = _normalize_scale_entry(e_dim, 1.0)
    assert out_dim_full.r == 48
    assert out_dim_full.g == 24
    assert out_dim_full.b == 0


def test_normalize_scale_entry_name_preserved():
    """Color name is always carried through unchanged."""
    e = ColorEntry(name="Turquoise", r=10, g=40, b=30)
    out = _normalize_scale_entry(e, 0.75)
    assert out.name == "Turquoise"


# ─── _patch_admin_buttons_in_text ─────────────────────────────────────────────


def test_patch_admin_buttons_adds_missing_keys():
    """All specified button keys are added when none exist in a section."""
    text = "[galaga]\nP1_BUTTON1=White\nP1_BUTTON2=White\n\n"
    new_text, count = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Blue"])
    assert count == 1
    assert "P3_BUTTON1=Red" in new_text
    assert "P3_BUTTON2=Blue" in new_text
    # Existing keys must be untouched
    assert "P1_BUTTON1=White" in new_text


def test_patch_admin_buttons_updates_existing_keys():
    """Existing admin button keys are updated to new values."""
    text = "[galaga]\nP3_BUTTON1=White\nP3_BUTTON2=White\n"
    new_text, count = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Green"])
    assert count == 1
    assert "P3_BUTTON1=Red" in new_text
    assert "P3_BUTTON2=Green" in new_text
    assert "P3_BUTTON1=White" not in new_text
    assert "P3_BUTTON2=White" not in new_text


def test_patch_admin_buttons_no_change_when_same():
    """Sections where all values already match are not counted as updated."""
    text = "[galaga]\nP3_BUTTON1=Red\nP3_BUTTON2=Blue\n"
    new_text, count = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Blue"])
    assert count == 0  # nothing changed
    assert new_text == text


def test_patch_admin_buttons_multiple_sections():
    """Every section receives the admin button keys."""
    text = textwrap.dedent("""\
        [galaga]
        P1_BUTTON1=White

        [pacman]
        P1_BUTTON1=Blue
    """)
    _, count = _patch_admin_buttons_in_text(text, admin_player=3,
                                             button_colors=["Green"])
    assert count == 2


def test_patch_admin_buttons_does_not_touch_other_players():
    """Only P{admin_player}_BUTTON* keys are written; other keys untouched."""
    text = "[galaga]\nP1_BUTTON1=White\nP2_BUTTON1=Yellow\nP4_BUTTON1=Purple\n"
    new_text, _ = _patch_admin_buttons_in_text(text, admin_player=3,
                                               button_colors=["Red"])
    assert "P1_BUTTON1=White" in new_text
    assert "P2_BUTTON1=Yellow" in new_text
    assert "P4_BUTTON1=Purple" in new_text
    assert "P3_BUTTON1=Red" in new_text


def test_patch_admin_buttons_empty_sections():
    """Empty input text with no sections returns zero count and empty text."""
    text = ""
    new_text, count = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red"])
    assert count == 0
    assert new_text == ""


def test_patch_admin_buttons_partial_existing():
    """When only some button keys exist they are updated; missing ones are added."""
    text = "[galaga]\nP3_BUTTON1=White\n"
    new_text, count = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Blue", "Green"])
    assert count == 1
    assert "P3_BUTTON1=Red" in new_text    # updated
    assert "P3_BUTTON2=Blue" in new_text   # added
    assert "P3_BUTTON3=Green" in new_text  # added


def test_patch_admin_buttons_different_player_slots():
    """Admin player slot is respected; other slot keys are not touched."""
    text = "[game]\nP2_BUTTON1=White\n"
    new_text, count = _patch_admin_buttons_in_text(text, admin_player=2,
                                                    button_colors=["Red"])
    assert count == 1
    assert "P2_BUTTON1=Red" in new_text

    # Using player=5 on the same text adds P5 and leaves P2 alone
    text2 = "[game]\nP2_BUTTON1=White\n"
    new_text2, count2 = _patch_admin_buttons_in_text(text2, admin_player=5,
                                                      button_colors=["Green"])
    assert count2 == 1
    assert "P2_BUTTON1=White" in new_text2
    assert "P5_BUTTON1=Green" in new_text2


# ─── scale_colors_brightness (integration via Color-RGB.ini temp file) ───────


def test_scale_brightness_full_normalizes_dim_colors(tmp_path, monkeypatch):
    """At 100 %, all dim colors are boosted to full intensity."""
    import types
    from spindoctor.ledblinky import scale_colors_brightness, COLOR_RGB_NAME

    # Write a minimal Color-RGB.ini with one dim color
    color_rgb = tmp_path / COLOR_RGB_NAME
    color_rgb.write_text(
        "[Colors]\nDimWhite=20,20,20\nRed=48,0,0\nOff=0,0,0\n",
        encoding="utf-8",
    )

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = scale_colors_brightness(cfg, scale_pct=100, dry_run=False, backup=False)

    assert result.colors_scaled == 3
    text = color_rgb.read_text(encoding="utf-8")
    # DimWhite should be boosted to 48,48,48
    assert "DimWhite=48,48,48" in text
    # Red stays 48,0,0
    assert "Red=48,0,0" in text
    # Off stays 0,0,0
    assert "Off=0,0,0" in text


def test_scale_brightness_50_percent(tmp_path, monkeypatch):
    """At 50 %, dominant channel = 24 for all non-black colors."""
    import types
    from spindoctor.ledblinky import scale_colors_brightness, COLOR_RGB_NAME

    color_rgb = tmp_path / COLOR_RGB_NAME
    color_rgb.write_text(
        "[Colors]\nWhite=48,48,48\nRed=48,0,0\nOff=0,0,0\n",
        encoding="utf-8",
    )

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = scale_colors_brightness(cfg, scale_pct=50, dry_run=False, backup=False)

    text = color_rgb.read_text(encoding="utf-8")
    assert "White=24,24,24" in text
    assert "Red=24,0,0" in text
    assert "Off=0,0,0" in text


def test_scale_brightness_dry_run_does_not_write(tmp_path):
    """Dry-run must not modify Color-RGB.ini."""
    import types
    from spindoctor.ledblinky import scale_colors_brightness, COLOR_RGB_NAME

    color_rgb = tmp_path / COLOR_RGB_NAME
    original = "[Colors]\nWhite=48,48,48\n"
    color_rgb.write_text(original, encoding="utf-8")

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = scale_colors_brightness(cfg, scale_pct=10, dry_run=True, backup=False)

    assert result.dry_run is True
    assert color_rgb.read_text(encoding="utf-8") == original


# ─── patch_admin_button_colors (integration) ─────────────────────────────────


def test_patch_admin_button_colors_writes_all_sections(tmp_path):
    """patch_admin_button_colors updates every section in Colors.ini."""
    import types
    from spindoctor.ledblinky import (
        patch_admin_button_colors, COLOR_RGB_NAME,
    )

    # Minimal Color-RGB.ini so color validation passes
    color_rgb = tmp_path / COLOR_RGB_NAME
    color_rgb.write_text("[Colors]\nRed=48,0,0\nBlue=0,0,48\nWhite=48,48,48\n",
                         encoding="utf-8")

    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text(
        "[galaga]\nP1_BUTTON1=White\n\n[pacman]\nP1_BUTTON1=White\n",
        encoding="utf-8",
    )

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = patch_admin_button_colors(
        cfg,
        button_colors=["Red", "Blue"],
        admin_player=3,
        dry_run=False,
        backup=False,
    )

    assert result.sections_updated == 2
    text = colors_ini.read_text(encoding="utf-8")
    assert text.count("P3_BUTTON1=Red") == 2
    assert text.count("P3_BUTTON2=Blue") == 2
    # Existing entries must be untouched
    assert "P1_BUTTON1=White" in text


def test_patch_admin_button_colors_dry_run(tmp_path):
    """Dry-run must not write to Colors.ini."""
    import types
    from spindoctor.ledblinky import patch_admin_button_colors, COLOR_RGB_NAME

    color_rgb = tmp_path / COLOR_RGB_NAME
    color_rgb.write_text("[Colors]\nRed=48,0,0\n", encoding="utf-8")

    colors_ini = tmp_path / "Colors.ini"
    original = "[galaga]\nP1_BUTTON1=White\n"
    colors_ini.write_text(original, encoding="utf-8")

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = patch_admin_button_colors(
        cfg, button_colors=["Red"], admin_player=3, dry_run=True, backup=False,
    )

    assert result.dry_run is True
    assert colors_ini.read_text(encoding="utf-8") == original


def test_patch_admin_button_colors_validates_colors(tmp_path):
    """Unknown color names raise ValueError."""
    import types
    import pytest
    from spindoctor.ledblinky import patch_admin_button_colors, COLOR_RGB_NAME

    color_rgb = tmp_path / COLOR_RGB_NAME
    color_rgb.write_text("[Colors]\nRed=48,0,0\n", encoding="utf-8")

    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text("[galaga]\nP1_BUTTON1=White\n", encoding="utf-8")

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    with pytest.raises(ValueError, match="Unknown color"):
        patch_admin_button_colors(
            cfg, button_colors=["NotAColor"], admin_player=3, dry_run=True,
        )
