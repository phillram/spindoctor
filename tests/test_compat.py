"""Tests for the Python 3.8 polyfills in spindoctor._compat.

These exist because both polyfills are only exercised on 3.8 in
production but CI also runs on 3.12 — so without dedicated tests the
fallback paths never run and any regression in them ships silently.
"""
from __future__ import annotations

import ast
import xml.etree.ElementTree as ET

from spindoctor import _compat


# ─── et_indent ────────────────────────────────────────────────────────────────


def _build_tree() -> ET.ElementTree:
    root = ET.Element("menu")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "listname").text = "Demo"
    ET.SubElement(header, "lastlistupdate").text = "2025-01-01"
    g1 = ET.SubElement(root, "game", attrib={"name": "Pac-Man"})
    ET.SubElement(g1, "description").text = "Pac-Man"
    g2 = ET.SubElement(root, "game", attrib={"name": "Galaga"})
    ET.SubElement(g2, "description").text = "Galaga"
    return ET.ElementTree(root)


def test_et_indent_pretty_prints_tree():
    tree = _build_tree()
    _compat.et_indent(tree, space="  ")
    out = ET.tostring(tree.getroot(), encoding="unicode")
    # Each <game> child should sit on its own indented line.
    assert "\n  <game" in out
    # Inner-most elements indent two more levels.
    assert "\n    <description" in out


def test_et_indent_handles_empty_root():
    """An empty root must not raise — the F821 fix exercised this path."""
    tree = ET.ElementTree(ET.Element("menu"))
    _compat.et_indent(tree, space="  ")  # must not raise
    assert ET.tostring(tree.getroot(), encoding="unicode") == "<menu />"


def test_et_indent_works_with_fallback(monkeypatch):
    """Force the fallback path (no native ET.indent) and verify it works.

    On Python 3.9+ the polyfill normally returns immediately because
    ``hasattr(ET, "indent")`` is true. Stripping the attribute exercises
    the legacy walk that used to carry the noqa: F821 suppression.
    """
    monkeypatch.delattr(ET, "indent", raising=False)
    tree = _build_tree()
    _compat.et_indent(tree, space="  ")
    out = ET.tostring(tree.getroot(), encoding="unicode")
    assert "\n  <game" in out
    # Last child's tail should land on a fresh line for the closing
    # </menu> — this is exactly the path that used to rely on the
    # F821-suppressed `child.tail = i`.
    assert "</game>\n</menu>" in out


def test_et_indent_accepts_bare_element(monkeypatch):
    """et_indent also accepts a raw ET.Element (not just an ElementTree)."""
    monkeypatch.delattr(ET, "indent", raising=False)
    root = ET.Element("menu")
    child = ET.SubElement(root, "game")
    ET.SubElement(child, "leaf").text = "x"
    _compat.et_indent(root, space="  ")
    out = ET.tostring(root, encoding="unicode")
    assert "\n  <game>" in out


# ─── ast_unparse ──────────────────────────────────────────────────────────────


def test_ast_unparse_native_path():
    node = ast.parse("x = 1 + 2", mode="exec")
    out = _compat.ast_unparse(node)
    # Either native unparse or ast.dump — both are non-empty strings
    # and stable within a single interpreter run, which is all this
    # polyfill promises.
    assert isinstance(out, str) and out


def test_ast_unparse_fallback(monkeypatch):
    monkeypatch.delattr(ast, "unparse", raising=False)
    node = ast.parse("x = 1", mode="exec")
    out = _compat.ast_unparse(node)
    # Fallback uses ast.dump — output should contain the literal node names.
    assert "Module" in out
    assert "Assign" in out


# ─── enable_windows_utf8_console ──────────────────────────────────────────────


def test_enable_windows_utf8_console_noop_off_windows(monkeypatch):
    """Off Windows it must do nothing and never touch the streams."""
    monkeypatch.setattr(_compat.sys, "platform", "linux")
    # Should return cleanly without importing ctypes or reconfiguring stdout.
    _compat.enable_windows_utf8_console()


def test_enable_windows_utf8_console_reconfigures_on_windows(monkeypatch):
    """On Windows it sets the console codepage and reconfigures stdio."""
    monkeypatch.setattr(_compat.sys, "platform", "win32")
    calls = {"cp": None, "reconfigured": 0}

    class _FakeKernel:
        def SetConsoleOutputCP(self, cp):  # noqa: N802 - mirror WinAPI name
            calls["cp"] = cp

    class _FakeWindll:
        kernel32 = _FakeKernel()

    import types
    fake_ctypes = types.ModuleType("ctypes")
    fake_ctypes.windll = _FakeWindll()
    monkeypatch.setitem(__import__("sys").modules, "ctypes", fake_ctypes)

    class _FakeStream:
        def reconfigure(self, **kwargs):
            assert kwargs == {"encoding": "utf-8", "errors": "replace"}
            calls["reconfigured"] += 1

    monkeypatch.setattr(_compat.sys, "stdout", _FakeStream())
    monkeypatch.setattr(_compat.sys, "stderr", _FakeStream())

    _compat.enable_windows_utf8_console()
    assert calls["cp"] == 65001
    assert calls["reconfigured"] == 2


