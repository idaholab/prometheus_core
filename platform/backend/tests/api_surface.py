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

"""Build a snapshot of the backend's *behavioral* HTTP surface.

The snapshot pins what a client can observe -- paths, methods, success status
codes, parameters, request bodies, success response schemas and component
schemas -- and deliberately drops everything that is documentation only
(descriptions, summaries, examples, titles, tags, operationIds, security
declarations and non-2xx responses). Documentation passes therefore leave it
untouched, while anything that would change runtime behavior shows up as a
diff against ``tests/snapshots/api_surface.json``.

``tests/test_api_surface.py`` compares the live app against the golden file.
When a change to the surface is intentional, regenerate it and commit the diff
so reviewers see exactly what moved::

    uv run python -m tests.api_surface
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import routing
from fastapi.security.api_key import APIKeyBase

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "api_surface.json"

# OpenAPI keys that only carry documentation. Stripped everywhere except where
# they are a schema's *property names* (e.g. ``ConversationSummary.title``).
_DOC_KEYS = {"description", "summary", "examples", "example", "title", "tags", "operationId", "security"}

_FRAMEWORK_SCHEMAS = {"HTTPValidationError", "ValidationError"}

# ``app.routers.admin_users.AdminUserOut`` -> ``AdminUserOut``, so moving a model
# between modules is not reported as a surface change.
_QUALIFIED_NAME = re.compile(r"\b(?:[A-Za-z_]\w*\.)+([A-Za-z_]\w*)")


def _type_name(annotation: Any) -> str | None:
    if annotation is None:
        return None
    name = annotation.__name__ if isinstance(annotation, type) else str(annotation)
    return _QUALIFIED_NAME.sub(r"\1", name)


def _params(dependant: Any) -> dict[str, list[str]]:
    """Every parameter a route reads, including those contributed by its dependencies.

    API-key security schemes (``APIKeyCookie`` and friends) read a cookie, header or
    query value too, so they count as that kind of parameter: moving the session
    cookie from ``Cookie(...)`` onto a security scheme is not a surface change.
    """
    found: dict[str, set[str]] = {kind: set() for kind in ("path", "query", "header", "cookie", "body")}
    stack = [dependant]
    while stack:
        node = stack.pop()
        for kind in found:
            found[kind].update(p.alias for p in getattr(node, f"{kind}_params"))
        if isinstance(node.call, APIKeyBase):
            found[node.call.model.in_.value].add(node.call.model.name)
        stack.extend(node.dependencies)
    return {kind: sorted(names) for kind, names in found.items()}


def _route_table(app: Any) -> list[dict[str, Any]]:
    """The runtime routing table, including parameters contributed by dependencies."""
    table: list[dict[str, Any]] = []
    for ctx in routing.iter_route_contexts(app.routes):
        route = ctx.original_route
        if not isinstance(route, routing.APIRoute):
            table.append({"path": ctx.path, "kind": type(route).__name__})
            continue
        table.append(
            {
                "path": ctx.path,
                "methods": sorted(route.methods or ()),
                "status_code": route.status_code,
                "response_model": _type_name(route.response_model),
                "params": _params(route.dependant),
            }
        )
    return sorted(table, key=lambda r: (r["path"], r.get("methods", [])))


def _strip_docs(node: Any, *, under_properties: bool = False) -> Any:
    if isinstance(node, dict):
        return {
            key: _strip_docs(value, under_properties=key == "properties" and not under_properties)
            for key, value in node.items()
            if under_properties or key not in _DOC_KEYS
        }
    if isinstance(node, list):
        return [_strip_docs(item) for item in node]
    return node


def _openapi_surface(app: Any) -> dict[str, Any]:
    schema = app.openapi()
    paths: dict[str, Any] = {}
    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            operation = dict(operation)
            # Cookies are pinned by the route table, which also sees cookies read by a
            # security scheme; OpenAPI lists only the plain ``Cookie(...)`` ones.
            operation["parameters"] = [p for p in operation.get("parameters", []) if p.get("in") != "cookie"]
            if not operation["parameters"]:
                del operation["parameters"]
            operation["responses"] = {
                code: response for code, response in operation.get("responses", {}).items() if code.startswith("2")
            }
            paths.setdefault(path, {})[method] = _strip_docs(operation)
    # FastAPI's own validation-error schemas come and go with whether any route has a
    # validatable parameter; they are framework constants, not part of our surface.
    schemas = {
        name: _strip_docs(value)
        for name, value in schema.get("components", {}).get("schemas", {}).items()
        if name not in _FRAMEWORK_SCHEMAS
    }
    return {"paths": paths, "schemas": schemas}


def build_surface(app: Any = None) -> dict[str, Any]:
    if app is None:
        from app.main import app

    return {"routes": _route_table(app), "openapi": _openapi_surface(app)}


def render(surface: dict[str, Any]) -> str:
    return json.dumps(surface, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(render(build_surface()))
    print(f"wrote {SNAPSHOT_PATH}")
