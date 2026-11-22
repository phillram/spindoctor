"""Tests for the `doctor` **Keymapper hotkeys** check
(``health.check_keymapper_hotkeys``) and the profile reader behind it
(``spindoctor.keymapper_hotkeys``).

RocketLauncher's menu navigation keys replace plain hotkeys of the same name
in an Internal AHK keymapper profile, so ``w::`` never fires while ``*w::``
and remaps (``w::c``) do.
"""
from __future__ import annotations

import pytest

from spindoctor import health
from spindoctor.config import Config
from spindoctor.keymapper_hotkeys import navigation_keys, plain_hotkeys, replaced_hotkeys

NAVIGATION = (
    "[Navigation]\r\n"
    "Navigation_Up_Key=Up|8|W\r\n"
    "Navigation_Down_Key=Down|6|S\r\n"
    "Navigation_Left_Key=Left|7|A\r\n"
    "Navigation_Right_Key=Right|9|D\r\n"
    "Navigation_Select_Key=Enter|G\r\n"
    "Navigation_P2_Up_Key=N|Numpad8\r\n"
    "Navigation_P2_Down_Key=Q|Numpad0\r\n"
    "Navigation_P2_Left_Key=M|Numpad7\r\n"
    "Navigation_P2_Right_Key=O|Numpad9\r\n"
    "Navigation_P2_Select_Key=Enter|G\r\n"
)


def _rl(tmp_path, navigation=NAVIGATION, method="Internal", settings="Global RocketLauncher.ini"):
    rl = tmp_path / "RocketLauncher"
    settings_dir = rl / "Settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "RocketLauncher.ini").write_bytes(("[Settings]\r\n" + navigation).encode("utf-8"))
    (settings_dir / settings).write_text(f"[Keymapper]\r\nKeymapper_AHK_Method={method}\r\n", encoding="utf-8")
    (rl / "Profiles" / "AHK").mkdir(parents=True)
    return rl


def _profile(rl, name, text):
    path = rl / "Profiles" / "AHK" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _check(rl):
    return health.check_keymapper_hotkeys(Config(rocketlauncher_dir=str(rl)))


# ── the navigation keys ───────────────────────────────────────────────────────

def test_navigation_keys_split_on_the_bar_and_drop_combinations(tmp_path):
    rl = _rl(tmp_path, "[Navigation]\r\nNavigation_Up_Key=~Up|S & D|H2000:*8|Joy3\r\n")
    nav = navigation_keys(rl / "Settings")
    assert {"up", "8"} <= set(nav)
    assert "s & d" not in nav and "joy3" not in nav
    assert nav["up"] == ("Navigation_Up_Key", "~Up|S & D|H2000:*8|Joy3")


def test_missing_settings_fall_back_to_rocketlaunchers_own_keys(tmp_path):
    rl = _rl(tmp_path, "")
    nav = navigation_keys(rl / "Settings")
    assert {"up", "down", "left", "right", "enter", "numpadenter"} <= set(nav)


# ── the profile reader ────────────────────────────────────────────────────────

def test_plain_hotkeys_are_listed_with_line_numbers():
    text = "#MaxHotkeysPerInterval 200\r\n; w::not this\r\nw::\r\nreturn\r\n~r::return\r\n$x::Send y\r\n"
    assert [(h.line, h.key) for h in plain_hotkeys(text)] == [(3, "w"), (5, "r"), (6, "x")]


@pytest.mark.parametrize("line", [
    "*w::", "~*w::return", "!w::", "^+w::", "#w::", "w & x::", "w::c", "w::1", "W::LShift", "w::LButton", "~w::c",
    "d::delete", "f::PgDn", "e::end", "w::^c", "w::+", "w::SC01E", "w::Numpad5", "w::Volume_Up",
])
def test_wildcards_modifiers_combinations_and_remaps_are_not_plain(line):
    assert list(plain_hotkeys(line + "\r\n")) == []


def test_a_hotkey_inside_an_if_context_is_skipped():
    text = "#IfWinActive ahk_class Game\r\nw::\r\nreturn\r\n#IfWinActive\r\ns::\r\nreturn\r\n"
    assert [h.key for h in plain_hotkeys(text)] == ["s"]


