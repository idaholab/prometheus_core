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

"""A2A agent registry and gateway (service-to-service; not part of CONTRACT.md).

Wire-compatible with the subset of LiteLLM's agent API that ``prometheus_api``'s
``AgentRegistryClient`` and the client-agent's ``tool_discovery`` use, so neither
needs to change when ``REGISTRY_URL`` points here instead of at LiteLLM:

- ``POST /v1/agents`` -- register ``{agent_name, agent_card_params, static_headers?}``
- ``GET /v1/agents`` -- a bare list of ``{agent_id, agent_name, agent_card_params}``
- ``DELETE /v1/agents/{agent_id}``
- ``GET /a2a/{agent_name}`` -- the registered card
- ``POST /a2a/{agent_name}`` -- forward an A2A JSON-RPC call to the agent's card URL,
  with its registered ``static_headers``, streaming the response back unchanged

Registrations live in one Valkey hash so every worker sees the same set and they survive
a backend restart (agents only register when *they* start). A re-registering agent
overwrites its own entry; ``make clear-agent-registry`` wipes the hash.

Every route requires ``Authorization: Bearer <AGENT_SECRET>``. These are called by
agents, never the browser, so the session-cookie auth in :mod:`app.security` does not
apply. ``static_headers`` hold agent credentials and are never returned.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.config import settings
from app.redis_client import RedisClient, get_redis

logger = logging.getLogger(__name__)

REGISTRY_KEY = "prometheus:agent-registry"

# Matches the client-agent's own dispatch timeout (tool_discovery.call_a2a_agent):
# research agents can run for minutes, and the proxy must not be the first to give up.
A2A_PROXY_TIMEOUT_S = 900.0

# Hop-by-hop or recomputed headers that must not be copied between the two legs.
_DROP_RESPONSE_HEADERS = {"content-length", "transfer-encoding", "connection", "content-encoding"}
_FORWARD_REQUEST_HEADERS = ("content-type", "accept", "a2a-version")


def require_agent_secret(request: Request) -> None:
    """Reject any caller that does not present ``Bearer <AGENT_SECRET>``.

    Fails closed: with no secret configured, nothing can register or dispatch.
    """
    expected = settings.agent_secret
    if not expected:
        raise HTTPException(status_code=503, detail="AGENT_SECRET is not configured on the backend")
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing agent credentials")


router = APIRouter(tags=["agent-registry"], dependencies=[Depends(require_agent_secret)])


def _make_client() -> httpx.AsyncClient:
    """The upstream client for one proxied call (a seam for tests)."""
    return httpx.AsyncClient(timeout=A2A_PROXY_TIMEOUT_S)


class AgentRegistration(BaseModel):
    agent_name: str = Field(min_length=1)
    agent_card_params: Dict[str, Any]
    static_headers: Dict[str, str] = Field(default_factory=dict)


def _public_entry(stored: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "agent_id": stored["agent_name"],
        "agent_name": stored["agent_name"],
        "agent_card_params": stored["agent_card_params"],
    }


async def _load(redis: RedisClient, agent_name: str) -> Dict[str, Any]:
    raw = await redis.hget(REGISTRY_KEY, agent_name)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' is not registered")
    return cast(Dict[str, Any], json.loads(raw))


@router.post("/v1/agents")
async def register_agent(body: AgentRegistration, redis: RedisClient = Depends(get_redis)) -> Dict[str, Any]:
    stored = body.model_dump()
    await redis.hset(REGISTRY_KEY, body.agent_name, json.dumps(stored))
    logger.info("Registered agent '%s' at %s", body.agent_name, body.agent_card_params.get("url", ""))
    return _public_entry(stored)


@router.get("/v1/agents")
async def list_agents(redis: RedisClient = Depends(get_redis)) -> List[Dict[str, Any]]:
    entries = await redis.hgetall(REGISTRY_KEY)
    return [_public_entry(json.loads(raw)) for _, raw in sorted(entries.items())]


@router.delete("/v1/agents/{agent_id}")
async def delete_agent(agent_id: str, redis: RedisClient = Depends(get_redis)) -> Dict[str, str]:
    if not await redis.hdel(REGISTRY_KEY, agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' is not registered")
    logger.info("Removed agent registration '%s'", agent_id)
    return {"agent_id": agent_id}


@router.get("/a2a/{agent_name}")
async def get_agent_card(agent_name: str, redis: RedisClient = Depends(get_redis)) -> Dict[str, Any]:
    return cast(Dict[str, Any], (await _load(redis, agent_name))["agent_card_params"])


@router.post("/a2a/{agent_name}")
async def proxy_a2a(agent_name: str, request: Request, redis: RedisClient = Depends(get_redis)) -> Any:
    stored = await _load(redis, agent_name)
    target: Optional[str] = (stored["agent_card_params"].get("url") or "").strip() or None
    if target is None:
        raise HTTPException(status_code=502, detail=f"Agent '{agent_name}' registered without a URL")

    headers = {name: value for name in _FORWARD_REQUEST_HEADERS if (value := request.headers.get(name))}
    # The agent's own credentials replace the caller's registry token.
    headers.update(stored.get("static_headers") or {})

    client = _make_client()
    try:
        upstream = await client.send(
            client.build_request("POST", target, content=await request.body(), headers=headers),
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("A2A proxy to '%s' at %s failed: %s", agent_name, target, exc)
        raise HTTPException(status_code=502, detail=f"Agent '{agent_name}' is unreachable") from exc

    async def _close() -> None:
        await upstream.aclose()
        await client.aclose()

    content_type = (upstream.headers.get("content-type") or "").lower()
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}
    if "text/event-stream" in content_type or "ndjson" in content_type:
        return StreamingResponse(
            _iter_bytes(upstream),
            status_code=upstream.status_code,
            headers=response_headers,
            background=BackgroundTask(_close),
        )

    try:
        body = await upstream.aread()
    finally:
        await _close()
    try:
        return JSONResponse(status_code=upstream.status_code, content=json.loads(body))
    except ValueError:
        return StreamingResponse(iter([body]), status_code=upstream.status_code, headers=response_headers)


async def _iter_bytes(upstream: httpx.Response) -> AsyncIterator[bytes]:
    # Decoded, not raw: content-encoding is dropped from the relayed headers above.
    async for chunk in upstream.aiter_bytes():
        yield chunk
