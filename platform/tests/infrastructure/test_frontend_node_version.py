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

"""The frontend's CI jobs run the same Node as the frontend's Dockerfile."""

import re
from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def dockerfile_node(project_root: Path) -> str:
    """The Node version in the frontend Dockerfile's base image, e.g. 22.23.3."""
    text = (project_root / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^FROM node:(\d+\.\d+\.\d+)\b", text, re.MULTILINE)
    assert match, "frontend/Dockerfile has no FROM node:<x.y.z> line"
    return match.group(1)


@pytest.fixture(scope="module")
def frontend_ci_jobs(project_root: Path) -> dict[str, dict]:
    """The test workflow's jobs that run in platform/frontend, by job id."""
    workflow = yaml.safe_load((project_root.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))
    return {
        job_id: job
        for job_id, job in workflow["jobs"].items()
        if job.get("defaults", {}).get("run", {}).get("working-directory") == "platform/frontend"
    }


def test_frontend_ci_jobs_are_found(frontend_ci_jobs: dict[str, dict]):
    """The jobs below are still found, so the version check can't pass on nothing."""
    assert {"platform-frontend-npm", "platform-frontend-e2e"} <= set(frontend_ci_jobs)


def test_frontend_ci_node_matches_dockerfile(frontend_ci_jobs: dict[str, dict], dockerfile_node: str):
    """Each frontend job's setup-node version equals the Dockerfile's, so CI tests the Node production runs."""
    for job_id, job in frontend_ci_jobs.items():
        versions = [
            step["with"]["node-version"]
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/setup-node@")
        ]
        assert versions, f"{job_id} has no actions/setup-node step"
        for version in versions:
            assert str(version) == dockerfile_node, (
                f"{job_id} runs Node {version}, but frontend/Dockerfile uses {dockerfile_node}; change them together"
            )
