"""Lint module: AST-based code-health checks."""
from __future__ import annotations

from spindoctor.lint import lint_tree


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_unused_import_detected(tmp_path):
    _write(tmp_path / "mod.py", "import os\nimport sys\nprint(sys.argv)\n")
    report = lint_tree(tmp_path)
    cats = report.by_category()
    assert any("os" in f.detail for f in cats.get("unused-import", []))
    # `sys` IS used, must not be flagged
    assert all("`sys`" not in f.detail for f in cats.get("unused-import", []))


def test_bare_except_detected(tmp_path):
    _write(tmp_path / "mod.py", "try:\n    x = 1\nexcept:\n    pass\n")
    report = lint_tree(tmp_path)
    assert report.by_category().get("bare-except"), "expected a bare-except finding"


def test_todo_detected(tmp_path):
    _write(tmp_path / "mod.py", "# TODO: clean this up\nx = 1\n")
    report = lint_tree(tmp_path)
    todos = report.by_category().get("todo", [])
    assert any("TODO" in t.detail for t in todos)


def test_duplicate_function_bodies_detected(tmp_path):
    body = (
        "def compute_running_total(values):\n"
        "    accumulated = 0\n"
        "    for current_value in values:\n"
        "        accumulated += current_value * 2\n"
        "        accumulated -= current_value // 3\n"
        "    return accumulated * 1000\n"
    )
    _write(tmp_path / "a.py", body)
    _write(tmp_path / "c.py", body)
    report = lint_tree(tmp_path)
    assert report.by_category().get("duplicate-body"), \
        "expected duplicate-body finding for identical defs"


def test_files_scanned_count(tmp_path):
    _write(tmp_path / "a.py", "x = 1\n")
    _write(tmp_path / "b.py", "y = 2\n")
    report = lint_tree(tmp_path)
    assert report.files_scanned == 2
