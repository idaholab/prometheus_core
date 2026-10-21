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

"""Static checks of the Helm chart's rendered output, the counterpart of test_compose_static.py.

Renders ``infrastructure/helm/prometheus`` with ``helm template`` (as make cluster-deploy
does: values-dev.yaml plus every agent's helm-values.yaml, with every agent enabled) and
checks that the chart deploys what Compose does: the same services under the same names,
the same pinned images, and the environment each service needs. Skipped when helm isn't
installed.

The agents checked are the ones that ship a helm-values.yaml. An agent without one is
simply not deployed to the cluster; that is not an error, so adding an agent with only a
Dockerfile and a compose file keeps CI green.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")

PLATFORM = Path(__file__).resolve().parent.parent.parent

INFRASTRUCTURE = {"litellm-db", "admin-db", "litellm", "redis", "backend", "client-agent", "frontend"}


def _discover_agents() -> dict[str, Path]:
    """Each agent a helm-values.yaml defines, by name, mapped to that file's directory."""
    agents: dict[str, Path] = {}
    for values in sorted((PLATFORM / "agents").glob("**/helm-values.yaml")):
        for name in (yaml.safe_load(values.read_text()) or {}).get("agents") or {}:
            agents[name] = values.parent
    return agents


# Agent name (its Deployment and Service name, and the name it registers with LiteLLM
# under) -> its directory
AGENTS = _discover_agents()

# The agents that also run under Compose, where the compose service has the same name.
# Only these can be compared with Compose.
COMPOSE_AGENTS = {
    name: directory / "docker-compose.yml"
    for name, directory in AGENTS.items()
    if (directory / "docker-compose.yml").is_file()
    and name in (yaml.safe_load((directory / "docker-compose.yml").read_text()).get("services") or {})
}

# Variables Compose sets that the chart deliberately handles another way
CHART_HANDLES_OTHERWISE = {
    # Build-time proxy settings; Compose passes them to builds, not to running agents
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
}


@pytest.fixture(scope="session")
def chart_path(project_root: Path) -> Path:
    return project_root.parent / "infrastructure" / "helm" / "prometheus"


def _render(project_root: Path, chart: Path, *args: str) -> list[dict]:
    agent_values = sorted((project_root / "agents").glob("**/helm-values.yaml"))
    cmd = ["helm", "template", "prometheus", str(chart), "-f", str(chart / "values-dev.yaml")]
    for path in agent_values:
        cmd += ["-f", str(path)]
    cmd += ["-f", str(chart / "values-debug.yaml")]
    # Every agent, including the ones that ship disabled
    for name in AGENTS:
        cmd += ["--set", f"agents.{name}.enabled=true"]
    cmd += ["--set-file", f"litellm.config={project_root / 'litellm_config.yaml'}", *args]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


@pytest.fixture(scope="session")
def rendered(project_root: Path, chart_path: Path) -> list[dict]:
    return _render(project_root, chart_path)


def _objects(rendered: list[dict], kind: str) -> dict[str, dict]:
    return {o["metadata"]["name"]: o for o in rendered if o["kind"] == kind}


def _workloads(rendered: list[dict]) -> dict[str, dict]:
    return {**_objects(rendered, "Deployment"), **_objects(rendered, "StatefulSet")}


def _container(workload: dict) -> dict:
    return workload["spec"]["template"]["spec"]["containers"][0]


def _env_names(rendered: list[dict], workload: dict) -> set[str]:
    """Every variable a container gets: env, and the keys of each envFrom ConfigMap.

    envFrom Secrets come from .env at deploy time, so they count as providing every
    variable .env.example lists.
    """
    container = _container(workload)
    names = {e["name"] for e in container.get("env", [])}
    configmaps = _objects(rendered, "ConfigMap")
    for source in container.get("envFrom", []):
        if "configMapRef" in source:
            names |= set(configmaps[source["configMapRef"]["name"]]["data"])
        if "secretRef" in source:
            names.add(f"secret:{source['secretRef']['name']}")
    return names


