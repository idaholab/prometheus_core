"""Validate port mappings and detect conflicts."""

import re
from collections import Counter


def _parse_port_mapping(port_str: str) -> tuple[str, str]:
    """Parse a docker port string like '${VAR:-8500}:8500' into (host_expr, container_port)."""
    parts = port_str.split(":")
    if len(parts) == 2:
        return parts[0], parts[1]
    # host_ip:host_port:container_port
    return parts[1], parts[2]


def _resolve_default(expr: str, env_vars: dict[str, str]) -> str | None:
    """Resolve ${VAR:-default} or ${VAR} using env_example_vars."""
    match = re.match(r"\$\{([^:}]+)(?::-(.*))?\}", expr)
    if match:
        var_name, default = match.group(1), match.group(2)
        return env_vars.get(var_name, default)
    return expr


def test_postgres_no_host_port(compose_data):
    """PostgreSQL should not expose a host port (internal-only access)."""
    svc = compose_data["services"]["litellm-db"]
    assert "ports" not in svc, "litellm-db should not expose host ports"


def test_litellm_port_mapping(compose_data):
    svc = compose_data["services"]["litellm"]
    ports = svc.get("ports", [])
    assert len(ports) == 1
    host_expr, container_port = _parse_port_mapping(ports[0])
    assert container_port == "4000"


def test_redis_port_mapping(compose_data):
    svc = compose_data["services"]["redis"]
    ports = svc.get("ports", [])
    assert len(ports) == 1
    _, container_port = _parse_port_mapping(ports[0])
    assert container_port == "6379"


def test_frontend_port_mapping(compose_data):
    svc = compose_data["services"]["chainlit-frontend"]
    ports = svc.get("ports", [])
    assert len(ports) == 1
    _, container_port = _parse_port_mapping(ports[0])
    assert container_port == "8500"


def test_client_agent_port_mapping(compose_data):
    svc = compose_data["services"]["client-agent"]
    ports = svc.get("ports", [])
    assert len(ports) == 1
    _, container_port = _parse_port_mapping(ports[0])
    assert container_port == "8000"


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
        "litellm": "4000",
        "redis": "6379",
        "chainlit-frontend": "8500",
        "client-agent": "8000",
    }
    for svc_name, expected_port in expected.items():
        ports = compose_data["services"][svc_name].get("ports", [])
        assert len(ports) >= 1, f"Service '{svc_name}' has no port mappings"
        _, container_port = _parse_port_mapping(str(ports[0]))
        assert container_port == expected_port, (
            f"Service '{svc_name}' internal port is {container_port}, expected {expected_port}"
        )
