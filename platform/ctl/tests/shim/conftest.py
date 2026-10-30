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

"""Options for the shim tests."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--shim-shell",
        default="sh",
        help="The shell that runs the shim (for example dash, 'bash --posix', ksh). Default: sh",
    )


@pytest.fixture(scope="session")
def shim_shell(pytestconfig: pytest.Config) -> list[str]:
    import shlex

    return shlex.split(pytestconfig.getoption("--shim-shell"))
