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

"""Validate volume mounts and filesystem paths."""


def _get_volumes(svc: dict) -> list[str]:
    """Get volume strings from a service definition."""
    return [str(v) for v in svc.get("volumes", [])]


def test_litellm_config_bind_mount(compose_data):
    volumes = _get_volumes(compose_data["services"]["litellm"])
    assert any("litellm_config.yaml:/app/config.yaml" in v for v in volumes), (
        "litellm service should bind-mount litellm_config.yaml"
    )


def test_litellm_config_file_exists(project_root):
    assert (project_root / "litellm_config.yaml").exists()


# Only these three host paths may be bind-mounted at runtime. Every other service
# must run purely from its image, so the stack stays deployable to plain Docker or
# Kubernetes without provisioning a host path or an RWX volume for source. The
# frontend entry is the Vite dev server, which needs host sources for HMR and is
# gated behind the "dev" profile; litellm_config.yaml is config, i.e. a ConfigMap.
# The backend entry is the optional platform settings file, also config with no
# secrets (its passwords are env references); it is mounted read-only, so an edit
# needs a restart and no rebuild, i.e. a ConfigMap too.
ALLOWED_HOST_MOUNTS = {
    "litellm": {"./litellm_config.yaml:/app/config.yaml"},
    "frontend-dev": {"./frontend:/app"},
    "backend": {"./settings:/app/settings:ro"},
}


def _host_mounts(svc: dict) -> set[str]:
    """Bind mounts of a host path: 'source:target' whose source is a path.

    A single-segment entry such as '/app/node_modules' is an anonymous volume, not a
    bind, and a 'name:/target' entry is a named volume — neither ties the deployment
    to the host filesystem, so neither counts here. The long syntax counts when its
    ``type`` is ``bind``, and a source that starts with ``~`` or ``${...}`` counts too.
    """
    mounts = set()
    for v in svc.get("volumes", []):
        if isinstance(v, dict):  # long syntax: {type: bind, source: ..., target: ...}
            if v.get("type") == "bind":
                mounts.add(f"{v.get('source')}:{v.get('target')}")
        elif ":" in str(v) and str(v).split(":", 1)[0].startswith((".", "/", "~", "$")):
            mounts.add(str(v))
    return mounts


def test_host_mounts_sees_every_bind_form():
    svc = {
        "volumes": [
            {"type": "bind", "source": "./shared", "target": "/app/shared"},
            {"type": "volume", "source": "mesh-cache", "target": "/cache"},
            "~/src:/app/src",
            "${HOME}/src:/app/home",
            "mesh-cache:/cache",
            "/app/node_modules",
        ]
    }
    assert _host_mounts(svc) == {"./shared:/app/shared", "~/src:/app/src", "${HOME}/src:/app/home"}


def test_no_unexpected_host_bind_mounts(compose_data):
    for name, svc in compose_data["services"].items():
        assert _host_mounts(svc) <= ALLOWED_HOST_MOUNTS.get(name, set()), (
            f"service '{name}' bind-mounts a host path that is not in "
            f"ALLOWED_HOST_MOUNTS; prefer baking it into the image"
        )


def test_no_host_bind_mounts_in_agent_compose_files(project_root):
    """Same rule for the per-agent files make generate includes — no agent needs one."""
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
            assert not _host_mounts(svc), f"{path.relative_to(project_root)}: service '{name}' bind-mounts a host path"


def test_named_volumes_declared(compose_data):
    volumes = compose_data.get("volumes", {})
    assert "litellm-db-data" in volumes
    assert "valkey-data" in volumes
    assert "mesh-cache" in volumes


def test_mesh_cache_volume(compose_data):
    """Converted VTP timesteps must survive a backend restart.

    The cache is content-hash keyed, so a container-local /tmp meant every restart
    re-ran the (expensive, VTK-heavy) Exodus conversion for artifacts it had already
    converted. PROMETHEUS_MESH_CACHE_DIR has to agree with the mount point.
    """
    backend = compose_data["services"]["backend"]
    volumes = _get_volumes(backend)
    assert any("mesh-cache:/var/cache/prometheus-mesh" in v for v in volumes)
    assert backend["environment"]["PROMETHEUS_MESH_CACHE_DIR"] == "/var/cache/prometheus-mesh"


def test_postgres_data_volume(compose_data):
    volumes = _get_volumes(compose_data["services"]["litellm-db"])
    assert any("litellm-db-data:/var/lib/postgresql/data" in v for v in volumes)


def test_valkey_data_volume(compose_data):
    volumes = _get_volumes(compose_data["services"]["redis"])
    assert any("valkey-data:/data" in v for v in volumes)
