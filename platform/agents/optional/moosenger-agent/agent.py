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

"""
MOOSEnger Agent -- platform launcher.

The agent itself lives in MOOSEnger: ``moosenger.a2a.prometheus_agent``
(installed with ``pip install moosenger[prometheus]``; see the Dockerfile).  It
subclasses ``PrometheusAgent`` and maps MOOSEnger's outputs, clarifications and
long-running execution onto the platform's artifacts, ``INPUT_REQUIRED`` forms
and background tasks.  Its agent card is packaged with it.

This file only exists so the agent fits the platform's per-agent layout
(``python agent.py`` entry point, ``make generate`` discovery); keep it to a
launcher so there is a single implementation to maintain.
"""

from moosenger.a2a.prometheus_agent import main

if __name__ == "__main__":
    main()
