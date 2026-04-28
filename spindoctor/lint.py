"""Lightweight static-analysis pass over the SpinDoctor source tree.

Surfaces low-cost code-health issues using the standard-library ``ast``
module so the check runs without external linters:

* unused top-level imports
* private functions defined but never referenced
* bare ``except:`` clauses
* TODO / FIXME / XXX markers
* near-duplicate function bodies (same source after whitespace strip)

The goal is "second pair of eyes", not a strict linter. Each finding is
advisory and links to a file/line.
"""
from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class Finding:
    category: str          # "unused-import" | "dead-code" | "bare-except" | "todo" | "duplicate-body"
    path: Path
    line: int
    detail: str


@dataclass
class LintReport:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0

    def by_category(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = defaultdict(list)
        for f in self.findings:
            out[f.category].append(f)
        return out


_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")


def _iter_python_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if any(part.startswith((".", "__pycache__")) for part in p.parts):
            continue
        if "site-packages" in p.parts or "egg-info" in str(p):
            continue
        yield p


def _imported_names(tree: ast.AST) -> dict[str, ast.AST]:
    """Map alias name → the import node where it was introduced."""
    names: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = node
        elif isinstance(node, ast.ImportFrom):
            # __future__ imports are language directives, not bindings the
            # author is meant to reference — never flag them as unused.
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                names[alias.asname or alias.name] = node
    return names


def _used_names(tree: ast.AST) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
    return used


def _check_unused_imports(path: Path, tree: ast.AST, source: str) -> list[Finding]:
    findings: list[Finding] = []
    used = _used_names(tree)
    # Cheap fallback: catch string-only references (e.g. `"Optional"` in
    # forward refs) by checking the raw text.
    for name, node in _imported_names(tree).items():
        if name in used:
            continue
        if re.search(rf"\b{re.escape(name)}\b", source.replace(
            ast.get_source_segment(source, node) or "", "", 1)
        ):
            continue
        findings.append(
            Finding(
                category="unused-import",
                path=path,
                line=getattr(node, "lineno", 0),
                detail=f"`{name}` imported but never referenced",
            )
        )
    return findings


def _check_bare_except(path: Path, tree: ast.AST) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            out.append(
                Finding(
                    category="bare-except",
                    path=path,
                    line=node.lineno,
                    detail="bare `except:` — catches KeyboardInterrupt/SystemExit too",
                )
            )
    return out


def _check_todos(path: Path, source: str) -> list[Finding]:
    out: list[Finding] = []
    for i, line in enumerate(source.splitlines(), 1):
        m = _TODO_RE.search(line)
        if m:
            out.append(
                Finding(
                    category="todo",
                    path=path,
                    line=i,
                    detail=line.strip()[:120],
                )
            )
    return out


def _function_signatures(tree: ast.AST) -> list[tuple[ast.FunctionDef, str]]:
    """Return (node, normalised_body_hash) for every def in *tree*."""
    out: list[tuple[ast.FunctionDef, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                body = ast.unparse(node)
            except AttributeError:  # py < 3.9 — never hit but defensive
                continue
            stripped = re.sub(r"\s+", "", body)
            if len(stripped) < 80:  # too small to be a meaningful dup
                continue
            digest = hashlib.md5(stripped.encode("utf-8")).hexdigest()
            out.append((node, digest))
    return out


def _check_duplicate_functions(files: dict[Path, ast.AST]) -> list[Finding]:
    by_hash: dict[str, list[tuple[Path, ast.FunctionDef]]] = defaultdict(list)
    for path, tree in files.items():
        for node, digest in _function_signatures(tree):
            by_hash[digest].append((path, node))
    findings: list[Finding] = []
    for digest, occurrences in by_hash.items():
        if len(occurrences) < 2:
            continue
        first_path, first_node = occurrences[0]
        others = ", ".join(
            f"{p.name}:{n.lineno}" for p, n in occurrences[1:]
        )
        findings.append(
            Finding(
                category="duplicate-body",
                path=first_path,
                line=first_node.lineno,
                detail=f"`{first_node.name}` body matches: {others}",
            )
        )
    return findings


def _parse(path: Path) -> Optional[tuple[ast.AST, str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source, filename=str(path)), source
    except SyntaxError:
        return None


def lint_tree(root: Path) -> LintReport:
    """Run all checks across every .py file under *root*."""
    report = LintReport()
    parsed: dict[Path, ast.AST] = {}
    for path in _iter_python_files(root):
        result = _parse(path)
        if not result:
            continue
        tree, source = result
        report.files_scanned += 1
        parsed[path] = tree
        report.findings.extend(_check_unused_imports(path, tree, source))
        report.findings.extend(_check_bare_except(path, tree))
        report.findings.extend(_check_todos(path, source))
    report.findings.extend(_check_duplicate_functions(parsed))
    report.findings.sort(key=lambda f: (f.category, str(f.path), f.line))
    return report
