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

"""The three `scripts/*.py` stubs forward to commands that exist, with options that exist.

The stubs' own tests (`tests/infrastructure/test_script_stubs.py`) run them against a fake shim that
only echoes its arguments, so they would pass after a rename of `--no-start` or `--wait`. This test feeds
the same argument lists to the real parser, which is what the hackathon decks' commands end up calling.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from platformctl import cli

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
"""The platform's `scripts/` folder."""


def load(name: str):
    """Import a stub by path, without running it (its work is under `__main__`)."""
    spec = importlib.util.spec_from_file_location(f"stub_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("stub", "extra"),
    [
        ("init_env", []),
        ("check_platform", []),
        ("check_platform", ["--timeout", "42"]),
        ("deeplynx_setup", []),
        ("deeplynx_setup", ["--timeout", "9"]),
    ],
)
def test_the_argv_a_stub_forwards_is_accepted_by_the_real_parser(stub, extra):
    """`COMMAND` plus the carried-over `--timeout` parses, and reaches the action it names."""
    module = load(stub)
    args = cli.build_parser().parse_args([*module.COMMAND, *extra])
    assert args.command == module.COMMAND[0]
    assert callable(args._run)


def test_the_stubs_forward_the_option_names_the_parser_defines():
    """The options the stubs add (`--no-start`, `--timeout`, `--wait`) are the parser's, not a copy that can drift."""
    parser = cli.build_parser()
    deeplynx = parser.parse_args([*load("deeplynx_setup").COMMAND, "--timeout", "9"])
    assert (deeplynx.no_start, deeplynx.timeout) == (True, 9.0)
    status = parser.parse_args([*load("check_platform").COMMAND, "--timeout", "42"])
    assert (status.wait, status.timeout) == (True, 42.0)
