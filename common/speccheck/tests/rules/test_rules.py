# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Rules about the code base itself, as in platformctl.

- every function, global and class variable has its own brief docstring, in the code and the tests;
- every module with code has a test file at the mirrored path;
- every new `.py` file carries the copyright header;
- no `pragma: no cover`;
- only `cli.py` exits, and only `results.py`, `summary.py` and `actions/report.py` write files.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
"""common/speccheck."""
PACKAGE = ROOT / "speccheck"
"""The package."""
TESTS = ROOT / "tests"
"""The tests."""
UNIT = TESTS / "unit"
"""The unit tests, which mirror the package."""
SOURCES = [*sorted(PACKAGE.rglob("*.py")), *sorted(TESTS.rglob("*.py"))]
"""Every Python file the rules cover."""
EXEMPT_NAMES = {"__all__", "__slots__", "pytestmark"}
"""Names Python or pytest read by name, which carry no documentation of their own."""
HEADER = "# SPDX-License-Identifier: MIT"
"""The last line of the copyright header every file starts with."""


def is_docstring(node: ast.stmt) -> bool:
    """Whether a statement is a bare string literal, the shape of a docstring."""
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def assigned_names(node: ast.stmt) -> list[str]:
    """The names an assignment statement defines."""
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def missing_in(body: list[ast.stmt], where: str) -> list[str]:
    """The undocumented functions and variables of one module or class body, recursing into classes."""
    missing: list[str] = []
    for index, node in enumerate(body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node) is None:
                missing.append(f"{where}:{node.lineno} def {node.name}")
        elif isinstance(node, ast.ClassDef):
            if ast.get_docstring(node) is None:
                missing.append(f"{where}:{node.lineno} class {node.name}")
            missing += missing_in(node.body, where)
        elif isinstance(node, ast.If):
            missing += missing_in(node.body + node.orelse, where)
        else:
            names = [n for n in assigned_names(node) if n not in EXEMPT_NAMES]
            following = body[index + 1] if index + 1 < len(body) else None
            if names and not (following is not None and is_docstring(following)):
                missing.append(f"{where}:{node.lineno} {', '.join(names)}")
    return missing


def undocumented(path: Path) -> list[str]:
    """Everything in one file that lacks a docstring, including functions nested in functions."""
    tree = ast.parse(path.read_text())
    where = str(path.relative_to(ROOT))
    found = missing_in(tree.body, where)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.iter_child_nodes(node):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(inner) is None:
                    found.append(f"{where}:{inner.lineno} def {inner.name} (inside {node.name})")
    return found


def test_every_function_and_variable_has_a_docstring():
    """The rule covers the package and every test."""
    found = [line for path in SOURCES for line in undocumented(path)]
    assert found == [], f"{len(found)} without a docstring:\n" + "\n".join(found)


def test_the_docstring_checker_finds_what_it_should():
    """One of each undocumented thing is reported, and a documented one is not."""
    bad = ast.parse(
        "X = 1\ndef f():\n    pass\nclass C:\n    y: int\n    def m(self):\n        pass\nif True:\n    Z = 2\n"
    )
    good = ast.parse(
        'X = 1\n"""An X."""\ndef f():\n    """An f."""\nclass C:\n    """A C."""\n    y: int\n    """A y."""\n'
        '    def m(self):\n        """An m."""\nif True:\n    Z = 2\n    """A Z."""\n__all__ = []\n'
    )
    assert [m.split(" ", 1)[1] for m in missing_in(bad.body, "bad")] == ["X", "def f", "class C", "y", "def m", "Z"]
    assert missing_in(good.body, "good") == []


def expected_test_for(source: Path) -> Path:
    """The test file that mirrors a module: `actions/check.py` -> `tests/unit/actions/test_check.py`."""
    relative = source.relative_to(PACKAGE)
    name = {"__init__": "init", "__main__": "main"}.get(relative.stem, relative.stem.lstrip("_"))
    return UNIT / relative.parent / f"test_{name}.py"


def defines_code(source: Path) -> bool:
    """Whether a module defines a function or class (a docstring-only module needs no test file)."""
    return any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) for n in ast.parse(source.read_text()).body)


def test_tests_mirror_the_code():
    """Every module with code has its test file, and every test file has its module."""
    missing = [
        str(expected_test_for(p).relative_to(ROOT))
        for p in PACKAGE.rglob("*.py")
        if defines_code(p) and not expected_test_for(p).is_file()
    ]
    assert missing == [], "missing test files: " + ", ".join(missing)
    sources = {expected_test_for(p) for p in PACKAGE.rglob("*.py")}
    orphans = [str(t.relative_to(ROOT)) for t in UNIT.rglob("test_*.py") if t not in sources]
    assert orphans == [], "test files with no module: " + ", ".join(orphans)


def test_every_file_has_the_copyright_header():
    """The same header as the rest of the repository."""
    missing = [str(p.relative_to(ROOT)) for p in SOURCES if HEADER not in p.read_text().splitlines()[:12]]
    assert missing == []


def test_no_pragma_no_cover():
    """The only coverage exclusion is `if __name__ == "__main__":`, in pyproject.toml."""
    offenders = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in PACKAGE.rglob("*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if "pragma: no cover" in line
    ]
    assert offenders == []


def test_requirements_tests_mirror_the_specs():
    """One requirements test file per spec, named after it: specs/004-results-files.md -> test_004_results_files.py."""
    specs = {
        p.stem.replace("-", "_") for p in (ROOT / "specs").glob("[0-9][0-9][0-9]-*.md") if not p.name.startswith("000")
    }
    tests = {p.stem[len("test_") :] for p in (TESTS / "requirements").glob("test_*.py")}
    assert tests == specs


def test_only_the_cli_exits_and_only_three_modules_write():
    """Actions return a code; files are written only by results.py, summary.py and the report action."""
    exits, writes = [], []
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text()
        name = str(path.relative_to(PACKAGE))
        if ("sys.exit" in text or "raise SystemExit" in text) and name not in ("cli.py", "__main__.py"):
            exits.append(name)
        if any(w in text for w in ('open("w"', 'open("a"', ".write_text(", "mkstemp")) and name not in (
            "results.py",
            "summary.py",
            "actions/report.py",
        ):
            writes.append(name)
    assert (exits, writes) == ([], [])
