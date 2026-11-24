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

- ``POST /v1/agents`` -- register ``{agent_name, agent_card_params, static_headers?}``; the
  backend also stores ``registered_at`` (ISO 8601 UTC, set at write time, never returned)
- ``GET /v1/agents`` -- a bare list of ``{agent_id, agent_name, agent_card_params}``
- ``DELETE /v1/agents/{agent_id}``
- ``GET /a2a/{agent_name}`` -- the registered card
- ``POST /a2a/{agent_name}`` -- forward an A2A JSON-RPC call to the agent's card URL,
  with its registered ``static_headers``, streaming the response back unchanged

Registrations live in one Valkey hash so every worker sees the same set and they survive
a backend restart (agents only register when *they* start). A re-registering agent
overwrites its own entry; ``make clear-agent-registry`` wipes the hash.

With ``AGENT_IDENTITY_SOURCE=istio`` a registration also binds the caller's SPIFFE ID
(from the Istio sidecar) to the agent name, and records it in the reverse index
:data:`app.agent_identity.SPIFFE_INDEX_KEY`. An entry bound to one workload can only be
overwritten or deleted by that workload, and one workload holds one name: registering
under a new name (an agent renamed but keeping its ServiceAccount) replaces the entry it
held under the old one. An entry with no binding (written in ``trusted-name`` mode, or
before the switch to ``istio``) is open: the first workload to register it under
``istio`` claims it, and any workload can delete it -- clear the registry when switching
modes. Later ``/v1`` routes resolve the caller through the index
(:mod:`app.agent_identity`). The check and the write run in one ``WATCH``/``MULTI``
transaction over both hashes, so concurrent registrations can't both pass the check.

Every route requires ``Authorization: Bearer <AGENT_SECRET>``. These are called by
agents, never the browser, so the session-cookie auth in :mod:`app.security` does not
apply. ``static_headers`` hold agent credentials and are never returned.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio.client import Pipeline
from starlette.background import BackgroundTask

from app.agent_identity import SPIFFE_INDEX_KEY, caller_spiffe_id
from app.agent_store import REGISTRY_KEY, load_all, load_entry
from app.api_responses import AGENT_SECRET_RESPONSES, Responses, error
from app.config import settings
from app.openapi import TAG_AGENT_REGISTRY
from app.redis_client import RedisClient, get_redis

logger = logging.getLogger(__name__)

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


router = APIRouter(
    tags=[TAG_AGENT_REGISTRY], dependencies=[Depends(require_agent_secret)], responses=AGENT_SECRET_RESPONSES
)


def _make_client() -> httpx.AsyncClient:
    """The upstream client for one proxied call (a seam for tests)."""
    return httpx.AsyncClient(timeout=A2A_PROXY_TIMEOUT_S)


class AgentRegistration(BaseModel):
    # One path segment: the name is the key in /a2a/{agent_name}, /v1/agents/{agent_id}
    # and /api/agents/{agent_name}, so a "/" would make the agent unreachable by name.
    agent_name: str = Field(min_length=1, pattern=r"^[^/]+$")
    agent_card_params: Dict[str, Any]
    static_headers: Dict[str, str] = Field(default_factory=dict)


def _require_spiffe_id(request: Request) -> Optional[str]:
    """The caller's SPIFFE ID under Istio (401 without one); ``None`` in trusted-name mode."""
    if settings.agent_identity_source != "istio":
        return None
    spiffe_id = caller_spiffe_id(request)
    if spiffe_id is None:
        raise HTTPException(status_code=401, detail="No verified workload identity on the request")
    return spiffe_id


def _public_entry(stored: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "agent_id": stored["agent_name"],
        "agent_name": stored["agent_name"],
        "agent_card_params": stored["agent_card_params"],
    }


# The errors the individual routes raise, beyond the router-wide agent-secret ones.
_NOT_REGISTERED: Responses = error(
    404, "No agent is registered under that name.", "Agent 'thermal-agent' is not registered"
)
# Under AGENT_IDENTITY_SOURCE=istio, a name stays bound to the workload that registered it.
_OTHER_WORKLOAD: Responses = error(
    403,
    "Under Istio identity, the name is registered by a different workload.",
    "Agent 'thermal-agent' is registered by another workload",
)
_UNREACHABLE: Responses = error(
    502,
    "The agent is registered without a URL, or the backend couldn't connect to it.",
    "Agent 'thermal-agent' registered without a URL",
    "Agent 'thermal-agent' is unreachable",
)


