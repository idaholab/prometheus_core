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

"""Rules about the code base itself."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "platformctl"
"""The `platformctl` package folder."""


def test_no_pragma_no_cover_anywhere():
    """The only allowed exclusion is `if __name__ == "__main__":` (in pyproject's coverage config)."""
    offenders = [
        f"{path.relative_to(PACKAGE)}:{number}"
        for path in PACKAGE.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "pragma: no cover" in line or "pragma:no cover" in line
    ]
    assert offenders == []


def test_only_the_runner_starts_subprocesses():
    """Design: only system/runner.py starts subprocesses."""
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if path.name != "runner.py" and ("import subprocess" in path.read_text() or "os.system" in path.read_text())
    ]
    assert offenders == []


UNIT = Path(__file__).resolve().parent
"""The unit tests folder."""

CROSS_CUTTING = {"test_rules.py", "test_docstrings.py", "test_secrets_canary.py", "test_live_option.py"}
"""Tests that cover the whole tool rather than one module."""


def expected_test_for(source: Path) -> Path:
    """The unit test file that mirrors a source module: `system/compose.py` -> `system/test_compose.py`."""
    relative = source.relative_to(PACKAGE)
    name = {"__init__": "init", "__main__": "main"}.get(relative.stem, relative.stem)
    return UNIT / relative.parent / f"test_{name}.py"


def defines_code(source: Path) -> bool:
    """Whether a module defines a function or class (a docstring-only `__init__.py` needs no test)."""
    return any(isinstance(node, (ast.FunctionDef, ast.ClassDef)) for node in ast.parse(source.read_text()).body)


def test_every_module_with_code_has_a_test_file_at_the_mirrored_path():
    """`platformctl/system/compose.py` is tested in `tests/unit/system/test_compose.py`."""
    missing = [
        str(source.relative_to(PACKAGE))
        for source in PACKAGE.rglob("*.py")
        if defines_code(source) and not expected_test_for(source).exists()
    ]
    assert missing == []


def test_every_test_file_mirrors_a_module_or_is_cross_cutting():
    """No test file sits where no module could own it."""
    expected = {expected_test_for(source) for source in PACKAGE.rglob("*.py")}
    orphans = [
        str(test.relative_to(UNIT))
        for test in UNIT.rglob("test_*.py")
        if test not in expected and test.name not in CROSS_CUTTING
    ]
    assert orphans == []


def test_the_standard_library_is_the_only_runtime_dependency():
    """The package declares no runtime dependencies, so running the platform needs only Python."""
    # No tomllib: it needs Python 3.11 and the tests run on 3.10.
    text = (PACKAGE.parent / "pyproject.toml").read_text()
    assert "\ndependencies = []\n" in text
