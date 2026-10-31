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

"""Moved: run ``./platformctl deeplynx setup``. This stub forwards to it and is removed in step 3c.

The old script ran after the DeepLynx containers were up, so the stub passes ``--no-start``. The old
``--timeout`` is kept; ``--port`` is now the ``DEEPLYNX_SERVER_PORT`` setting and is ignored.
"""

import os
import sys
from pathlib import Path

SHIM = Path(__file__).resolve().parent.parent / "platformctl"
COMMAND = ["deeplynx", "setup", "--no-start"]


def timeout(argv):
    """The value of --timeout in the old arguments, in either form, or None."""
    for i, arg in enumerate(argv):
        if arg == "--timeout" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--timeout="):
            return arg.partition("=")[2]
    return None


if __name__ == "__main__":
    seconds = timeout(sys.argv[1:])
    command = COMMAND + (["--timeout", seconds] if seconds else [])
    print(f"moved: run `./platformctl {' '.join(command[:2])}`", file=sys.stderr)
    sys.stderr.flush()
    os.execv("/bin/sh", ["sh", str(SHIM), *command])