def test_enable_windows_utf8_console_tolerates_missing_reconfigure(monkeypatch):
    """A stream without reconfigure (or a kernel32 OSError) must not raise."""
    monkeypatch.setattr(_compat.sys, "platform", "win32")

    import types
    fake_ctypes = types.ModuleType("ctypes")

    class _Boom:
        def SetConsoleOutputCP(self, cp):  # noqa: N802
            raise OSError("no console")

    fake_ctypes.windll = types.SimpleNamespace(kernel32=_Boom())
    monkeypatch.setitem(__import__("sys").modules, "ctypes", fake_ctypes)

    # Plain objects: no reconfigure attribute → AttributeError, swallowed.
    monkeypatch.setattr(_compat.sys, "stdout", object())
    monkeypatch.setattr(_compat.sys, "stderr", object())
    _compat.enable_windows_utf8_console()  # must not raise


def test_enable_windows_utf8_console_wraps_with_safe_writer(monkeypatch):
    """After the call, sys.stdout/stderr should be _SafeWriter instances."""
    monkeypatch.setattr(_compat.sys, "platform", "win32")

    import types
    fake_ctypes = types.ModuleType("ctypes")
    fake_ctypes.windll = types.SimpleNamespace(
        kernel32=types.SimpleNamespace(SetConsoleOutputCP=lambda cp: None)
    )
    monkeypatch.setitem(__import__("sys").modules, "ctypes", fake_ctypes)

    class _FakeStream:
        def reconfigure(self, **kwargs):
            pass

    monkeypatch.setattr(_compat.sys, "stdout", _FakeStream())
    monkeypatch.setattr(_compat.sys, "stderr", _FakeStream())

    _compat.enable_windows_utf8_console()

    assert isinstance(_compat.sys.stdout, _compat._SafeWriter)
    assert isinstance(_compat.sys.stderr, _compat._SafeWriter)


def test_enable_windows_utf8_console_idempotent(monkeypatch):
    """Calling twice must not double-wrap the streams."""
    monkeypatch.setattr(_compat.sys, "platform", "win32")

    import types
    fake_ctypes = types.ModuleType("ctypes")
    fake_ctypes.windll = types.SimpleNamespace(
        kernel32=types.SimpleNamespace(SetConsoleOutputCP=lambda cp: None)
    )
    monkeypatch.setitem(__import__("sys").modules, "ctypes", fake_ctypes)

    class _FakeStream:
        def reconfigure(self, **kwargs):
            pass

    monkeypatch.setattr(_compat.sys, "stdout", _FakeStream())
    monkeypatch.setattr(_compat.sys, "stderr", _FakeStream())

    _compat.enable_windows_utf8_console()
    first = _compat.sys.stdout
    _compat.enable_windows_utf8_console()

    # Must be the same object — no double-wrap.
    assert _compat.sys.stdout is first
    assert not isinstance(first._w, _compat._SafeWriter)


# ─── _SafeWriter ──────────────────────────────────────────────────────────────


def test_safe_writer_write_swallows_os_error():
    """write() must return len(s) and not raise when the inner stream fails."""
    class _Broken:
        def write(self, s):
            raise PermissionError("WinError 31")
        def flush(self):
            pass

    writer = _compat._SafeWriter(_Broken())
    result = writer.write("hello")
    assert result == len("hello")


def test_safe_writer_flush_swallows_os_error():
    """flush() must silently swallow OSError."""
    class _Broken:
        def write(self, s):
            return len(s)
        def flush(self):
            raise PermissionError("WinError 31")

    writer = _compat._SafeWriter(_Broken())
    writer.flush()  # must not raise


def test_safe_writer_proxies_attrs():
    """Attributes not overridden by _SafeWriter are proxied to the inner stream."""
    class _Stream:
        encoding = "utf-8"
        def isatty(self):
            return True

    writer = _compat._SafeWriter(_Stream())
    assert writer.encoding == "utf-8"
    assert writer.isatty() is True


def test_safe_writer_successful_write_passes_through():
    """When the inner stream works normally, write() returns the real count."""
    buf = []

    class _Good:
        def write(self, s):
            buf.append(s)
            return len(s)
        def flush(self):
            pass

    writer = _compat._SafeWriter(_Good())
    result = writer.write("ok")
    assert result == 2
    assert buf == ["ok"]
