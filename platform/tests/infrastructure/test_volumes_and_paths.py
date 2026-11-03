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

import re


def _get_volumes(svc: dict) -> list[str]:
    """Get volume strings from a service definition."""
    return [str(v) for v in svc.get("volumes", [])]


# Only this host path may be bind-mounted at runtime. Every other service
# must run purely from its image, so the stack stays deployable to plain Docker or
# Kubernetes without provisioning a host path or an RWX volume for source. The
# frontend entry is the Vite dev server, which needs host sources for HMR and is
# gated behind the "dev" profile.
ALLOWED_HOST_MOUNTS = {
    "frontend-dev": {"./frontend:/app"},
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
    assert "admin-db-data" in volumes
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
    assert any("mesh-cache:/cache/prometheus-mesh" in v for v in volumes)
    assert backend["environment"]["PROMETHEUS_MESH_CACHE_DIR"] == "/cache/prometheus-mesh"


def test_postgres_data_volume(compose_data):
    volumes = _get_volumes(compose_data["services"]["admin-db"])
    assert any("admin-db-data:/var/lib/postgresql/data" in v for v in volumes)


def test_valkey_data_volume(compose_data):
    volumes = _get_volumes(compose_data["services"]["redis"])
    assert any("valkey-data:/data" in v for v in volumes)


def _final_user(dockerfile: str) -> str | None:
    """The last USER instruction in a Dockerfile, i.e. the user the image runs as."""
    users = [
        line.split(None, 1)[1].strip() for line in dockerfile.splitlines() if line.strip().upper().startswith("USER ")
    ]
    return users[-1] if users else None


def test_backend_runs_as_non_root(project_root):
    """The backend image must end on the fixed non-root UID (k8s plan P1-11).

    Pod Security "restricted" rejects root containers, and the chart runs the pod as
    UID 10001 with a read-only root filesystem.
    """
    dockerfile = (project_root / "backend" / "Dockerfile").read_text()
    user = _final_user(dockerfile)
    assert user is not None, "backend/Dockerfile should set USER"
    assert user.split(":")[0] == "10001"


def test_backend_mesh_cache_owned_by_app_user(project_root):
    """The mesh cache mount point is created in the image, owned by the app UID.

    A fresh named volume copies the ownership of the directory it is mounted on, so
    this is what makes mesh-cache writable by the non-root backend. If the image
    lacked the mount point, Docker would create it owned by root.
    """
    dockerfile = (project_root / "backend" / "Dockerfile").read_text()
    assert "mkdir -p /cache/prometheus-mesh && chown -R 10001:10001 /cache" in dockerfile


def _stage_user(dockerfile: str, stage: str) -> str | None:
    """The last USER in one stage of a multi-stage Dockerfile."""
    stages = re.split(r"(?im)^FROM\s", dockerfile)
    for body in stages[1:]:
        if re.match(rf"\S+\s+AS\s+{stage}\s*$", body.splitlines()[0], re.IGNORECASE):
            return _final_user(body)
    raise AssertionError(f"no '{stage}' stage in Dockerfile")


def test_frontend_images_run_as_non_root(project_root):
    """Both frontend targets end on a fixed, numeric, non-root user (k8s plan P1-11).

    Numeric so hadolint DL3066 passes, and pinned here rather than inherited from the
    base image, so a base bump can't change the UID the chart expects. dev is the node
    image's `node` user; prod is nginx-unprivileged's 101, and never switches to root.
    """
    dockerfile = (project_root / "frontend" / "Dockerfile").read_text()
    assert _stage_user(dockerfile, "dev") == "1000:1000"
    assert _stage_user(dockerfile, "prod") == "101:101"
    prod = re.split(r"(?im)^FROM\s", dockerfile)[-1]
    assert not re.search(r"(?im)^USER\s+(0|root)\b", prod), "prod must not switch to root"


def test_frontend_prod_renders_config_outside_conf_d(project_root):
    """nginx's rendered config goes to /tmp, so a read-only root still gets it.

    With a read-only root and the default output dir, the template step fails to
    write conf.d/ and nginx starts on the stock config: no /api proxy, no /healthz.
    """
    dockerfile = (project_root / "frontend" / "Dockerfile").read_text()
    assert "NGINX_ENVSUBST_OUTPUT_DIR=/tmp" in dockerfile
    assert "include /tmp/default.conf;" in dockerfile


def test_frontend_dev_runs_as_host_user(compose_data, project_root):
    """frontend-dev runs as the developer's UID, which the Makefile exports.

    Vite writes into the bind-mounted ./frontend, owned by whoever checked it out,
    so a fixed UID breaks the dev server for anyone who isn't UID 1000.
    """
    assert compose_data["services"]["frontend-dev"]["user"] == "${HOST_UID:-1000}:${HOST_GID:-1000}"
    makefile = (project_root / "Makefile").read_text()
    assert "export HOST_UID HOST_GID" in makefile


def test_start_targets_drop_frontend_dev_node_modules(project_root):
    """down and clear-agent-registry remove frontend-dev with its volume, before stopping.

    Its node_modules is an anonymous volume: compose would otherwise keep an old one
    (stale dependencies, or root-owned from an older image) and leave ~550 MB behind
    each time the container is recreated. Every start target runs clear-agent-registry
    first, so that one removal covers all of them.
    """
    makefile = (project_root / "Makefile").read_text()
    # target -> (prerequisites, recipe lines); the target-specific variable lines
    # (`up: VAR := ...`) have no recipe and are skipped.
    rules = {
        name: (prereqs.split(), recipe.splitlines())
        for name, prereqs, recipe in re.findall(
            r"(?m)^([a-z-]+):(?! [A-Z_]+ :?=)([^\n#]*)(?:#[^\n]*)?\n((?:\t[^\n]*\n)+)", makefile
        )
    }
    for name in ("down", "clear-agent-registry"):
        assert name in rules, f"no {name} recipe in Makefile"
        assert rules[name][1][0].strip() == "$(RM_FRONTEND_DEV)", f"{name} must remove frontend-dev first"
    for name in ("up", "up-fg", "restart", "restart-fg", "ng-up", "ng-up-fg", "ng-restart", "ng-restart-fg"):
        assert name in rules, f"no {name} recipe in Makefile"
        assert "clear-agent-registry" in rules[name][0], f"{name} must depend on clear-agent-registry"