def test_block_comments_are_skipped():
    assert list(plain_hotkeys("/*\r\nw::\r\n*/\r\n")) == []


@pytest.mark.parametrize("text, expected", [
    ("w::\r\nreturn\r\n", ["w"]),
    ("Return::\r\nreturn\r\n", ["enter"]),
    ("z::\r\nreturn\r\n", []),
    ("a::lshift\r\n", []),
    ("a::Send {Enter}{Space}\r\n", ["a"]),
    ("d::delete\r\n", []),
])
def test_replaced_hotkeys_match_navigation_keys(tmp_path, text, expected):
    nav = navigation_keys(_rl(tmp_path) / "Settings")
    assert [r.hotkey.key for r in replaced_hotkeys(text, nav)] == expected


# ── the doctor check ──────────────────────────────────────────────────────────

def test_a_plain_hotkey_on_a_navigation_key_warns(tmp_path):
    rl = _rl(tmp_path)
    _profile(rl, "Game.ahk", "a::lshift\r\nw::\r\nreturn\r\n")
    result = _check(rl)
    assert result.status == health.Status.WARN
    child = result.children[0]
    assert "line 2" in child.detail and "Navigation_Up_Key" in child.detail
    assert "*w::" in child.fix


def test_wildcards_and_remaps_are_fine(tmp_path):
    rl = _rl(tmp_path)
    _profile(rl, "Game.ahk", "a::lshift\r\n*w::\r\nreturn\r\n~*s::\r\nreturn\r\n")
    result = _check(rl)
    assert result.status == health.Status.OK


def test_profiles_are_grouped_by_wheel_and_counted(tmp_path):
    rl = _rl(tmp_path)
    for game in ("One", "Two", "Three", "Four"):
        _profile(rl, f"Pinball/{game}.ahk", "g::\r\nreturn\r\n")
    result = _check(rl)
    assert len(result.children) == 1
    assert result.children[0].detail.startswith("4 profiles: ")
    assert "and 1 more" in result.children[0].detail


def test_profiles_in_a_wheel_folder_are_read_with_the_wheel_name(tmp_path):
    rl = _rl(tmp_path)
    _profile(rl, "Pinball/Table One.ahk", "g::\r\nreturn\r\n")
    result = _check(rl)
    assert [c.name for c in result.children] == ["Pinball"]


def test_profiles_for_the_front_end_and_rocketlauncher_are_not_read(tmp_path):
    rl = _rl(tmp_path)
    _profile(rl, "HyperSpin.ahk", "w::\r\nreturn\r\n")
    _profile(rl, "RocketLauncher.ahk", "w::\r\nreturn\r\n")
    result = _check(rl)
    assert result.status == health.Status.INFO
    assert not result.children


def test_an_external_keymapper_is_not_checked(tmp_path):
    rl = _rl(tmp_path, method="External")
    _profile(rl, "Game.ahk", "w::\r\nreturn\r\n")
    result = _check(rl)
    assert result.status == health.Status.INFO


def test_no_keymapper_setting_is_not_checked(tmp_path):
    rl = _rl(tmp_path, method="false")
    _profile(rl, "Game.ahk", "w::\r\nreturn\r\n")
    assert _check(rl).status == health.Status.INFO


def test_a_wheels_own_setting_wins_over_the_global_one(tmp_path):
    rl = _rl(tmp_path, method="false")
    system = rl / "Settings" / "Arcade Pinball"
    system.mkdir()
    (system / "RocketLauncher.ini").write_text(
        "[Keymapper]\r\nKeymapper_AHK_Method=Internal\r\n", encoding="utf-8")
    _profile(rl, "Arcade Pinball.ahk", "w::\r\nreturn\r\n")
    _profile(rl, "Other.ahk", "w::\r\nreturn\r\n")
    result = _check(rl)
    assert [c.name for c in result.children] == ["Arcade Pinball"]


def test_without_a_rocketlauncher_folder_it_says_so():
    result = health.check_keymapper_hotkeys(Config())
    assert result.status == health.Status.INFO
    assert "not configured" in result.detail
