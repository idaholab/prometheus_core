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

Every entry is decoded on its own. ``POST /v1/agents`` validates what it stores, so a
bad entry can only come from a hand edit of Valkey. Such an entry is still returned, as
its hash field for ``agent_name`` and an empty ``agent_card_params``, and a warning is
logged, so one bad value cannot fail a read of the whole registry. Every returned entry
has a string ``agent_name`` and a dict ``agent_card_params``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.redis_client import RedisClient

logger = logging.getLogger(__name__)

REGISTRY_KEY = "prometheus:agent-registry"


def _text(value: str | bytes) -> str:
    # The client is created with decode_responses=True; bytes only satisfy its type.
    return value.decode() if isinstance(value, bytes) else value


def _decode(field: str, raw: str) -> Dict[str, Any]:
    """The entry stored under *field*. The hash field is the registry key, so it is the
    entry's ``agent_name``; an entry that does not decode to an object keeps only that."""
    try:
        value = json.loads(raw)
    except ValueError:
        logger.warning("Agent registry entry '%s' is not valid JSON; returning it without its card", field)
        return {"agent_name": field, "agent_card_params": {}}
    if not isinstance(value, dict):
        logger.warning("Agent registry entry '%s' is not a JSON object; returning it without its card", field)
        return {"agent_name": field, "agent_card_params": {}}
    card = value.get("agent_card_params")
    if not isinstance(card, dict):
        logger.warning("Agent registry entry '%s' has no card object; returning it without its card", field)
        card = {}
    return {**value, "agent_name": field, "agent_card_params": card}


async def load_entry(redis: RedisClient, agent_name: str) -> Optional[Dict[str, Any]]:
    """The stored registration of *agent_name*, or ``None`` when it is not registered."""
    raw = await redis.hget(REGISTRY_KEY, agent_name)
    if raw is None:
        return None
    return _decode(agent_name, _text(raw))


async def load_all(redis: RedisClient) -> List[Dict[str, Any]]:
    """Every stored registration, sorted by agent name."""
    entries = await redis.hgetall(REGISTRY_KEY)
    return [_decode(_text(field), _text(raw)) for field, raw in sorted(entries.items())]
