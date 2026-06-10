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
    sync_player_colors,
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
    """controls.ini sections must use LedBlinky runtime key names.

    LedBlinky treats every unrecognised key as a literal control identifier.
    Keys like P1_NUMBUTTONS or P1_CONTROLS are not recognised and silently
    replace the real button names, breaking LED mapping at game launch.
    """
    info = parse_listxml(SAMPLE_LISTXML)["1942"]
    section = synth_controls_section(info)
    body = "\n".join(section.lines)
    assert "numPlayers=2" in body
    assert "alternating=0" in body
    # Buttons and joystick must use LedBlinky's runtime key names
    assert "P1_BUTTON1=1" in body
    assert "P1_BUTTON2=1" in body
    assert "P1_JOYSTICK=1" in body
    assert "P1_START=1" in body
    assert "P1_COIN=1" in body
    # P2 must also be present for a 2-player game
    assert "P2_BUTTON1=1" in body
    assert "P2_JOYSTICK=1" in body
    assert "P2_START=1" in body
    assert "P2_COIN=1" in body
    # Old metadata-style keys must NOT appear
    assert "P1_NUMBUTTONS" not in body
    assert "P1_CONTROLS" not in body
    assert "JOYSTICK_8WAY" not in body


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
    new_text, names = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Blue"])
    assert len(names) == 1
    assert "P3_BUTTON1=Red" in new_text
    assert "P3_BUTTON2=Blue" in new_text
    # Existing keys must be untouched
    assert "P1_BUTTON1=White" in new_text


def test_patch_admin_buttons_updates_existing_keys():
    """Existing admin button keys are updated to new values."""
    text = "[galaga]\nP3_BUTTON1=White\nP3_BUTTON2=White\n"
    new_text, names = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Green"])
    assert len(names) == 1
    assert "P3_BUTTON1=Red" in new_text
    assert "P3_BUTTON2=Green" in new_text
    assert "P3_BUTTON1=White" not in new_text
    assert "P3_BUTTON2=White" not in new_text


def test_patch_admin_buttons_no_change_when_same():
    """Sections where all values already match are not counted as updated."""
    text = "[galaga]\nP3_BUTTON1=Red\nP3_BUTTON2=Blue\n"
    new_text, names = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Blue"])
    assert len(names) == 0  # nothing changed
    assert new_text == text


def test_patch_admin_buttons_multiple_sections():
    """Every section receives the admin button keys."""
    text = textwrap.dedent("""\
        [galaga]
        P1_BUTTON1=White

        [pacman]
        P1_BUTTON1=Blue
    """)
    _, names = _patch_admin_buttons_in_text(text, admin_player=3,
                                             button_colors=["Green"])
    assert len(names) == 2


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
    new_text, names = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red"])
    assert len(names) == 0
    assert new_text == ""


def test_patch_admin_buttons_partial_existing():
    """When only some button keys exist they are updated; missing ones are added."""
    text = "[galaga]\nP3_BUTTON1=White\n"
    new_text, names = _patch_admin_buttons_in_text(text, admin_player=3,
                                                    button_colors=["Red", "Blue", "Green"])
    assert len(names) == 1
    assert "P3_BUTTON1=Red" in new_text    # updated
    assert "P3_BUTTON2=Blue" in new_text   # added
    assert "P3_BUTTON3=Green" in new_text  # added


def test_patch_admin_buttons_different_player_slots():
    """Admin player slot is respected; other slot keys are not touched."""
    text = "[game]\nP2_BUTTON1=White\n"
    new_text, names = _patch_admin_buttons_in_text(text, admin_player=2,
                                                    button_colors=["Red"])
    assert len(names) == 1
    assert "P2_BUTTON1=Red" in new_text

    # Using player=5 on the same text adds P5 and leaves P2 alone
    text2 = "[game]\nP2_BUTTON1=White\n"
    new_text2, names2 = _patch_admin_buttons_in_text(text2, admin_player=5,
                                                      button_colors=["Green"])
    assert len(names2) == 1
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


# ── _uniform_section_color ─────────────────────────────────────────────────────

def test_uniform_section_color_single_color():
    """All button keys share one color → returns that color."""
    from spindoctor.ledblinky import _uniform_section_color
    lines = [
        "P1_BUTTON1=White\n",
        "P1_BUTTON2=White\n",
        "P1_JOYSTICK=White\n",
        "P1_START=White\n",
        "P1_COIN=White\n",
    ]
    assert _uniform_section_color(lines) == "White"