def _compose_env(compose_file: Path, service: str) -> set[str]:
    data = yaml.safe_load(compose_file.read_text())
    env = data["services"][service].get("environment", {})
    keys = env if isinstance(env, dict) else [item.split("=", 1)[0] for item in env]
    return set(keys)


def test_infrastructure_services_rendered(rendered):
    services = set(_objects(rendered, "Service"))
    assert INFRASTRUCTURE <= services, f"Missing services: {INFRASTRUCTURE - services}"


def test_agents_are_found():
    """Guards the discovery itself: the in-repo agents ship helm-values.yaml files."""
    assert AGENTS, "no helm-values.yaml found under agents/"


def test_every_agent_renders(rendered):
    """Each agent a helm-values.yaml defines renders a Deployment and Service of its name."""
    deployments = set(_objects(rendered, "Deployment"))
    services = set(_objects(rendered, "Service"))
    assert set(AGENTS) <= deployments, f"Agents not rendered: {set(AGENTS) - deployments}"
    assert set(AGENTS) <= services, f"Agents without a Service: {set(AGENTS) - services}"


@pytest.mark.parametrize("name", sorted(n for n, d in AGENTS.items() if d.parent.name in ("debug-agents", "optional")))
def test_debug_and_optional_agents_ship_disabled(name):
    """Like Compose's DEBUG_AGENTS and OPTIONAL_AGENTS, these run only when asked for."""
    values = yaml.safe_load((AGENTS[name] / "helm-values.yaml").read_text())
    assert values["agents"][name]["enabled"] is False


def test_pinned_third_party_images(rendered, compose_data):
    workloads = _workloads(rendered)
    for name in ("litellm-db", "admin-db", "litellm", "redis"):
        compose_image = compose_data["services"][name]["image"]
        image = _container(workloads[name])["image"]
        assert image.endswith("/" + compose_image.split("/")[-1]), f"{name}: chart {image}, compose {compose_image}"


def test_first_party_images_share_one_tag(project_root, chart_path):
    docs = _render(project_root, chart_path, "--set", "global.image.tag=20261021-abc1234")
    first_party = {
        name: _container(w)["image"]
        for name, w in _workloads(docs).items()
        if name in {"backend", "client-agent", "frontend"} | set(AGENTS)
    }
    for name, image in first_party.items():
        assert image.startswith("ghcr.io/idaholab/prometheus_core/prometheus_"), f"{name}: {image}"
        assert image.endswith("-devel:20261021-abc1234"), f"{name}: {image}"


@pytest.mark.parametrize("agent", sorted(COMPOSE_AGENTS))
def test_agent_gets_compose_env(rendered, project_root, env_example_path, agent):
    """Each agent gets every variable its compose service sets.

    A variable counts when the chart sets it (env or the common ConfigMap), or when the
    pod reads the shared Secret and the variable is one .env can hold: listed in
    .env.example, or one of the optional keys Compose defaults to empty.
    """
    workload = _objects(rendered, "Deployment")[agent]
    have = _env_names(rendered, workload)
    in_env_file = set()
    if "secret:prometheus-env" in have:
        for line in env_example_path.read_text().splitlines():
            name = line.lstrip("# ").split("=", 1)[0]
            if name.isupper() and "=" in line:
                in_env_file.add(name)
        in_env_file |= {"AGENT_SECRET", "REDIS_PASSWORD", "LITELLM_MASTER_KEY"}
        in_env_file |= {
            k for k in _compose_env(project_root / "docker-compose.yml", "backend") if k.startswith("DEEPLYNX_")
        }
        in_env_file.add("USER_IDENTITY_PUBLIC_KEY")
    compose_env = _compose_env(COMPOSE_AGENTS[agent], agent)
    missing = compose_env - have - in_env_file - CHART_HANDLES_OTHERWISE
    assert not missing, f"{agent} lacks {sorted(missing)}"
    assert {"REGISTRY_URL", "REDIS_URL", "JWKS_URL", "AGENT_PORT", "EXTERNAL_AGENT_URL"} <= have


