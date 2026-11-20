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

"""Which agent is calling a service-to-service (``/v1``) route.

Every agent presents the same ``Bearer <AGENT_SECRET>``, so the secret alone proves
"some agent", never "which agent". ``AGENT_IDENTITY_SOURCE`` picks where the name
comes from:

``trusted-name`` (default; Docker Compose)
    The agent names itself in ``X-Agent-Name``. Nothing stops one agent from
    claiming another's name, so this is only as strong as the shared secret.

``istio`` (Kubernetes with Istio sidecars)
    The backend's sidecar terminates mTLS and forwards the verified peer identity in
    ``x-forwarded-client-cert`` (XFCC), as a SPIFFE ID
    (``spiffe://<trust-domain>/ns/<ns>/sa/<service-account>``). Istio's sidecar
    strips any client-supplied XFCC, so the header can be trusted **provided** the
    sidecar can't be bypassed: STRICT ``PeerAuthentication`` on the backend's
    namespace, plus a NetworkPolicy (or a loopback-only listen) so nothing reaches
    the pod port directly. Each agent needs its own ServiceAccount; the backend
    can't tell apart agents that share one.

    The SPIFFE ID is bound to an agent name when the agent registers
    (``POST /v1/agents``, see :mod:`app.routers.agent_registry`). Every later call
    resolves SPIFFE ID → name through the registry; any name in the request is
    ignored.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Request

from app.config import settings
from app.redis_client import RedisClient, get_redis

logger = logging.getLogger(__name__)

IdentitySource = Literal["trusted-name", "istio"]

AGENT_NAME_HEADER = "x-agent-name"
XFCC_HEADER = "x-forwarded-client-cert"


@dataclass(frozen=True)
class AgentCaller:
    """The calling agent. ``name`` is the registry key; ``spiffe_id`` is set under Istio."""

    name: str
    spiffe_id: Optional[str] = None


def parse_xfcc_spiffe_id(header: str) -> Optional[str]:
    """Return the SPIFFE ID of the immediate peer from an XFCC header, or ``None``.

    XFCC is a comma-separated list of elements, one per proxy hop, each a
    ``;``-separated list of ``Key=Value`` pairs (values may be double-quoted). Envoy
    appends the latest hop last, so the last element describes our direct peer.
    A ``URI=`` value that isn't ``spiffe://...`` is ignored.
    """
    elements = _split_unquoted(header, ",")
    if not elements:
        return None
    for pair in _split_unquoted(elements[-1], ";"):
        key, sep, value = pair.partition("=")
        if not sep or key.strip().lower() != "uri":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if value.startswith("spiffe://") and len(value) > len("spiffe://"):
            return value
    return None


def _split_unquoted(text: str, sep: str) -> list[str]:
    """Split on ``sep`` outside double quotes; drop empty parts."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == sep and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def caller_spiffe_id(request: Request) -> Optional[str]:
    """The verified SPIFFE ID of the caller under Istio, else ``None``."""
    if settings.agent_identity_source != "istio":
        return None
    return parse_xfcc_spiffe_id(request.headers.get(XFCC_HEADER) or "")


async def _name_for_spiffe_id(redis: RedisClient, spiffe_id: str) -> Optional[str]:
    # Imported here: the registry router depends on this module for registration.
    from app.routers.agent_registry import REGISTRY_KEY

    entries = await redis.hgetall(REGISTRY_KEY)
    for name, raw in entries.items():
        try:
            if json.loads(raw).get("spiffe_id") == spiffe_id:
                return str(name)
        except ValueError:
            continue
    return None


async def require_agent_caller(request: Request, redis: RedisClient = Depends(get_redis)) -> AgentCaller:
    """Identify the calling agent. Use with :func:`require_agent_secret` (route or router level).

    401 when the caller can't be identified; 403 under Istio when the workload is
    authenticated but no agent has registered under its SPIFFE ID.
    """
    if settings.agent_identity_source == "istio":
        spiffe_id = caller_spiffe_id(request)
        if spiffe_id is None:
            raise HTTPException(status_code=401, detail="No verified workload identity on the request")
        name = await _name_for_spiffe_id(redis, spiffe_id)
        if name is None:
            raise HTTPException(status_code=403, detail="No agent is registered for this workload identity")
        return AgentCaller(name=name, spiffe_id=spiffe_id)

    name = (request.headers.get(AGENT_NAME_HEADER) or "").strip()
    if not name:
        raise HTTPException(status_code=401, detail=f"Missing {AGENT_NAME_HEADER} header")
    return AgentCaller(name=name)