def test_uniform_section_color_mixed():
    """Mixed colors → returns None."""
    from spindoctor.ledblinky import _uniform_section_color
    lines = [
        "P1_BUTTON1=Blue\n",
        "P1_BUTTON2=Orange\n",
        "P1_START=White\n",
    ]
    assert _uniform_section_color(lines) is None


def test_uniform_section_color_two_players_uniform():
    """P1 and P2 all same color → uniform."""
    from spindoctor.ledblinky import _uniform_section_color
    lines = [
        "P1_BUTTON1=Red\n",
        "P1_BUTTON2=Red\n",
        "P2_BUTTON1=Red\n",
        "P2_BUTTON2=Red\n",
    ]
    assert _uniform_section_color(lines) == "Red"


def test_uniform_section_color_two_players_mixed_across():
    """P1=Red but P2=Green → mixed → None."""
    from spindoctor.ledblinky import _uniform_section_color
    lines = [
        "P1_BUTTON1=Red\n",
        "P2_BUTTON1=Green\n",
    ]
    assert _uniform_section_color(lines) is None


def test_uniform_section_color_no_player_keys():
    """Section with no P*_BUTTON keys → None (can't determine uniformity)."""
    from spindoctor.ledblinky import _uniform_section_color
    lines = [
        "ledcolor1=FF0000\n",
        "ledcolor2=00FF00\n",
    ]
    assert _uniform_section_color(lines) is None


def test_uniform_section_color_empty():
    """Empty section body → None."""
    from spindoctor.ledblinky import _uniform_section_color
    assert _uniform_section_color([]) is None


def test_uniform_section_color_ignores_non_player_lines():
    """Non-button lines (blank, comments, hex entries) don't count."""
    from spindoctor.ledblinky import _uniform_section_color
    lines = [
        "\n",
        "; this is a comment\n",
        "P1_BUTTON1=Blue\n",
        "P1_BUTTON2=Blue\n",
    ]
    assert _uniform_section_color(lines) == "Blue"


# ── _rewrite_section_body ──────────────────────────────────────────────────────

def test_rewrite_section_body_replaces_values():
    """Existing key values are replaced with new_color."""
    from spindoctor.ledblinky import _rewrite_section_body
    lines = ["P1_BUTTON1=Red\n", "P1_BUTTON2=Red\n"]
    out = _rewrite_section_body(lines, "White", n_players=1, n_buttons=2,
                                admin_player=2, admin_buttons=0,
                                admin_color="White", no_add_keys=True)
    assert "P1_BUTTON1=White\n" in out
    assert "P1_BUTTON2=White\n" in out


def test_rewrite_section_body_no_add_keys_adds_nothing():
    """With no_add_keys=True, no new keys are inserted."""
    from spindoctor.ledblinky import _rewrite_section_body
    lines = ["P1_BUTTON1=Red\n", "P1_BUTTON2=Red\n"]
    out = _rewrite_section_body(lines, "White", n_players=1, n_buttons=6,
                                admin_player=2, admin_buttons=0,
                                admin_color="White", no_add_keys=True)
    keys = [l.split("=")[0] for l in out if "=" in l]
    assert keys == ["P1_BUTTON1", "P1_BUTTON2"]


def test_rewrite_section_body_adds_missing_keys():
    """With no_add_keys=False, missing keys are added."""
    from spindoctor.ledblinky import _rewrite_section_body
    lines = ["P1_BUTTON1=Red\n", "P1_BUTTON2=Red\n"]
    out = _rewrite_section_body(lines, "White", n_players=1, n_buttons=3,
                                admin_player=2, admin_buttons=0,
                                admin_color="White", no_add_keys=False)
    out_text = "".join(out)
    assert "P1_BUTTON3=White" in out_text
    assert "P1_JOYSTICK=White" in out_text
    assert "P1_START=White" in out_text
    assert "P1_COIN=White" in out_text


def test_rewrite_section_body_admin_color():
    """Admin player gets admin_color, not new_color."""
    from spindoctor.ledblinky import _rewrite_section_body
    lines = [
        "P1_BUTTON1=Red\n",
        "P3_BUTTON1=Red\n",
    ]
    out = _rewrite_section_body(lines, "White", n_players=1, n_buttons=1,
                                admin_player=3, admin_buttons=1,
                                admin_color="Green", no_add_keys=True)
    out_text = "".join(out)
    assert "P1_BUTTON1=White" in out_text
    assert "P3_BUTTON1=Green" in out_text


