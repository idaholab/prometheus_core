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

"""platformctl's built-in knowledge (required keys, ports, defaults) matches the real files.

The tool keeps its own copy of what `.env.example`, the compose files and the Makefile say.
The platformctl workflow only runs for changes under `platform/ctl`, so a rename here would
otherwise go unnoticed until `doctor` failed a good `.env` or missed a busy port.
"""

import re
import sys
from pathlib import Path

import pytest

CTL = Path(__file__).resolve().parents[2] / "ctl"
"""The platformctl project folder."""


@pytest.fixture(scope="module")
def ctl():
    """The platformctl package, standard library only, imported from its folder."""
    sys.path.insert(0, str(CTL))
    try:
        from platformctl import config
        from platformctl.diagnostics import env_checks, host_checks
    finally:
        sys.path.remove(str(CTL))
    return config, env_checks, host_checks


@pytest.fixture(scope="module")
def compose_text(project_root: Path) -> str:
    """The text of every compose file at the platform root."""
    return "\n".join(path.read_text() for path in sorted(project_root.glob("docker-compose*.yml")))


@pytest.fixture(scope="module")
def makefile_text(project_root: Path) -> str:
    """The text of the Makefile."""
    return (project_root / "Makefile").read_text()


def test_every_required_key_is_in_env_example(ctl, env_example_vars):
    """`doctor` fails a `.env` that lacks a key `.env.example` no longer has."""
    _, env_checks, _ = ctl
    assert [key for key in env_checks.REQUIRED if key not in env_example_vars] == []


def test_the_port_settings_are_published_by_a_compose_file(ctl, compose_text):
    """Each port `ports-free` checks is a `${NAME:-port}:` mapping in a compose file."""
    config, _, host_checks = ctl
    names = [*(name for name, _ in host_checks.PLATFORM_PORTS), *host_checks.FRONTEND_PORTS.values()]
    unpublished = [name for name in names if not re.search(rf"\$\{{{name}:-\d+\}}:\d+", compose_text)]
    assert unpublished == []
    assert all(config.REGISTRY[name].kind == "int" for name in names)


@pytest.mark.parametrize(
    "name",
    [
        "BACKEND_PORT",
        "FRONTEND_DEV_PORT",
        "FRONTEND_PROD_PORT",
        "REDIS_LOCAL_PORT",
        "CLIENT_AGENT_PORT",
        "DEEPLYNX_SERVER_PORT",
        "DEEPLYNX_UI_PORT",
    ],
)
def test_port_defaults_match_compose_and_the_makefile(ctl, compose_text, makefile_text, name):
    """The default port in the tool's registry is the one in the compose file and the Makefile."""
    config, _, _ = ctl
    expected = config.REGISTRY[name].default
    found = {
        *re.findall(rf"\$\{{{name}:-(\d+)\}}", compose_text),
        *re.findall(rf"^{name}\s*\?=\s*(\d+)\s*$", makefile_text, re.MULTILINE),
    }
    assert found, f"{name} has no default in a compose file or the Makefile"
    assert found == {expected}


def test_profile_default_matches_the_makefile(ctl, makefile_text):
    """`PROFILE ?= dev` in the Makefile is the tool's default, and `dev`/`prod` are its frontend profiles."""
    config, _, host_checks = ctl
    assert re.search(rf"^PROFILE\s*\?=\s*{config.REGISTRY['PROFILE'].default}\s*$", makefile_text, re.MULTILINE)
    assert set(host_checks.FRONTEND_PORTS) == {"dev", "prod"}
