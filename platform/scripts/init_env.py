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

"""Moved: run ``./platformctl config init``. This stub forwards to it and is removed in step 3c."""

import os
import sys
from pathlib import Path

SHIM = Path(__file__).resolve().parent.parent / "platformctl"
COMMAND = ["config", "init"]

if __name__ == "__main__":
    print(f"moved: run `./platformctl {' '.join(COMMAND)}`", file=sys.stderr)
    sys.stderr.flush()
    os.execv("/bin/sh", ["sh", str(SHIM), *COMMAND])
