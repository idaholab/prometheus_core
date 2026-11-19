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

"""Validate port mappings and detect conflicts."""

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
import yaml

# The optional address every published port starts with (see docker-compose.yml)
PUBLISH_ADDR = "${PUBLISH_ADDR:+${PUBLISH_ADDR}:}"


def _parse_port_mapping(port_str: str) -> tuple[str, str]:
    """Parse a docker port string like '${VAR:-8600}:8000' into (host_expr, container_port).

    The optional PUBLISH_ADDR prefix is dropped first.
    """
    parts = port_str.removeprefix(PUBLISH_ADDR).split(":")
    if len(parts) == 2:
        return parts[0], parts[1]
    # host_ip:host_port:container_port
    return parts[1], parts[2]


def _published_ports(project_root: Path) -> list[tuple[str, str, str]]:
    """(file, service, mapping) for every `ports:` entry in the platform's compose files."""
    files = [
        project_root / "docker-compose.yml",
        project_root / "docker-compose.system-test.yml",
        project_root / "docker-compose.deeplynx.yml",
        *sorted((project_root / "agents").glob("**/docker-compose.yml")),
    ]
    found = []
    for path in files:
        services = (yaml.safe_load(path.read_text()) or {}).get("services") or {}
        for name, svc in services.items():
            for mapping in (svc or {}).get("ports", []):
                found.append((str(path.relative_to(project_root)), name, str(mapping)))
    return found


def _resolve_default(expr: str, env_vars: dict[str, str]) -> str | None:
    """Resolve ${VAR:-default} or ${VAR} using env_example_vars."""
    match = re.match(r"\$\{([^:}]+)(?::-(.*))?\}", expr)
    if match:
        var_name, default = match.group(1), match.group(2)
        return env_vars.get(var_name, default)
    return expr


def test_postgres_no_host_port(compose_data):
    """PostgreSQL should not expose a host port (internal-only access)."""
    svc = compose_data["services"]["admin-db"]
    assert "ports" not in svc, "admin-db should not expose host ports"


def test_redis_port_mapping(compose_data):
    svc = compose_data["services"]["redis"]
    ports = svc.get("ports", [])
    assert len(ports) == 1
    _, container_port = _parse_port_mapping(ports[0])
    assert container_port == "6379"


def test_backend_port_mapping(compose_data):
    svc = compose_data["services"]["backend"]
    ports = svc.get("ports", [])
    assert len(ports) == 1
    _, container_port = _parse_port_mapping(ports[0])
    assert container_port == "8000"


def test_client_agent_has_no_base_host_port_mapping(compose_data):
    svc = compose_data["services"]["client-agent"]
    assert "ports" not in svc
    assert svc["environment"]["AGENT_PORT"] == 8000


def test_no_host_port_conflicts(compose_data, env_example_vars):
    """After resolving defaults, no two services should map to the same host port."""
    host_ports = []
    for svc_name, svc in compose_data["services"].items():
        for port_str in svc.get("ports", []):
            host_expr, _ = _parse_port_mapping(str(port_str))
            resolved = _resolve_default(host_expr, env_example_vars)
            if resolved:
                host_ports.append((svc_name, resolved))

    port_counts = Counter(port for _, port in host_ports)
    duplicates = {port: count for port, count in port_counts.items() if count > 1}
    assert not duplicates, f"Host port conflicts detected: {duplicates}"


def test_internal_container_ports_correct(compose_data):
    """Verify internal container ports match expected values."""
    expected = {
        "redis": "6379",
        "backend": "8000",
    }
    for svc_name, expected_port in expected.items():
        ports = compose_data["services"][svc_name].get("ports", [])
        assert len(ports) >= 1, f"Service '{svc_name}' has no port mappings"
        _, container_port = _parse_port_mapping(str(ports[0]))
        assert container_port == expected_port, (
            f"Service '{svc_name}' internal port is {container_port}, expected {expected_port}"
        )


def test_every_published_port_can_be_kept_to_one_address(project_root):
    """PUBLISH_ADDR must reach every port: one it misses stays open to the network.

    The DeepLynx ports are always on loopback (it has no login), so a literal 127.0.0.1 is fine.
    """
    ports = _published_ports(project_root)
    assert len(ports) >= 7, ports
    unbound = [
        f"{path}: {name} {mapping}"
        for path, name, mapping in ports
        if not mapping.startswith((PUBLISH_ADDR, "127.0.0.1:"))
    ]
    assert unbound == [], f"start these with {PUBLISH_ADDR}: {unbound}"


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker compose")
@pytest.mark.parametrize("address", ["", "127.0.0.1"])
def test_compose_publishes_on_publish_addr_or_everywhere(project_root, address):
    """Blank: no host IP, so every interface (IPv4 and IPv6), as before. Set: that address only."""
    files = ["docker-compose.yml", "docker-compose.system-test.yml"]
    # Only what compose needs to render: not the developer's own PUBLISH_ADDR, ports or .env
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "LLM_CONFIG_PROFILE": "x"}
    result = subprocess.run(
        ["docker", "compose", "-p", "ports-probe", "--env-file", os.devnull]
        + [arg for name in files for arg in ("-f", name)]
        + ["--profile", "dev", "--profile", "prod", "config", "--format", "json"],
        cwd=project_root,
        env={**env, "PUBLISH_ADDR": address},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    published = {
        name: [port.get("host_ip") for port in svc.get("ports") or []]
        for name, svc in json.loads(result.stdout)["services"].items()
        if svc.get("ports")
    }
    assert set(published) == {"redis", "backend", "frontend-dev", "frontend-prod", "client-agent"}
    assert all(ips == [address or None] for ips in published.values()), published
