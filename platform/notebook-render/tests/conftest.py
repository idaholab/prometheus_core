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

"""Set the sentinel secret before ``proxy`` is imported.

``proxy`` reads AGENT_SECRET at import time into a module constant, so the env
var must be present before the first import that pytest collection triggers.
"""

import os
import sys
from pathlib import Path

# The sentinel we assert never leaks into any /rerun response body. Assigned, not
# setdefault: a developer shell that exports a real AGENT_SECRET would otherwise
# win, failing the test and printing the real secret in the assertion message.
os.environ["AGENT_SECRET"] = "sentinel-secret-do-not-leak"
os.environ.setdefault("RERUN_ROUTE", "direct")

# Make ``import proxy`` resolve to notebook-render/proxy.py.
NOTEBOOK_RENDER_DIR = Path(__file__).resolve().parents[1]
if str(NOTEBOOK_RENDER_DIR) not in sys.path:
    sys.path.insert(0, str(NOTEBOOK_RENDER_DIR))