# ── fill_default_colors with override_uniform ──────────────────────────────────

def _make_cfg(tmp_path):
    import types
    cfg = types.SimpleNamespace(
        ledblinky_dir=str(tmp_path),
        databases_dir=str(tmp_path / "Databases"),
        hyperspin_dir=str(tmp_path),
        roms_dir=str(tmp_path / "Roms"),
        backup_dir="",
        backup_before_modify=False,
    )
    (tmp_path / "Roms").mkdir(exist_ok=True)
    return cfg


def _write_db(tmp_path, system, roms):
    """Create a minimal HyperSpin database XML."""
    db_dir = tmp_path / "Databases" / system
    db_dir.mkdir(parents=True, exist_ok=True)
    entries = "".join(f'  <game name="{r}"><description>{r}</description></game>\n' for r in roms)
    (db_dir / f"{system}.xml").write_text(
        f'<?xml version="1.0"?><menu>{entries}</menu>', encoding="utf-8"
    )


def test_fill_default_override_uniform_replaces_same_color(tmp_path):
    """Sections where all buttons share one color are rewritten with new color."""
    from spindoctor.ledblinky import fill_default_colors
    cfg = _make_cfg(tmp_path)
    _write_db(tmp_path, "Arcade", ["pacman", "galaga"])

    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text(
        "[pacman]\nP1_BUTTON1=Red\nP1_BUTTON2=Red\n\n"
        "[galaga]\nP1_BUTTON1=Blue\nP1_BUTTON2=Orange\n\n",
        encoding="utf-8",
    )

    result = fill_default_colors(
        cfg, default_color="White", n_buttons=2, n_players=1,
        override_uniform=True, no_add_keys=True, dry_run=False, backup=False,
    )

    text = colors_ini.read_text(encoding="utf-8")
    # pacman was uniform (all Red) → overridden to White
    assert "P1_BUTTON1=White" in text
    assert result.roms_overridden == 1
    # galaga was mixed → left untouched
    assert "P1_BUTTON2=Orange" in text
    assert result.roms_skipped_mixed == 1


def test_fill_default_override_uniform_dry_run_no_write(tmp_path):
    """Dry-run does not modify Colors.ini even with override_uniform."""
    from spindoctor.ledblinky import fill_default_colors
    cfg = _make_cfg(tmp_path)
    _write_db(tmp_path, "Arcade", ["pacman"])

    original = "[pacman]\nP1_BUTTON1=Red\nP1_BUTTON2=Red\n"
    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text(original, encoding="utf-8")

    result = fill_default_colors(
        cfg, default_color="White", n_buttons=2, n_players=1,
        override_uniform=True, dry_run=True, backup=False,
    )

    assert colors_ini.read_text(encoding="utf-8") == original
    assert result.dry_run is True
    assert result.roms_overridden == 1  # detected but not written


def test_fill_default_no_add_keys_preserves_key_count(tmp_path):
    """no_add_keys=True: overriding a 2-button section stays at 2 buttons."""
    from spindoctor.ledblinky import fill_default_colors
    cfg = _make_cfg(tmp_path)
    _write_db(tmp_path, "Arcade", ["pacman"])

    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text("[pacman]\nP1_BUTTON1=Red\nP1_BUTTON2=Red\n",
                          encoding="utf-8")

    fill_default_colors(
        cfg, default_color="White", n_buttons=6, n_players=1,
        override_uniform=True, no_add_keys=True, dry_run=False, backup=False,
    )

    text = colors_ini.read_text(encoding="utf-8")
    # Should NOT have added BUTTON3–BUTTON6 or JOYSTICK/START/COIN
    assert "P1_BUTTON3" not in text
    assert "P1_JOYSTICK" not in text
    assert "P1_BUTTON1=White" in text
    assert "P1_BUTTON2=White" in text


def test_fill_default_add_keys_extends_section(tmp_path):
    """no_add_keys=False (default): missing keys are added when overriding."""
    from spindoctor.ledblinky import fill_default_colors
    cfg = _make_cfg(tmp_path)
    _write_db(tmp_path, "Arcade", ["pacman"])

    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text("[pacman]\nP1_BUTTON1=Red\nP1_BUTTON2=Red\n",
                          encoding="utf-8")

    fill_default_colors(
        cfg, default_color="White", n_buttons=3, n_players=1,
        override_uniform=True, no_add_keys=False, dry_run=False, backup=False,
    )

    text = colors_ini.read_text(encoding="utf-8")
    assert "P1_BUTTON3=White" in text
    assert "P1_JOYSTICK=White" in text


