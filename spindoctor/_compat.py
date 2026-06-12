"""Stdlib polyfills for the Python 3.8 floor (Win 7 cabinet target).

A handful of stdlib niceties we rely on (``ET.indent``, ``ast.unparse``)
landed in 3.9. The Windows binaries are still built against 3.8.10 — see
the note in setup.py — so these shims keep the same call sites working
on both versions without scattering try/excepts through the codebase.
"""
from __future__ import annotations

import ast
import sys
import xml.etree.ElementTree as ET
from typing import Optional, Union


class _SafeWriter:
    """Wraps a text IO stream; silently drops OSError on write/flush.

    Windows 7 + PCLauncher: ``SetConsoleOutputCP(65001)`` can leave the
    console handle in a state where every subsequent write raises
    ``PermissionError`` (WinError 31 — ERROR_GEN_FAILURE).  Without this
    wrapper the standalone wheel tools crash at their very first
    ``print()`` call.  All other stream attributes are proxied to the
    underlying stream unchanged.
    """

    def __init__(self, wrapped: object) -> None:
        object.__setattr__(self, "_w", wrapped)

    def write(self, s: str) -> int:
        try:
            return object.__getattribute__(self, "_w").write(s)  # type: ignore[union-attr]
        except OSError:
            return len(s)

    def flush(self) -> None:
        try:
            object.__getattribute__(self, "_w").flush()  # type: ignore[union-attr]
        except OSError:
            pass

    def __getattr__(self, name: str) -> object:
        return getattr(object.__getattribute__(self, "_w"), name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(object.__getattribute__(self, "_w"), name, value)


def enable_windows_utf8_console() -> None:
    """Switch the process's stdio to UTF-8 on Windows; no-op elsewhere.

    The Win 7 cabinet's default console codepage (cp437 / cp1252) can't
    encode the glyphs SpinDoctor prints — tree marks (``✓ ⚠ ✗``), em-dashes,
    ellipses, middle dots — and a frozen PyInstaller exe crashes mid-render
    when it tries.  Setting the console output codepage to 65001 and
    reconfiguring the text streams with ``errors="replace"`` fixes that.

    The main CLI has always done this at import time; the standalone wheel
    tools (``spindoctor-fav`` / ``-recent`` / ``-stats``) are separate frozen
    binaries that don't import the CLI module, so they must call this
    themselves before printing.  Idempotent and failure-tolerant: a
    redirected pipe, a missing ``kernel32``, or a stream without
    ``reconfigure`` just falls through harmlessly.

    After reconfiguring, each stream is wrapped with :class:`_SafeWriter` so
    that any subsequent write/flush that still raises ``OSError`` (e.g. the
    WinError 31 console-handle failure that PCLauncher triggers on Windows 7
    after a ``SetConsoleOutputCP(65001)`` call) is silently swallowed rather
    than crashing the process.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except (AttributeError, OSError):
        pass
    for _attr in ("stdout", "stderr"):
        _stream = getattr(sys, _attr)
        if isinstance(_stream, _SafeWriter):
            continue
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
        setattr(sys, _attr, _SafeWriter(_stream))


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
            last_child: Optional[ET.Element] = None
            for child in elem:
                _walk(child, level + 1)
                last_child = child
            if last_child is not None and (
                not last_child.tail or not last_child.tail.strip()
            ):
                last_child.tail = i
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
