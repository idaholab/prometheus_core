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

"""Every function, global and class variable has its own brief docstring, in the code and in the tests.

A function's docstring is the first statement of its body. A variable's docstring is a string
literal on the line after its assignment, which is how dataclass fields and module globals are
documented:

    @dataclass
    class Result:
        status: str
        \"\"\"PASS, WARN, FAIL or SKIP.\"\"\"

Lambdas, `__all__`, and names inside a function body are exempt: a lambda has no place for one, and
a local variable is documented by its code.
"""

from __future__ import annotations

import ast
from pathlib import Path

CTL = Path(__file__).resolve().parents[2]
"""The `platform/ctl` folder."""
SOURCES = [*sorted((CTL / "platformctl").rglob("*.py")), *sorted((CTL / "tests").rglob("*.py")), CTL / "run.py"]
"""Every Python file the rule covers: the package, the tests and `run.py`."""
EXEMPT_NAMES = {"__all__", "__slots__", "pytestmark"}
"""Names Python or pytest read by name, which carry no documentation of their own."""


def is_docstring(node: ast.stmt) -> bool:
    """Whether a statement is a bare string literal, the shape of a docstring."""
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def assigned_names(node: ast.stmt) -> list[str]:
    """The names an assignment statement defines, or an empty list for any other statement."""
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


CLASS_VARIABLES = False
"""Whether variables in a class body (dataclass fields, class attributes) need a docstring."""


def missing_in(body: list[ast.stmt], where: str, in_class: bool = False) -> list[str]:
    """The undocumented functions and variables of one module or class body, recursing into classes."""
    missing: list[str] = []
    for index, node in enumerate(body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node) is None:
                missing.append(f"{where}:{node.lineno} def {node.name}")
        elif isinstance(node, ast.ClassDef):
            if ast.get_docstring(node) is None:
                missing.append(f"{where}:{node.lineno} class {node.name}")
            missing += missing_in(node.body, where, in_class=True)
        elif isinstance(node, ast.If):
            # `if TYPE_CHECKING:` and `if __name__ == ...:` blocks hold module-level names too
            missing += missing_in(node.body + node.orelse, where, in_class)
        elif in_class and not CLASS_VARIABLES:
            continue
        else:
            names = [n for n in assigned_names(node) if n not in EXEMPT_NAMES]
            following = body[index + 1] if index + 1 < len(body) else None
            if names and not (following is not None and is_docstring(following)):
                missing.append(f"{where}:{node.lineno} {', '.join(names)}")
    return missing


def undocumented(path: Path) -> list[str]:
    """Everything in one file that lacks a docstring."""
    tree = ast.parse(path.read_text())
    where = str(path.relative_to(CTL))
    found = missing_in(tree.body, where)
    # Functions nested in functions (fixtures that return a closure, helpers) count too
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.iter_child_nodes(node):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(inner) is None:
                    found.append(f"{where}:{inner.lineno} def {inner.name} (inside {node.name})")
    return found


def test_every_function_and_variable_has_a_docstring():
    """The rule applies to the package, to run.py and to every test."""
    found = [line for path in SOURCES for line in undocumented(path)]
    assert found == [], f"{len(found)} without a docstring:\n" + "\n".join(found)


def test_the_checker_finds_what_it_should():
    """A file with one of each undocumented thing is reported, and a documented one is not."""
    bad = ast.parse(
        "X = 1\ndef f():\n    pass\nclass C:\n    y: int\n    def m(self):\n        pass\nif True:\n    Z = 2\n"
    )
    good = ast.parse(
        'X = 1\n"""An X."""\n'
        'def f():\n    """An f."""\n'
        'class C:\n    """A C."""\n    y: int\n    """A y."""\n'
        '    def m(self):\n        """An m."""\n'
        'if True:\n    Z = 2\n    """A Z."""\n'
        "__all__ = []\n"
    )
    names = [m.split(" ", 1)[1] for m in missing_in(bad.body, "bad")]
    assert names == (
        ["X", "def f", "class C", "y", "def m", "Z"] if CLASS_VARIABLES else ["X", "def f", "class C", "def m", "Z"]
    )
    assert missing_in(good.body, "good") == []