def test_fill_default_new_entries_still_added_alongside_overrides(tmp_path):
    """fill_default_colors adds NEW entries AND applies overrides in one pass."""
    from spindoctor.ledblinky import fill_default_colors
    cfg = _make_cfg(tmp_path)
    _write_db(tmp_path, "Arcade", ["pacman", "newgame"])

    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text("[pacman]\nP1_BUTTON1=Red\nP1_BUTTON2=Red\n\n",
                          encoding="utf-8")

    result = fill_default_colors(
        cfg, default_color="White", n_buttons=2, n_players=1,
        override_uniform=True, no_add_keys=True, dry_run=False, backup=False,
    )

    text = colors_ini.read_text(encoding="utf-8")
    assert result.roms_added == 1       # newgame added
    assert result.roms_overridden == 1  # pacman overridden
    assert "[newgame]" in text
    assert "P1_BUTTON1=White" in text   # both pacman override and newgame entry


# ─── _randomize_section_body ─────────────────────────────────────────────────


def test_randomize_section_body_rewrites_button_keys():
    """BUTTON* and JOYSTICK keys are replaced with button_color."""
    from spindoctor.ledblinky import _randomize_section_body
    body = [
        "P1_BUTTON1=Red\n",
        "P1_BUTTON2=Red\n",
        "P1_JOYSTICK=Red\n",
    ]
    new_body, had_keys = _randomize_section_body(body, "Blue", "Green")
    assert had_keys is True
    assert new_body == [
        "P1_BUTTON1=Blue\n",
        "P1_BUTTON2=Blue\n",
        "P1_JOYSTICK=Blue\n",
    ]


def test_randomize_section_body_coin_start_use_second_color():
    """COIN and START keys get coin_start_color, not button_color."""
    from spindoctor.ledblinky import _randomize_section_body
    body = [
        "P1_BUTTON1=White\n",
        "P1_COIN=White\n",
        "P1_START=White\n",
    ]
    new_body, had_keys = _randomize_section_body(body, "Yellow", "Cyan")
    assert had_keys is True
    texts = "".join(new_body)
    assert "P1_BUTTON1=Yellow" in texts
    assert "P1_COIN=Cyan" in texts
    assert "P1_START=Cyan" in texts


def test_randomize_section_body_no_new_keys_added():
    """_randomize_section_body never inserts lines that were not already there."""
    from spindoctor.ledblinky import _randomize_section_body
    body = ["P1_BUTTON1=Red\n"]
    new_body, had_keys = _randomize_section_body(body, "Blue", "Green")
    # Exactly one line in, exactly one line out
    assert len(new_body) == 1
    assert "P1_BUTTON2" not in "".join(new_body)
    assert "P1_JOYSTICK" not in "".join(new_body)


def test_randomize_section_body_empty_section_returns_no_keys():
    """An empty (or comment-only) section returns had_keys=False."""
    from spindoctor.ledblinky import _randomize_section_body
    body = ["; comment line\n", "\n"]
    new_body, had_keys = _randomize_section_body(body, "Blue", "Green")
    assert had_keys is False
    assert new_body == ["; comment line\n", "\n"]


def test_randomize_section_body_preserves_non_player_lines():
    """Non-player-key lines (comments, blanks, custom keys) pass through unchanged."""
    from spindoctor.ledblinky import _randomize_section_body
    body = [
        "; some comment\n",
        "P1_BUTTON1=Old\n",
        "\n",
        "CustomKey=something\n",
    ]
    new_body, had_keys = _randomize_section_body(body, "New", "New")
    assert had_keys is True
    assert new_body[0] == "; some comment\n"
    assert new_body[2] == "\n"
    assert new_body[3] == "CustomKey=something\n"
    assert new_body[1] == "P1_BUTTON1=New\n"


