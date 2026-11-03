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
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_git_keeps_the_shim_lf_even_on_a_windows_checkout():
    """`#!/bin/sh\\r` is "bad interpreter" under WSL, before Python can explain; `.gitattributes` prevents it."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = PACKAGE.parents[2]
    done = subprocess.run(
        [git, "check-attr", "eol", "--", "platform/platformctl"], capture_output=True, text=True, cwd=repo, check=False
    )
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    assert done.stdout.strip() == "platform/platformctl: eol: lf"


@pytest.mark.parametrize(
    "path",
    ["platform/Makefile", "platform/.env.example", "platform/ctl/platformctl/cli.py", ".github/workflows/test.yml"]
    + ["platform/README.md", "platform/backend/Dockerfile", "platform/scripts/init_env.py"],
)
def test_git_keeps_the_files_a_unix_tool_parses_lf(path):
    """Make, the dotenv parsers and Docker read these as LF; a Windows checkout must not turn them into CRLF."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = PACKAGE.parents[2]
    done = subprocess.run([git, "check-attr", "eol", "--", path], capture_output=True, text=True, cwd=repo, check=False)
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    assert done.stdout.strip() == f"{path}: eol: lf"


CHECKED_OUT_AS_THEY_ARE = {"NOTICE.txt", "common/certs/INL.pem"}
"""Files committed with CRLF or mixed endings on purpose, which git must leave alone (`-text`, or binary-like)."""

PARSED_EXTENSIONS = {".py", ".sh", ".md", ".yml", ".yaml", ".toml", ".lock", ".json", ".sample", ".example"}
"""Extensions of files a tool parses, so a checkout with CRLF would break them."""

PARSED_NAMES = {"Makefile", "Dockerfile", ".python-version", ".dockerignore", ".gitignore"}
"""Names (no useful extension) of files a tool parses."""


def test_no_parsed_file_would_be_checked_out_with_crlf():
    """With `core.autocrlf=true` (Windows git, or a WSL checkout on `/mnt/c`), a file with no `eol` rule becomes CRLF.

    This lists every tracked file a tool parses and asks git which line ending it would check out, instead of
    naming a few paths: `.python-version` as "3.12\\r" breaks uv, and a CRLF `.dockerignore` stops matching.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = PACKAGE.parents[2]
    listed = subprocess.run([git, "ls-files", "-z"], capture_output=True, cwd=repo, check=False)
    if listed.returncode != 0:
        pytest.skip("not a git checkout")
    files = [name for name in listed.stdout.decode().split("\0") if name and name not in CHECKED_OUT_AS_THEY_ARE]
    parsed = [
        name
        for name in files
        if Path(name).suffix in PARSED_EXTENSIONS
        or Path(name).name in PARSED_NAMES
        or Path(name).name.startswith(("Dockerfile.", ".env."))
    ]
    attrs = subprocess.run(
        [git, "check-attr", "-z", "--stdin", "eol"],
        input="\0".join(parsed).encode(),
        capture_output=True,
        cwd=repo,
        check=True,
    )
    fields = attrs.stdout.decode().split("\0")
    eol = {fields[i]: fields[i + 2] for i in range(0, len(fields) - 2, 3)}
    assert parsed, "found no files to check"
    assert [name for name in parsed if eol.get(name) != "lf"] == []


def test_git_leaves_notice_txt_exactly_as_committed():
    """`NOTICE.txt` is committed with CRLF and a byte-order mark: `-text` keeps git from touching either."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = PACKAGE.parents[2]
    done = subprocess.run(
        [git, "check-attr", "text", "--", "NOTICE.txt"], capture_output=True, text=True, cwd=repo, check=False
    )
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    assert done.stdout.strip() == "NOTICE.txt: text: unset"


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

CROSS_CUTTING = {
    "test_rules.py",
    "test_docstrings.py",
    "test_secrets_canary.py",
    "test_live_option.py",
    "test_script_stubs_match_the_cli.py",
}
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
