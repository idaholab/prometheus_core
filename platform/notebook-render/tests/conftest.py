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

"""Make ``import proxy`` resolve to notebook-render/proxy.py."""

import sys
from pathlib import Path

NOTEBOOK_RENDER_DIR = Path(__file__).resolve().parents[1]
if str(NOTEBOOK_RENDER_DIR) not in sys.path:
    sys.path.insert(0, str(NOTEBOOK_RENDER_DIR))
