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

"""Agent status for the browser: the registered agents and whether each one answers.

``GET /api/agents`` lists every entry of the agent registry (the Valkey hash that
:mod:`app.routers.agent_registry` writes), sorted by ``agent_name``;
``GET /api/agents/{agent_name}`` returns one. Each row carries the card's name,
description, version and skills, the time the agent last registered, and
``reachable``: whether ``GET /healthz`` on the origin of the card ``url`` answered 2xx
within :data:`AGENT_PROBE_TIMEOUT_S` during this request. Status is computed live on
every request; nothing is cached or stored.

These are session-cookie routes, separate from the ``AGENT_SECRET`` routes of the
registry, which stay service-to-service. ``static_headers`` and the card ``url`` never
reach this wire. When Valkey is unreachable the list degrades to
``{available: false, agents: []}`` with a 200, and the one-agent route answers 503.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.agent_store import load_all, load_entry
from app.api_responses import AUTH_RESPONSES, error
from app.contract import AgentListResponse, AgentSkillSummary, AgentStatus
from app.openapi import SESSION_COOKIE, TAG_AGENTS
from app.redis_client import RedisClient, get_redis
from app.security import TokenClaims, current_claims

logger = logging.getLogger(__name__)

# The longest time one agent's health probe may take; probes run concurrently, so this is
# also the most a list request waits on agents.
AGENT_PROBE_TIMEOUT_S = 2.0

_REGISTRY_UNAVAILABLE = "Agent registry is unavailable"

router = APIRouter(prefix="/api", tags=[TAG_AGENTS], responses=AUTH_RESPONSES, dependencies=[Depends(SESSION_COOKIE)])


def _make_client() -> httpx.AsyncClient:
    """The client for one request's health probes (a seam for tests)."""
    return httpx.AsyncClient(timeout=AGENT_PROBE_TIMEOUT_S)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _probe(client: httpx.AsyncClient, url: str) -> bool:
    """True when ``GET /healthz`` on the origin of *url* answers 2xx in time.

    Any failure is ``False``: a timeout, a refused connection, a non-2xx, and a card url
    that httpx cannot parse or send (``InvalidURL``, an IDNA ``UnicodeError``), so one
    bad registration cannot fail the whole list.
    """
    if not url:
        return False
    try:
        # httpx applies its timeout per phase (connect, read, ...), so bound the whole call.
        async with asyncio.timeout(AGENT_PROBE_TIMEOUT_S):
            response = await client.get(httpx.URL(url).join("/healthz"))
    except Exception:  # noqa: BLE001 - every failure means "not reachable"
        return False
    return response.is_success


def _text(card: Dict[str, Any], key: str) -> str:
    value = card.get(key)
    return value if isinstance(value, str) else ""


def _skills(agent_name: str, card: Dict[str, Any]) -> list[AgentSkillSummary]:
    """The card's skills that validate. An invalid skill is dropped on its own, so it
    does not take the agent's other skills or card fields with it."""
    raw = card.get("skills")
    if raw is None:
        return []
    if not isinstance(raw, list):
        logger.warning("Agent '%s' has a card whose skills are not a list; returning no skills", agent_name)
        return []
    skills = []
    dropped = 0
    for skill in raw:
        try:
            skills.append(AgentSkillSummary.model_validate(skill))
        except ValidationError:
            dropped += 1
    if dropped:
        # The count only: a ValidationError's text repeats the registrant's input values.
        logger.warning("Agent '%s' has %d malformed skill(s); returning the others", agent_name, dropped)
    return skills


def _to_status(stored: Dict[str, Any], reachable: bool) -> AgentStatus:
    """The status row of one entry. Each card field is checked on its own: a field of the
    wrong type is empty and an invalid skill is dropped, so one malformed value cannot fail
    the row, and one malformed registration cannot fail the whole list."""
    card = stored["agent_card_params"]
    registered_at = stored.get("registered_at")
    return AgentStatus(
        agent_name=stored["agent_name"],
        name=_text(card, "name"),
        description=_text(card, "description"),
        version=_text(card, "version"),
        registered_at=registered_at if isinstance(registered_at, str) else None,
        reachable=reachable,
        skills=_skills(stored["agent_name"], card),
    )


async def _probe_stored(client: httpx.AsyncClient, stored: Dict[str, Any]) -> AgentStatus:
    url = stored["agent_card_params"].get("url")
    url = url.strip() if isinstance(url, str) else ""
    return _to_status(stored, await _probe(client, url))


@router.get("/agents", response_model=AgentListResponse)
async def list_agent_status(
    redis: RedisClient = Depends(get_redis),
    claims: TokenClaims = Depends(current_claims),
) -> AgentListResponse:
    """Every registered agent with its live reachability, sorted by ``agent_name``."""
    checked_at = _now()
    try:
        stored = await load_all(redis)
    except RedisError as exc:
        logger.warning("Agent registry read failed: %s", exc)
        return AgentListResponse(available=False, checked_at=checked_at, agents=[])
    async with _make_client() as client:
        agents = await asyncio.gather(*(_probe_stored(client, entry) for entry in stored))
    return AgentListResponse(available=True, checked_at=checked_at, agents=list(agents))


@router.get(
    "/agents/{agent_name}",
    response_model=AgentStatus,
    responses={
        **error(
            http_status.HTTP_404_NOT_FOUND,
            "No agent is registered under this name.",
            "Agent '<name>' is not registered",
        ),
        **error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "The agent registry (Valkey) is unreachable.",
            _REGISTRY_UNAVAILABLE,
        ),
    },
)
async def get_agent_status(
    agent_name: str,
    redis: RedisClient = Depends(get_redis),
    claims: TokenClaims = Depends(current_claims),
) -> AgentStatus:
    """One registered agent with its live reachability and the time it was checked."""
    checked_at = _now()
    try:
        stored = await load_entry(redis, agent_name)
    except RedisError as exc:
        logger.warning("Agent registry read failed for '%s': %s", agent_name, exc)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=_REGISTRY_UNAVAILABLE) from exc
    if stored is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Agent '{agent_name}' is not registered"
        )
    async with _make_client() as client:
        agent = await _probe_stored(client, stored)
    agent.checked_at = checked_at
    return agent
