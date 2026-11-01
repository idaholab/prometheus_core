#!/usr/bin/env python3
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

"""Moved: run ``./platformctl status --wait``. This stub forwards to it and is removed in step 3c.

The old ``--timeout`` is kept. The ports and agent folders it took are now read from the settings
and the generated agents file, so they are ignored.
"""

import os
import sys
from pathlib import Path

SHIM = Path(__file__).resolve().parent.parent / "platformctl"
COMMAND = ["status", "--wait"]


def split(argv):
    """The value of --timeout (either form, or None) and the other old arguments, which are not forwarded."""
    seconds, rest, skip = None, [], False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
        elif arg == "--timeout" and i + 1 < len(argv):
            seconds, skip = argv[i + 1], True
        elif arg.startswith("--timeout="):
            seconds = arg.partition("=")[2]
        else:
            rest.append(arg)
    return seconds, rest


if __name__ == "__main__":
    seconds, rest = split(sys.argv[1:])
    command = COMMAND + (["--timeout", seconds] if seconds else [])
    print(f"moved: run `./platformctl {' '.join(command)}`", file=sys.stderr)
    if rest:
        print(
            f"ignored: {' '.join(rest)} (the ports now come from .env and the agents from docker-compose.agents.yml)",
            file=sys.stderr,
        )
    sys.stderr.flush()
    os.execv("/bin/sh", ["sh", str(SHIM), *command])
