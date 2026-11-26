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

"""Generic orchestration code, shared by every orchestration level.

This package is shaped for the SDK (``prometheus_api.orchestration``): it must
not import client-agent modules (``orchestrator``, ``conversation_store``,
``task_graph``, ``workflow_library``, ``runtime``) or Valkey.
``tests/test_orchestration_imports.py`` enforces that. See
``docs/design/hierarchical-orchestration.md``.
"""
