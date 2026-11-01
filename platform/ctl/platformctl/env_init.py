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

"""The file work of `config init`: create `.env` from `.env.example` and fill the blank secrets.

Ported from `scripts/init_env.py`. Values that are already set are never touched.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from platformctl.output import Output
from platformctl.system import envfile
from platformctl.system.runner import Runner


class GenerateError(RuntimeError):
    """A secret's generator one-liner failed. The message names the key, never the output."""


def write_env(env: Path, output: Output, values: dict[str, str]) -> None:
    """Write values into `.env`, first making it owner-only if it was readable by others (and saying so).

    A `.env` is created 0600, but one made by hand or by an old checkout may be 0644, and a rewrite keeps
    the mode. These commands add secrets, so the file is tightened before they do, not left for `doctor` to flag.
    """
    if (old := envfile.make_private(env)) is not None:
        output.warn(f"{env.name} was readable by other users (mode {old:04o}); it is now owner-only (0600).")
    envfile.update(env, values)


def create(example: Path, env: Path) -> bool:
    """Copy `.env.example` to `.env` if there is no `.env`; return whether it was created.

    The copy is owner-only before any secret is written to it, and later rewrites keep that mode.
    An existing `.env` is left as it is.
    """
    if env.exists():
        return False
    shutil.copyfile(example, env)
    env.chmod(0o600)
    return True


def generate_secret(runner: Runner, key: str, code: str) -> str:
    """Run one `python3 -c` one-liner from `.env.example` and return what it prints."""
    done = runner.run([sys.executable, "-c", code], timeout=30)
    value = done.stdout.strip()
    if not done.ok or not value:
        raise GenerateError(f"the generator for {key} in .env.example failed")
    return value


def fill_secrets(runner: Runner, example: str, current: dict[str, str]) -> dict[str, str]:
    """The generated value of every secret the example has a one-liner for and `current` leaves blank."""
    return {
        key: generate_secret(runner, key, code)
        for key, code in envfile.generators(example).items()
        if not current.get(key, "")
    }