@pytest.mark.parametrize("name", ["client-agent", *sorted(AGENTS)])
def test_agents_register_their_service_name(rendered, name):
    env = {e["name"]: e.get("value") for e in _container(_objects(rendered, "Deployment")[name])["env"]}
    assert env["EXTERNAL_AGENT_URL"] == f"http://{name}:8000"
    assert env["REGISTRY_URL"] == "http://litellm:4000"


def test_compose_common_env_reaches_every_agent(rendered, compose_data):
    """Non-secret x-common-env keys come from the common ConfigMap or fixed URLs."""
    common = _objects(rendered, "ConfigMap")["prometheus-common"]["data"]
    fixed = {"REGISTRY_URL", "REDIS_URL", "JWKS_URL"}
    secrets_from_env = {
        "AGENT_SECRET",
        "REDIS_PASSWORD",
        "DEEPLYNX_KEY",
        "DEEPLYNX_SECRET",
        "DEEPLYNX_ORG_ID",
        "DEEPLYNX_PROJECT_ID",
        "USER_IDENTITY_PUBLIC_KEY",
    }
    missing = set(compose_data["x-common-env"]) - set(common) - fixed - secrets_from_env
    assert not missing, f"x-common-env keys the chart doesn't set: {sorted(missing)}"


def test_backend_env(rendered, compose_data):
    have = _env_names(rendered, _objects(rendered, "Deployment")["backend"])
    compose_env = set(compose_data["services"]["backend"]["environment"]) - set(compose_data["x-common-env"])
    assert compose_env <= have, f"backend lacks {sorted(compose_env - have)}"


def test_private_keys_stay_off_the_agents(rendered):
    """Only the backend gets the signing and admin-plane keys, as in Compose."""
    private = {"BACKEND_JWT_SECRET", "USER_IDENTITY_PRIVATE_KEY", "ADMIN_DB_ENCRYPTION_KEY", "ADMIN_DB_PASSWORD"}
    for name, workload in _objects(rendered, "Deployment").items():
        if name == "backend":
            continue
        env = {e["name"] for e in _container(workload).get("env", [])}
        sources = [s.get("secretRef", {}).get("name") for s in _container(workload).get("envFrom", [])]
        assert not env & private, f"{name} gets {env & private}"
        assert "prometheus-env-private" not in sources, f"{name} reads the private Secret"


def test_probes(rendered):
    deployments = _objects(rendered, "Deployment")
    expected = {"backend": ("/healthz", "/readyz"), "frontend": ("/healthz", "/healthz")}
    expected["litellm"] = ("/health/liveliness", "/health/readiness")
    for name in ["client-agent", *AGENTS]:
        expected[name] = ("/healthz", "/healthz")
    for name, (liveness, readiness) in expected.items():
        container = _container(deployments[name])
        assert container["livenessProbe"]["httpGet"]["path"] == liveness, name
        assert container["readinessProbe"]["httpGet"]["path"] == readiness, name
        assert "startupProbe" in container, name


def test_backend_memory_limit_matches_compose(rendered):
    limits = _container(_objects(rendered, "Deployment")["backend"])["resources"]["limits"]
    assert limits["memory"] == "4Gi"


def test_ingress_routes_api_to_backend(rendered):
    paths = {
        p["path"]: p["backend"]["service"]["name"]
        for rule in _objects(rendered, "Ingress")["prometheus"]["spec"]["rules"]
        for p in rule["http"]["paths"]
    }
    assert paths == {"/api": "backend", "/": "frontend"}


def test_datastores_persist(rendered):
    for name in ("litellm-db", "admin-db", "redis"):
        claims = _objects(rendered, "StatefulSet")[name]["spec"]["volumeClaimTemplates"]
        assert claims, f"{name} has no volume claim"
