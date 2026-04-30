"""Stdlib polyfills for the Python 3.8 floor (Win 7 cabinet target).

A handful of stdlib niceties we rely on (``ET.indent``, ``ast.unparse``)
landed in 3.9. The Windows binaries are still built against 3.8.10 — see
the note in setup.py — so these shims keep the same call sites working
on both versions without scattering try/excepts through the codebase.
"""
from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from typing import Union


def et_indent(tree: Union[ET.ElementTree, ET.Element], space: str = "  ") -> None:
    """Pretty-print an ElementTree in place (``ET.indent`` polyfill)."""
    if hasattr(ET, "indent"):
        ET.indent(tree, space=space)
        return

    root = tree.getroot() if isinstance(tree, ET.ElementTree) else tree

    def _walk(elem: ET.Element, level: int = 0) -> None:
        i = "\n" + level * space
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + space
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for child in elem:
                _walk(child, level + 1)
            if not child.tail or not child.tail.strip():  # noqa: F821
                child.tail = i  # noqa: F821
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    _walk(root)


def ast_unparse(node: ast.AST) -> str:
    """Return source-equivalent text for *node* (``ast.unparse`` polyfill).

    On Python <3.9 we fall back to ``ast.dump``. The exact output differs
    from real ``unparse``, but every caller in this codebase only feeds the
    result to a hash for equivalence comparison, so consistency within a
    single interpreter run is all that matters.
    """
    if hasattr(ast, "unparse"):
        return ast.unparse(node)
    return ast.dump(node, annotate_fields=True, include_attributes=False)