def test_randomize_section_body_multi_player_all_updated():
    """P2, P3 button keys are also updated."""
    from spindoctor.ledblinky import _randomize_section_body
    body = [
        "P1_BUTTON1=Red\n",
        "P2_BUTTON1=Red\n",
        "P2_JOYSTICK=Red\n",
        "P1_START=Red\n",
    ]
    new_body, had_keys = _randomize_section_body(body, "Blue", "Orange")
    texts = "".join(new_body)
    assert "P1_BUTTON1=Blue" in texts
    assert "P2_BUTTON1=Blue" in texts
    assert "P2_JOYSTICK=Blue" in texts
    assert "P1_START=Orange" in texts


# ─── randomize_entry_colors (integration) ────────────────────────────────────


def test_randomize_entry_colors_updates_all_sections(tmp_path):
    """Every section with player keys gets new colors."""
    import types
    from spindoctor.ledblinky import randomize_entry_colors, COLOR_RGB_NAME

    (tmp_path / COLOR_RGB_NAME).write_text(
        "[Colors]\nRed=48,0,0\nBlue=0,0,48\nGreen=0,48,0\n",
        encoding="utf-8",
    )
    colors_ini = tmp_path / "Colors.ini"
    original = (
        "[pacman]\nP1_BUTTON1=White\nP1_COIN=White\n\n"
        "[galaga]\nP1_BUTTON1=White\nP1_START=White\n"
    )
    colors_ini.write_text(original, encoding="utf-8")

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = randomize_entry_colors(cfg, dry_run=False, backup=False, seed=1)

    assert result.dry_run is False
    assert result.sections_updated == 2
    assert result.sections_skipped == 0
    assert result.palette_size == 3

    text = colors_ini.read_text(encoding="utf-8")
    # Keys must still be present
    assert "P1_BUTTON1=" in text
    assert "P1_COIN=" in text
    assert "P1_START=" in text
    # Original color "White" must be gone (replaced)
    assert "=White" not in text


def test_randomize_entry_colors_dry_run_does_not_write(tmp_path):
    """Dry-run leaves Colors.ini unchanged."""
    import types
    from spindoctor.ledblinky import randomize_entry_colors, COLOR_RGB_NAME

    (tmp_path / COLOR_RGB_NAME).write_text(
        "[Colors]\nRed=48,0,0\nBlue=0,0,48\n",
        encoding="utf-8",
    )
    colors_ini = tmp_path / "Colors.ini"
    original = "[pacman]\nP1_BUTTON1=White\n"
    colors_ini.write_text(original, encoding="utf-8")

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = randomize_entry_colors(cfg, dry_run=True, backup=False, seed=99)

    assert result.dry_run is True
    assert result.sections_updated == 1  # detected but not written
    assert colors_ini.read_text(encoding="utf-8") == original


def test_randomize_entry_colors_reproducible_with_seed(tmp_path):
    """The same seed applied twice produces identical Colors.ini output."""
    import types
    from spindoctor.ledblinky import randomize_entry_colors, COLOR_RGB_NAME

    palette = "[Colors]\nRed=48,0,0\nBlue=0,0,48\nGreen=0,48,0\nYellow=48,48,0\n"
    (tmp_path / COLOR_RGB_NAME).write_text(palette, encoding="utf-8")

    original = (
        "[pacman]\nP1_BUTTON1=White\nP1_COIN=White\n\n"
        "[galaga]\nP1_BUTTON1=White\n\n"
        "[mspacman]\nP1_BUTTON1=White\nP1_START=White\n"
    )

    # First run
    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text(original, encoding="utf-8")
    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    randomize_entry_colors(cfg, dry_run=False, backup=False, seed=42)
    text_first = colors_ini.read_text(encoding="utf-8")

    # Second run with same seed
    colors_ini.write_text(original, encoding="utf-8")
    randomize_entry_colors(cfg, dry_run=False, backup=False, seed=42)
    text_second = colors_ini.read_text(encoding="utf-8")

    assert text_first == text_second


def test_randomize_entry_colors_skips_sections_without_player_keys(tmp_path):
    """Sections with no P*_BUTTON*/JOYSTICK/COIN/START keys are counted as skipped."""
    import types
    from spindoctor.ledblinky import randomize_entry_colors, COLOR_RGB_NAME

    (tmp_path / COLOR_RGB_NAME).write_text(
        "[Colors]\nRed=48,0,0\n",
        encoding="utf-8",
    )
    colors_ini = tmp_path / "Colors.ini"
    colors_ini.write_text(
        "[no_keys_game]\nSomeOtherKey=value\n",
        encoding="utf-8",
    )

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    result = randomize_entry_colors(cfg, dry_run=False, backup=False, seed=0)

    assert result.sections_updated == 0
    assert result.sections_skipped == 1