async def _load(redis: RedisClient, agent_name: str) -> Dict[str, Any]:
    stored = await load_entry(redis, agent_name)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' is not registered")
    return stored


def _bound(raw: Optional[str | bytes]) -> Optional[str]:
    """The SPIFFE ID a stored entry is bound to, if any."""
    return None if raw is None else cast(Optional[str], json.loads(raw).get("spiffe_id"))


@router.post("/v1/agents", responses=_OTHER_WORKLOAD)
async def register_agent(
    body: AgentRegistration, request: Request, redis: RedisClient = Depends(get_redis)
) -> Dict[str, Any]:
    name = body.agent_name
    stored = body.model_dump()
    stored["registered_at"] = datetime.now(timezone.utc).isoformat()
    spiffe_id = _require_spiffe_id(request)
    if spiffe_id is not None:
        stored["spiffe_id"] = spiffe_id

    async def write(pipe: Pipeline) -> None:
        # Reads run immediately (the keys are watched); writes queue after multi().
        bound = _bound(await pipe.hget(REGISTRY_KEY, name))
        if spiffe_id is not None and bound not in (None, spiffe_id):
            raise HTTPException(status_code=403, detail=f"Agent '{name}' is registered by another workload")
        # Under Istio, a different name this workload still holds (the agent was renamed).
        old_name: Optional[str] = None
        if spiffe_id is not None:
            # decode_responses=True: hash values are str.
            indexed = cast(Optional[str], await pipe.hget(SPIFFE_INDEX_KEY, spiffe_id))
            if indexed is not None and indexed != name and _bound(await pipe.hget(REGISTRY_KEY, indexed)) == spiffe_id:
                old_name = indexed
        pipe.multi()
        if bound is not None and bound != spiffe_id:
            pipe.hdel(SPIFFE_INDEX_KEY, bound)  # trusted-name mode overwrote a bound entry
        if old_name is not None:
            pipe.hdel(REGISTRY_KEY, old_name)
            logger.info("Workload %s re-registered as '%s'; removed its entry '%s'", spiffe_id, name, old_name)
        pipe.hset(REGISTRY_KEY, name, json.dumps(stored))
        if spiffe_id is not None:
            pipe.hset(SPIFFE_INDEX_KEY, spiffe_id, name)

    await redis.transaction(write, REGISTRY_KEY, SPIFFE_INDEX_KEY)
    logger.info("Registered agent '%s' at %s", name, body.agent_card_params.get("url", ""))
    return _public_entry(stored)


@router.get("/v1/agents")
async def list_agents(redis: RedisClient = Depends(get_redis)) -> List[Dict[str, Any]]:
    return [_public_entry(stored) for stored in await load_all(redis)]


@router.delete("/v1/agents/{agent_id}", responses={**_NOT_REGISTERED, **_OTHER_WORKLOAD})
async def delete_agent(agent_id: str, request: Request, redis: RedisClient = Depends(get_redis)) -> Dict[str, str]:
    spiffe_id = _require_spiffe_id(request)

    async def remove(pipe: Pipeline) -> None:
        raw = await pipe.hget(REGISTRY_KEY, agent_id)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' is not registered")
        bound = _bound(raw)
        if spiffe_id is not None and bound not in (None, spiffe_id):
            raise HTTPException(status_code=403, detail=f"Agent '{agent_id}' is registered by another workload")
        # Under trusted-name the index may already point this SPIFFE ID elsewhere.
        indexed = bound if bound is not None and await pipe.hget(SPIFFE_INDEX_KEY, bound) == agent_id else None
        pipe.multi()
        pipe.hdel(REGISTRY_KEY, agent_id)
        if indexed is not None:
            pipe.hdel(SPIFFE_INDEX_KEY, indexed)

    await redis.transaction(remove, REGISTRY_KEY, SPIFFE_INDEX_KEY)
    logger.info("Removed agent registration '%s'", agent_id)
    return {"agent_id": agent_id}


@router.get("/a2a/{agent_name}", responses=_NOT_REGISTERED)
async def get_agent_card(agent_name: str, redis: RedisClient = Depends(get_redis)) -> Dict[str, Any]:
    return cast(Dict[str, Any], (await _load(redis, agent_name))["agent_card_params"])


@router.post("/a2a/{agent_name}", responses={**_NOT_REGISTERED, **_UNREACHABLE})
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
