"""Integration tests for PostgreSQL container (litellm-db)."""

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


def test_postgres_container_running(docker_compose_up):
    assert _docker_inspect_status("litellm-db") == "running"


def test_postgres_healthy(docker_compose_up):
    assert _docker_inspect_health("litellm-db") == "healthy"


def test_postgres_accepts_connection(docker_compose_up):
    """Connect to PostgreSQL and run a simple query."""
    result = subprocess.run(
        [
            "docker", "exec", "litellm-db",
            "psql", "-U", "litellm", "-d", "litellm", "-c", "SELECT 1;",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"psql failed: {result.stderr}"


def test_postgres_litellm_database_exists(docker_compose_up):
    result = subprocess.run(
        [
            "docker", "exec", "litellm-db",
            "psql", "-U", "litellm", "-d", "postgres",
            "-c", "SELECT datname FROM pg_database WHERE datname = 'litellm';",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "litellm" in result.stdout


def test_postgres_litellm_user_exists(docker_compose_up):
    result = subprocess.run(
        [
            "docker", "exec", "litellm-db",
            "psql", "-U", "litellm", "-d", "postgres",
            "-c", "SELECT rolname FROM pg_roles WHERE rolname = 'litellm';",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "litellm" in result.stdout
