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

"""OpenAPI operationIds: each is its handler's name, and none repeats.

FastAPI only warns when two routes get the same operationId, so without this test a
duplicate handler name fails nothing but the Redocly lint in CI.
"""

from __future__ import annotations

from collections import Counter

from fastapi.routing import APIRoute

from app.main import app
from app.routers import (
    admin_keys,
    admin_oidc,
    admin_users,
    agent_registry,
    artifacts,
    auth,
    chat,
    config,
    conversations,
    events,
    health,
    jwks,
    sessions,
    setup,
    uploads,
)

ROUTERS = [
    admin_keys,
    admin_oidc,
    admin_users,
    agent_registry,
    artifacts,
    auth,
    chat,
    config,
    conversations,
    events,
    health,
    jwks,
    sessions,
    setup,
    uploads,
]


def _operation_ids() -> list[str]:
    return [op["operationId"] for path in app.openapi()["paths"].values() for op in path.values()]


def test_operation_ids_are_unique() -> None:
    duplicates = [name for name, count in Counter(_operation_ids()).items() if count > 1]
    assert duplicates == []


def test_operation_ids_are_handler_names() -> None:
    handlers = [route.name for module in ROUTERS for route in module.router.routes if isinstance(route, APIRoute)]
    assert sorted(_operation_ids()) == sorted(handlers)
