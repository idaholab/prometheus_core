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

"""Smoke tests for the MOOSEnger platform launcher.

The wrapper's behavior is tested in the MOOSEnger repository
(``tests/a2a/test_prometheus_agent.py``).  Here we only check that the packaged
agent builds a server on this platform's SDK -- which is what ``make up`` needs.
Skipped when MOOSEnger is not installed in the test environment (the platform's
per-agent CI job installs only prometheus_api plus this directory's lock file).
"""

import pytest

pa = pytest.importorskip("moosenger.a2a.prometheus_agent", reason="MOOSEnger not installed")


def test_build_app_loads_packaged_agent_card(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SECRET", "test-secret")
    monkeypatch.setenv("PROMETHEUS_TASK_STORE", "memory")
    agent = pa.MOOSEngerPrometheusAgent(project_dir=tmp_path)

    assert agent.build_app(register_on_startup=False) is not None
    assert {s.id for s in agent.agent_card.skills} == {pa.SKILL_QA, pa.SKILL_GENERATE, pa.SKILL_EXECUTE}


def test_launcher_imports_main():
    import agent

    assert agent.main is pa.main