def test_randomize_entry_colors_never_assigns_black(tmp_path):
    """Off/black colors (all channels 0) are never chosen."""
    import types
    from spindoctor.ledblinky import randomize_entry_colors, COLOR_RGB_NAME

    # Palette with one real color and one off/black entry
    (tmp_path / COLOR_RGB_NAME).write_text(
        "[Colors]\nRed=48,0,0\nOff=0,0,0\n",
        encoding="utf-8",
    )
    colors_ini = tmp_path / "Colors.ini"
    # Many sections so statistically we'd hit black if it were in the pool
    sections = "\n".join(
        f"[game{i}]\nP1_BUTTON1=White\nP1_COIN=White\n"
        for i in range(20)
    )
    colors_ini.write_text(sections, encoding="utf-8")

    cfg = types.SimpleNamespace(ledblinky_dir=str(tmp_path), backup_dir="",
                                backup_before_modify=False)
    randomize_entry_colors(cfg, dry_run=False, backup=False)

    text = colors_ini.read_text(encoding="utf-8")
    assert "=Off" not in text
    assert "=Red" in text  # Red must have been chosen for all games


# ── sync_player_colors ────────────────────────────────────────────────────────

def _write_sync_fixtures(tmp_path, controls_text: str, colors_text: str):
    """Write controls.ini and colors.ini to tmp_path and return a minimal config."""
    import types
    (tmp_path / "controls.ini").write_text(controls_text, encoding="utf-8")
    (tmp_path / "Colors.ini").write_text(colors_text, encoding="utf-8")
    return types.SimpleNamespace(
        ledblinky_dir=str(tmp_path),
        backup_dir="",
        backup_before_modify=False,
    )


def test_sync_players_adds_missing_p2_keys(tmp_path):
    """P2 keys present in controls.ini but absent from Colors.ini are added."""
    controls = (
        "[005]\n"
        "numPlayers=2\n"
        "alternating=0\n"
        "P1_BUTTON1=1\nP1_JOYSTICK=1\nP1_START=1\nP1_COIN=1\n"
        "P2_BUTTON1=1\nP2_JOYSTICK=1\nP2_START=1\nP2_COIN=1\n"
    )
    colors = (
        "[005]\n"
        "P1_BUTTON1=Red\nP1_JOYSTICK=White\nP1_START=White\nP1_COIN=Orange\n"
    )
    cfg = _write_sync_fixtures(tmp_path, controls, colors)

    result = sync_player_colors(cfg, dry_run=False, backup=False)

    assert result.roms_updated == 1
    assert result.keys_added == 4  # P2_BUTTON1, P2_JOYSTICK, P2_START, P2_COIN
    text = (tmp_path / "Colors.ini").read_text(encoding="utf-8")
    assert "P2_BUTTON1=Red" in text
    assert "P2_JOYSTICK=White" in text
    assert "P2_START=White" in text
    assert "P2_COIN=Orange" in text
    # P1 keys must still be present and unchanged
    assert "P1_BUTTON1=Red" in text


def test_sync_players_mirrors_p1_color_per_key(tmp_path):
    """Each P2 key gets the same color as the matching P1 key, not a uniform color."""
    controls = (
        "[mygame]\n"
        "P1_BUTTON1=1\nP1_BUTTON2=1\nP2_BUTTON1=1\nP2_BUTTON2=1\n"
    )
    colors = (
        "[mygame]\n"
        "P1_BUTTON1=Red\nP1_BUTTON2=Blue\n"
    )
    cfg = _write_sync_fixtures(tmp_path, controls, colors)
    sync_player_colors(cfg, dry_run=False, backup=False)

    text = (tmp_path / "Colors.ini").read_text(encoding="utf-8")
    assert "P2_BUTTON1=Red" in text
    assert "P2_BUTTON2=Blue" in text


def test_sync_players_does_not_overwrite_existing_p2_keys(tmp_path):
    """Keys already present in Colors.ini for P2 are left untouched."""
    controls = (
        "[mygame]\n"
        "P1_BUTTON1=1\nP2_BUTTON1=1\n"
    )
    colors = (
        "[mygame]\n"
        "P1_BUTTON1=Red\nP2_BUTTON1=Green\n"
    )
    cfg = _write_sync_fixtures(tmp_path, controls, colors)
    result = sync_player_colors(cfg, dry_run=False, backup=False)

    assert result.roms_updated == 0
    assert result.keys_added == 0
    text = (tmp_path / "Colors.ini").read_text(encoding="utf-8")
    assert "P2_BUTTON1=Green" in text  # original value preserved


