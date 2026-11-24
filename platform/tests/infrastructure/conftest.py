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

"""Shared fixtures for infrastructure tests."""

import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the path to the prometheus_platform directory."""
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def compose_path(project_root: Path) -> Path:
    """Return the path to docker-compose.yml."""
    return project_root / "docker-compose.yml"


@pytest.fixture(scope="session")
def compose_data(compose_path: Path) -> dict:
    """Parse and return docker-compose.yml as a dict."""
    return yaml.safe_load(compose_path.read_text())


@pytest.fixture(scope="session")
def env_example_path(project_root: Path) -> Path:
    """Return the path to .env.example."""
    return project_root / ".env.example"


@pytest.fixture(scope="session")
def env_example_vars(env_example_path: Path) -> dict[str, str]:
    """Parse .env.example into a dict of name -> value.

    Skips blank lines and comments. Commented-out vars (# VAR=val) are excluded.
    """
    result = {}
    for line in env_example_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


@pytest.fixture(scope="session")
def infrastructure_services() -> set[str]:
    """Return the set of infrastructure service names (excludes specialist agents)."""
    return {"admin-db", "redis", "backend", "client-agent"}


def _extract_compose_var_refs(compose_text: str) -> list[tuple[str, bool]]:
    """Extract all ${VAR}, ${VAR:-default}, ${VAR:+alt} and ${VAR:?error} references from compose file.

    Returns list of (var_name, has_default) tuples. ``:?`` makes a var required, so it
    has no default. ``:+`` is blank while the var is unset, so it counts as having one,
    and so does the ``${VAR}`` inside ``${VAR:+${VAR}:}``, which is only read when set.
    """
    results = []
    optional = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\+", compose_text))
    for match in re.finditer(r"\$\{([^${}]+)\}", compose_text):
        expr = match.group(1)
        if expr in optional:
            results.append((expr, True))
        elif ":-" in expr:
            var_name = expr.split(":-")[0]
            results.append((var_name, True))
        elif ":?" in expr:
            results.append((expr.split(":?")[0], False))
        else:
            results.append((expr, False))
    return results


@pytest.fixture(scope="session")
def compose_var_refs(compose_path: Path) -> list[tuple[str, bool]]:
    """All ${VAR} references in docker-compose.yml as (name, has_default) tuples."""
    return _extract_compose_var_refs(compose_path.read_text())


# ---------------------------------------------------------------------------
# Integration test fixtures
# ---------------------------------------------------------------------------

# The compose project the stack under test runs as. Matches the root Makefile's
# default, so a stack from ``make up`` is found without any extra setup.
COMPOSE_PROJECT_NAME = os.environ.get("COMPOSE_PROJECT_NAME", "prometheus_platform")


def _container_id(service: str) -> str:
    """Return the ID of the compose project's container for ``service``.

    Services have no fixed container_name (so stacks from different checkouts
    can run side by side), so containers are found by their compose labels.
    Falls back to the service name, so a docker command on it fails cleanly.
    """
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={COMPOSE_PROJECT_NAME}",
            "--filter",
            f"label=com.docker.compose.service={service}",
        ],
        capture_output=True,
        text=True,
    )
    ids = result.stdout.split()
    return ids[0] if ids else service


def _docker_available() -> bool:
    """Check if Docker CLI is available and the daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _wait_for_container_healthy(service: str, timeout: int = 120) -> bool:
    """Poll docker inspect until the service's container is healthy or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", _container_id(service)],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip()
        if status == "healthy":
            return True
        if status in ("unhealthy", ""):
            time.sleep(2)
            continue
        time.sleep(2)
    return False


def _wait_for_container_running(service: str, timeout: int = 60) -> bool:
    """Poll until the service's container is running or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", _container_id(service)],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() == "running":
            return True
        time.sleep(2)
    return False


def _inspect_container(service: str, format_string: str) -> str:
    """Return a docker inspect formatted field of the service's container, or empty string on error."""
    result = subprocess.run(
        ["docker", "inspect", "--format", format_string, _container_id(service)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _get_container_logs(service: str, tail: int = 80) -> str:
    """Return the service container's recent docker logs for debugging setup failures."""
    result = subprocess.run(
        ["docker", "logs", "--tail", str(tail), _container_id(service)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"<unable to fetch logs: {result.stderr.strip()}>"
    return result.stdout.strip() or result.stderr.strip() or "<no logs>"


def _wait_for_http_ready(url: str, timeout: int = 120, ok_statuses: tuple[int, ...] = (200,)) -> bool:
    """Poll an HTTP endpoint until it returns one of the accepted statuses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=5, follow_redirects=True)
            if resp.status_code in ok_statuses:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def _tail_lines(text: str, max_lines: int = 80) -> str:
    """Return the last max_lines of text for compact diagnostics."""
    lines = (text or "").splitlines()
    if len(lines) <= max_lines:
        return text or "<empty>"
    return "\n".join(lines[-max_lines:])


def _run_compose_or_fail(
    compose_cmd: list[str],
    project_root: Path,
    args: list[str],
    *,
    timeout: int,
) -> None:
    """Run docker compose and fail the fixture with useful output on errors."""
    result = subprocess.run(
        [*compose_cmd, *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode == 0:
        return

    stdout = _tail_lines(result.stdout)
    stderr = _tail_lines(result.stderr)
    pytest.fail(
        "docker compose command failed.\n"
        f"Command: {' '.join([*compose_cmd, *args])}\n"
        f"Exit code: {result.returncode}\n"
        f"stdout (tail):\n{stdout}\n"
        f"stderr (tail):\n{stderr}"
    )


@pytest.fixture(scope="session")
def container_id():
    """Look up the stack's container ID for a compose service name."""
    return _container_id


@pytest.fixture(scope="session")
def running_stack() -> bool:
    """Whether a platform stack (e.g. from ``make up``) is already running.

    The test stack would run as the same compose project, so it can't start
    next to it; the integration tests use the running one instead.
    """
    return _docker_available() and _inspect_container("backend", "{{.State.Status}}") == "running"


@pytest.fixture(scope="session")
def env_test_file(project_root: Path, running_stack: bool):
    """Return the env file of the stack under test.

    With a running stack, that's its platform/.env. Otherwise, generate a
    .env.test file with test-safe credentials, cleaned up after the session.
    """
    if running_stack:
        env_path = project_root / ".env"
        if not env_path.is_file():
            pytest.fail(f"A platform stack is running, but {env_path} (its credentials and ports) does not exist")
        yield env_path
        return

    test_secret = uuid.uuid4().hex[:16]
    env_path = project_root / ".env.test"
    env_path.write_text(
        f"LLM_CONFIG_PROFILE=anthropic\n"
        f"LLM_API_KEY=sk-ant-test-not-real\n"
        f"AGENT_SECRET={test_secret}\n"
        f"REDIS_PASSWORD={test_secret}\n"
        f"REDIS_URL=redis://:{test_secret}@redis:6379\n"
        f"BACKEND_JWT_SECRET={test_secret}\n"
        f"ADMIN_DB_PASSWORD={test_secret}\n"
        f"REDIS_LOCAL_PORT=16379\n"
        f"CLIENT_AGENT_PORT=18001\n"
        f"BACKEND_PORT=18600\n"
        f"CLIENT_AGENT_URL=http://client-agent:8000\n"
    )
    yield env_path
    env_path.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def test_ports() -> dict[str, int]:
    """Host ports used by integration tests (offset from defaults to avoid conflicts)."""
    return {
        "redis": 16379,
        "client_agent": 18001,
        "backend": 18600,
    }


def _parse_env_test_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict."""
    result = {}
    for line in env_path.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k] = v
    return result


@pytest.fixture(scope="session")
def docker_compose_up(project_root: Path, env_test_file: Path, test_ports: dict[str, int], running_stack: bool):
    """Start infrastructure-only Docker stack for integration tests.

    Uses .env.test with test-safe credentials and offset ports.
    Only starts infra services (no agents).
    Tears down and removes volumes after session.

    If a stack is already running (``make up``), use it as is: it's neither
    started nor torn down here, and its ports come from platform/.env.
    """
    if running_stack:
        env_vars = _parse_env_test_file(env_test_file)
        yield {
            "redis": int(env_vars.get("REDIS_LOCAL_PORT", "6379")),
            "client_agent": int(env_vars.get("CLIENT_AGENT_PORT", "8001")),
            "backend": int(env_vars.get("BACKEND_PORT", "8600")),
        }
        return

    if not _docker_available():
        pytest.skip("Docker is not available")

    compose_cmd = [
        "docker",
        "compose",
        "-p",
        COMPOSE_PROJECT_NAME,
        "-f",
        "docker-compose.yml",
        "--env-file",
        str(env_test_file),
    ]

    # Start in phases: the datastores, then the backend (it hosts the agent
    # registry the client-agent registers with), then the client-agent.
    core_services = ["admin-db", "redis"]
    app_services = ["backend", "client-agent"]

    try:
        # Start core infrastructure first.
        _run_compose_or_fail(
            compose_cmd,
            project_root,
            ["up", "-d", "--build", *core_services],
            timeout=600,
        )

        # Enforce readiness checks with actionable diagnostics on failure.
        core_readiness_checks = [
            ("admin-db", "healthy", _wait_for_container_healthy, 90),
            ("redis", "running", _wait_for_container_running, 60),
        ]
        for service, expected_state, wait_fn, timeout in core_readiness_checks:
            if wait_fn(service, timeout=timeout):
                continue

            status = _inspect_container(service, "{{.State.Status}}")
            health = _inspect_container(service, "{{if .State.Health}}{{.State.Health.Status}}{{end}}")
            logs = _get_container_logs(service)
            pytest.fail(
                f"Service {service} did not become {expected_state} within {timeout}s.\n"
                f"State={status or '<unknown>'}, Health={health or '<none>'}\n"
                f"Recent logs:\n{logs}"
            )

        # Start app services after core services are ready.
        _run_compose_or_fail(
            compose_cmd,
            project_root,
            ["up", "-d", "--build", *app_services],
            timeout=600,
        )

        app_readiness_checks = [
            ("backend", "running", _wait_for_container_running, 180),
            ("client-agent", "running", _wait_for_container_running, 120),
        ]
        for service, expected_state, wait_fn, timeout in app_readiness_checks:
            if wait_fn(service, timeout=timeout):
                continue

            status = _inspect_container(service, "{{.State.Status}}")
            health = _inspect_container(service, "{{if .State.Health}}{{.State.Health.Status}}{{end}}")
            logs = _get_container_logs(service)
            pytest.fail(
                f"Service {service} did not become {expected_state} within {timeout}s.\n"
                f"State={status or '<unknown>'}, Health={health or '<none>'}\n"
                f"Recent logs:\n{logs}"
            )

        env_vars = _parse_env_test_file(env_test_file)
        backend_port = env_vars.get("BACKEND_PORT", "18600")

        if not _wait_for_http_ready(
            f"http://localhost:{backend_port}/healthz",
            timeout=180,
            ok_statuses=(200,),
        ):
            logs = _get_container_logs("backend")
            pytest.fail(f"backend /healthz did not return HTTP 200 within 180s.\nRecent logs:\n{logs}")

        yield test_ports

    finally:
        # Tear down
        subprocess.run(
            [*compose_cmd, "down", "-v", "--remove-orphans"],
            cwd=project_root,
            capture_output=True,
            timeout=120,
        )
