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

"""Integration tests for the PostgreSQL container (admin-db)."""

import subprocess

import pytest


pytestmark = pytest.mark.integration


def _docker_inspect_status(container_name: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _docker_inspect_health(container_name: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_name],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_postgres_container_running(docker_compose_up, container_id):
    assert _docker_inspect_status(container_id("admin-db")) == "running"


def test_postgres_healthy(docker_compose_up, container_id):
    assert _docker_inspect_health(container_id("admin-db")) == "healthy"


def test_postgres_accepts_connection(docker_compose_up, container_id):
    """Connect to PostgreSQL and run a simple query."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_id("admin-db"),
            "psql",
            "-U",
            "admin",
            "-d",
            "prometheus",
            "-c",
            "SELECT 1;",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"psql failed: {result.stderr}"


def test_postgres_admin_database_exists(docker_compose_up, container_id):
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_id("admin-db"),
            "psql",
            "-U",
            "admin",
            "-d",
            "postgres",
            "-c",
            "SELECT datname FROM pg_database WHERE datname = 'prometheus';",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "prometheus" in result.stdout


def test_postgres_admin_user_exists(docker_compose_up, container_id):
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_id("admin-db"),
            "psql",
            "-U",
            "admin",
            "-d",
            "postgres",
            "-c",
            "SELECT rolname FROM pg_roles WHERE rolname = 'admin';",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "admin" in result.stdout