def test_sync_players_skips_key_when_p1_color_absent(tmp_path):
    """If P1_KEY is not in Colors.ini, no Pn_KEY is added (nothing to mirror)."""
    controls = (
        "[mygame]\n"
        "P1_JOYSTICK=1\nP2_JOYSTICK=1\n"
    )
    # Colors.ini only has a button entry — no P1_JOYSTICK to mirror from
    colors = (
        "[mygame]\n"
        "P1_BUTTON1=Red\n"
    )
    cfg = _write_sync_fixtures(tmp_path, controls, colors)
    result = sync_player_colors(cfg, dry_run=False, backup=False)

    assert result.roms_updated == 0
    text = (tmp_path / "Colors.ini").read_text(encoding="utf-8")
    assert "P2_JOYSTICK" not in text


def test_sync_players_skips_roms_without_controls_ini_entry(tmp_path):
    """ROMs that have no controls.ini entry are counted as skipped."""
    controls = "[othergame]\nP1_BUTTON1=1\nP2_BUTTON1=1\n"
    colors = "[mygame]\nP1_BUTTON1=Red\n"
    cfg = _write_sync_fixtures(tmp_path, controls, colors)
    result = sync_player_colors(cfg, dry_run=False, backup=False)

    assert result.roms_updated == 0
    assert result.roms_skipped_no_controls == 1


def test_sync_players_dry_run_does_not_write(tmp_path):
    """Dry-run must not modify Colors.ini."""
    controls = "[005]\nP1_BUTTON1=1\nP2_BUTTON1=1\n"
    colors = "[005]\nP1_BUTTON1=Red\n"
    cfg = _write_sync_fixtures(tmp_path, controls, colors)
    original = (tmp_path / "Colors.ini").read_text(encoding="utf-8")

    result = sync_player_colors(cfg, dry_run=True, backup=False)

    assert result.dry_run is True
    assert result.roms_updated == 1  # would update
    assert (tmp_path / "Colors.ini").read_text(encoding="utf-8") == original


def test_sync_players_multiple_roms(tmp_path):
    """All ROMs with missing player keys are updated in one pass."""
    controls = (
        "[005]\nP1_BUTTON1=1\nP2_BUTTON1=1\n"
        "[1942]\nP1_BUTTON1=1\nP1_BUTTON2=1\nP2_BUTTON1=1\nP2_BUTTON2=1\n"
        "[pacman]\nP1_JOYSTICK=1\n"  # single-player — no P2 keys
    )
    colors = (
        "[005]\nP1_BUTTON1=Red\n"
        "[1942]\nP1_BUTTON1=Blue\nP1_BUTTON2=Yellow\n"
        "[pacman]\nP1_JOYSTICK=White\n"
    )
    cfg = _write_sync_fixtures(tmp_path, controls, colors)
    result = sync_player_colors(cfg, dry_run=False, backup=False)

    assert result.roms_updated == 2
    assert result.keys_added == 3  # 1 for 005, 2 for 1942
    text = (tmp_path / "Colors.ini").read_text(encoding="utf-8")
    assert "P2_BUTTON1=Red" in text    # 005
    assert "P2_BUTTON1=Blue" in text   # 1942
    assert "P2_BUTTON2=Yellow" in text  # 1942
    # pacman: single-player — no P2 keys in controls.ini so counted as no-controls-entry
    assert result.roms_skipped_no_controls >= 1


def test_sync_players_case_insensitive_rom_matching(tmp_path):
    """ROM name matching between controls.ini and Colors.ini is case-insensitive."""
    controls = "[MyCabinetGame]\nP1_BUTTON1=1\nP2_BUTTON1=1\n"
    colors = "[mycabinetgame]\nP1_BUTTON1=Purple\n"
    cfg = _write_sync_fixtures(tmp_path, controls, colors)
    result = sync_player_colors(cfg, dry_run=False, backup=False)

    assert result.roms_updated == 1
    text = (tmp_path / "Colors.ini").read_text(encoding="utf-8")
    assert "P2_BUTTON1=Purple" in text
