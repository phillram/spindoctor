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
