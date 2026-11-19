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

"""The agent registry's storage: one Valkey hash of registrations, keyed by agent name.

:mod:`app.routers.agent_registry` writes it for the agents (``POST /v1/agents``) and
:mod:`app.routers.agents` reads it for the browser. Both read it through this module, so
the key, the decoding and the sort order have one home.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, cast

from app.redis_client import RedisClient

REGISTRY_KEY = "prometheus:agent-registry"


async def load_entry(redis: RedisClient, agent_name: str) -> Optional[Dict[str, Any]]:
    """The stored registration of *agent_name*, or ``None`` when it is not registered."""
    raw = await redis.hget(REGISTRY_KEY, agent_name)
    if raw is None:
        return None
    return cast(Dict[str, Any], json.loads(raw))


async def load_all(redis: RedisClient) -> List[Dict[str, Any]]:
    """Every stored registration, sorted by agent name."""
    entries = await redis.hgetall(REGISTRY_KEY)
    return [cast(Dict[str, Any], json.loads(raw)) for _, raw in sorted(entries.items())]
