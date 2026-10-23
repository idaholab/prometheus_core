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

"""Validate service dependency chains and startup order."""

from collections import defaultdict


def _get_depends_on(compose_data, service_name) -> dict:
    """Get depends_on as a normalized dict of {service: condition}."""
    deps = compose_data["services"][service_name].get("depends_on", {})
    if isinstance(deps, list):
        return {d: "service_started" for d in deps}
    if isinstance(deps, dict):
        return {name: cfg.get("condition", "service_started") for name, cfg in deps.items()}
    return {}


def test_client_agent_depends_on_backend_healthy(compose_data):
    """The client-agent registers with, and discovers agents through, the backend's registry."""
    deps = _get_depends_on(compose_data, "client-agent")
    assert "backend" in deps
    assert deps["backend"] == "service_healthy"


def test_frontend_dev_depends_on_backend_healthy(compose_data):
    deps = _get_depends_on(compose_data, "frontend-dev")
    assert "backend" in deps
    assert deps["backend"] == "service_healthy"


def test_frontend_prod_depends_on_backend_healthy(compose_data):
    deps = _get_depends_on(compose_data, "frontend-prod")
    assert "backend" in deps
    assert deps["backend"] == "service_healthy"


def test_client_agent_depends_on_redis_started(compose_data):
    deps = _get_depends_on(compose_data, "client-agent")
    assert "redis" in deps
    assert deps["redis"] == "service_started"


def test_backend_does_not_depend_on_client_agent(compose_data):
    """The client-agent waits on the backend, so the reverse edge would be a cycle."""
    deps = _get_depends_on(compose_data, "backend")
    assert "client-agent" not in deps


def test_backend_depends_on_redis_started(compose_data):
    deps = _get_depends_on(compose_data, "backend")
    assert "redis" in deps
    assert deps["redis"] == "service_started"


def test_no_circular_dependencies(compose_data, infrastructure_services):
    """Dependency graph must be a DAG (no cycles)."""
    graph = defaultdict(set)
    for svc_name in infrastructure_services:
        deps = _get_depends_on(compose_data, svc_name)
        for dep in deps:
            graph[svc_name].add(dep)

    # Kahn's algorithm for cycle detection
    in_degree = defaultdict(int)
    all_nodes = set(graph.keys())
    for deps in graph.values():
        all_nodes.update(deps)
    for node in all_nodes:
        in_degree[node] = 0
    for node, deps in graph.items():
        for dep in deps:
            in_degree[node] += 1  # node depends on dep

    # Actually, reverse: edges go from dependency to dependent
    reverse_graph = defaultdict(set)
    for node, deps in graph.items():
        for dep in deps:
            reverse_graph[dep].add(node)

    in_degree_correct = defaultdict(int)
    for node in all_nodes:
        in_degree_correct[node] = len(graph.get(node, set()) & all_nodes)

    queue = [n for n in all_nodes if not graph.get(n)]
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        for dependent in reverse_graph[current]:
            graph[dependent].discard(current)
            if not graph[dependent]:
                queue.append(dependent)

    assert visited == len(all_nodes), "Circular dependency detected in service graph"


def test_startup_order(compose_data, infrastructure_services):
    """Verify that a valid startup order exists: base services first, dependents after."""
    # Build dependency sets
    deps_map = {}
    for svc in infrastructure_services:
        deps_map[svc] = set(_get_depends_on(compose_data, svc).keys())

    # admin-db and redis should have no infra dependencies
    assert not deps_map["admin-db"], "admin-db should have no dependencies"
    assert not deps_map["redis"], "redis should have no dependencies"

    # backend depends on the datastores, not client-agent: it hosts the agent registry
    assert deps_map["backend"] == {"redis", "admin-db"}

    # client-agent depends on the backend (its registry) and redis, so it starts last
    assert "backend" in deps_map["client-agent"]
    assert "redis" in deps_map["client-agent"]
