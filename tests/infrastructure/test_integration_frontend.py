"""Integration tests for Chainlit frontend container."""

import subprocess

import httpx
import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def frontend_base_url(docker_compose_up, env_test_file):
    """Return the base URL for the Chainlit frontend."""
    env_vars = {}
    for line in env_test_file.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env_vars[k] = v
    port = env_vars.get("CHAINLIT_FRONTEND_PORT", "18500")
    return f"http://localhost:{port}"


def test_frontend_container_running(docker_compose_up):
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", "chainlit-frontend"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "running"


def test_frontend_serves_on_port(frontend_base_url):
    """Frontend should serve its HTML page."""
    resp = httpx.get(frontend_base_url, timeout=15, follow_redirects=True)
    assert resp.status_code == 200


def test_frontend_shared_mount_visible(docker_compose_up):
    """The bind mount for shared/ should make a2a_protocol.py visible inside the container."""
    result = subprocess.run(
        ["docker", "exec", "chainlit-frontend", "ls", "/app/shared/a2a_protocol.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"shared mount not visible: {result.stderr}"
