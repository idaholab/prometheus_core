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

"""Stack test: the adk role owns the adk schema in admin-db and cannot read the admin plane.

admin-db publishes no host port, so the test runs ``psql`` inside the already-running
``admin-db`` container with ``docker exec``. It never starts or stops a container, so it
does not use the ``docker_compose_up`` fixture.
"""

import os
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


def _env_value(project_root: Path, name: str) -> str:
    """Return a variable from the process environment, then platform/.env, else an empty string."""
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    env_path = project_root / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            key, sep, raw = line.partition("=")
            if sep and key.strip() == name:
                return raw.strip()
    return ""


@pytest.fixture
def adk_psql_env(project_root: Path) -> dict[str, str]:
    """Return a subprocess environment with PGPASSWORD for the adk role, or skip when admin-db is down."""
    try:
        status = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", "admin-db"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker is not available: {type(exc).__name__}")
    if status != "running":
        pytest.skip("The admin-db container is not running")
    password = _env_value(project_root, "ADK_DB_PASSWORD")
    if not password:
        pytest.skip("ADK_DB_PASSWORD is not set in the environment or platform/.env")
    # `docker exec -e PGPASSWORD` with no value copies it from this environment, so the
    # password never appears on a command line.
    return {**os.environ, "PGPASSWORD": password}


def _psql_as_adk(env: dict[str, str], sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "PGPASSWORD",
            "admin-db",
            "psql",
            "-U",
            "adk",
            "-d",
            "admin",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_adk_role_reads_its_own_schema(adk_psql_env):
    """The adk role can query adk.procedures, the table it owns."""
    result = _psql_as_adk(adk_psql_env, "select 1 from adk.procedures limit 1")
    assert result.returncode == 0, f"adk could not read adk.procedures: {result.stderr}"


def test_adk_role_cannot_read_admin_plane_users(adk_psql_env):
    """The adk role is denied the admin-plane public.users table."""
    result = _psql_as_adk(adk_psql_env, "select * from public.users")
    assert result.returncode != 0, "adk read public.users; the admin plane is not isolated"
    assert "permission denied" in result.stderr, f"Expected a permission error, got: {result.stderr}"
