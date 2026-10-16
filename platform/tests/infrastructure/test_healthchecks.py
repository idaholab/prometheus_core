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

"""Validate health check configurations for infrastructure services."""


def _get_healthcheck(compose_data, service_name) -> dict | None:
    return compose_data["services"][service_name].get("healthcheck")


def test_postgres_has_healthcheck(compose_data):
    hc = _get_healthcheck(compose_data, "litellm-db")
    assert hc is not None, "litellm-db should define a healthcheck"


def test_postgres_healthcheck_command(compose_data):
    hc = _get_healthcheck(compose_data, "litellm-db")
    test_cmd = hc["test"]
    # test can be a list like ["CMD-SHELL", "pg_isready -U litellm"]
    joined = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "pg_isready" in joined
    assert "-U litellm" in joined


def test_litellm_has_healthcheck(compose_data):
    hc = _get_healthcheck(compose_data, "litellm")
    assert hc is not None, "litellm should define a healthcheck"


def test_litellm_healthcheck_url(compose_data):
    hc = _get_healthcheck(compose_data, "litellm")
    test_cmd = hc["test"]
    joined = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "health/liveliness" in joined
    assert "localhost:4000" in joined


def test_litellm_healthcheck_has_start_period(compose_data):
    hc = _get_healthcheck(compose_data, "litellm")
    assert "start_period" in hc, "litellm healthcheck should have start_period (slow startup)"


def test_valkey_has_no_healthcheck(compose_data):
    """Document current state: Valkey has no healthcheck defined."""
    hc = _get_healthcheck(compose_data, "redis")
    assert hc is None, "Valkey currently has no healthcheck (update this test if one is added)"


def test_backend_has_healthcheck(compose_data):
    """The backend must have one: it carries `restart: unless-stopped`.

    Without a healthcheck the restart policy papers over a backend that boots but
    cannot serve -- the container reports "Up" either way -- which is precisely the
    class of silent failure the mesh subprocess pool was added to make visible.
    """
    hc = _get_healthcheck(compose_data, "backend")
    assert hc is not None, "backend should define a healthcheck"


def test_backend_healthcheck_probes_healthz(compose_data):
    hc = _get_healthcheck(compose_data, "backend")
    test_cmd = hc["test"]
    joined = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "/healthz" in joined
    assert "localhost:8000" in joined, "must probe the container port, not the host port"


def test_backend_healthcheck_has_start_period(compose_data):
    """The entrypoint runs `alembic upgrade head` before uvicorn, so first boot is slow."""
    hc = _get_healthcheck(compose_data, "backend")
    assert "start_period" in hc


def _assert_agent_healthcheck(hc, where: str) -> None:
    assert hc is not None, f"{where} should define a healthcheck"
    test_cmd = hc["test"]
    joined = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    # The agent template reads AGENT_PORT in the probe, so match host and path
    assert "localhost:" in joined, f"{where} must probe the container itself, not a host port"
    assert "/health'" in joined, f"{where} must probe the base-class /health endpoint"
    assert "start_period" in hc, f"{where} healthcheck should have start_period"


def test_client_agent_has_healthcheck(compose_data):
    """Lets `docker compose up --wait` gate on the client-agent serving HTTP."""
    _assert_agent_healthcheck(_get_healthcheck(compose_data, "client-agent"), "client-agent")


def test_agent_compose_files_have_healthchecks(project_root):
    """Same probe for every per-agent file make generate includes."""
    import yaml

    paths = (
        sorted(project_root.glob("agents/*/docker-compose.yml"))
        + sorted(project_root.glob("agents/debug-agents/*/docker-compose.yml"))
        + sorted(project_root.glob("agents/optional/*/docker-compose.yml"))
    )
    assert paths, "no per-agent compose files found"
    for path in paths:
        data = yaml.safe_load(path.read_text()) or {}
        for name, svc in (data.get("services") or {}).items():
            _assert_agent_healthcheck(svc.get("healthcheck"), f"{path.relative_to(project_root)}: {name}")


def test_frontend_prod_has_healthcheck(compose_data):
    """Probes nginx on its container port; the image has wget but no python."""
    hc = _get_healthcheck(compose_data, "frontend-prod")
    assert hc is not None, "frontend-prod should define a healthcheck"
    test_cmd = hc["test"]
    joined = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "wget" in joined
    assert "127.0.0.1:8080" in joined, "must probe the container port, not the host port"
