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

"""Agent-facing state store: ``/v1/agent-state``. Design: Confluence 44335895.

Two scopes, the same three methods each:

- ``/v1/agent-state/tasks/{task_id}`` -- one A2A task's state, carried across an
  ``INPUT_REQUIRED`` resume. The conversation comes from ``X-Conversation-Id``.
- ``/v1/agent-state/conversations/{conversation_id}`` -- the calling agent's state for
  the whole conversation.

Every call needs ``Bearer <AGENT_SECRET>``, the calling agent's identity
(:func:`app.agent_identity.require_agent_caller`) and the turn's user identity JWT in
``X-User-Token``. The backend takes the user from the JWT, never from the agent, and
checks the user owns the conversation and hasn't deleted it. A record is only visible to the same
``(user, agent, conversation)`` that created it; anything else is 404, the same as
absent.

``GET`` returns the version as an ``ETag``. ``PUT`` needs ``If-None-Match: *`` to
create or ``If-Match: <version>`` to replace (409 on a mismatch, 428 with neither), so
two racing resumes can't silently overwrite each other. ``DELETE`` is idempotent.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from app.agent_identity import AgentCaller, require_agent_caller
from app.config import settings
from app.identity import verify_user_token
from app.openapi import TAG_AGENT_REGISTRY
from app.redis_client import RedisClient, get_redis
from app.routers.agent_registry import require_agent_secret
from app.services.agent_state import (
    AgentStateError,
    AgentStateStore,
    Owner,
    StateRecord,
    conversation_key,
    task_key,
)

router = APIRouter(prefix="/v1/agent-state", tags=[TAG_AGENT_REGISTRY], dependencies=[Depends(require_agent_secret)])

_STATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing or invalid agent credentials or user identity token"},
    404: {"description": "No such conversation, or no state owned by this user, agent and conversation"},
}


class StateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: dict[str, Any]


class StateResponse(BaseModel):
    state: dict[str, Any]
    version: int
    created_at: str
    updated_at: str


def get_agent_state_store(request: Request) -> AgentStateStore:
    return AgentStateStore(
        get_redis(request),
        ttl_seconds=settings.agent_state_ttl_seconds,
        max_bytes=settings.agent_state_max_bytes,
    )


async def _owner(redis: RedisClient, caller: AgentCaller, user_token: Optional[str], conversation_id: str) -> Owner:
    user_id = await verify_user_token(user_token or "")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Missing or invalid user identity token")
    # A soft-deleted conversation is gone for agents too; its records then age out by TTL.
    if (
        not conversation_id
        or not await redis.sismember(f"user:convs:{user_id}", conversation_id)
        or await redis.hget(f"conv:meta:{conversation_id}", "hidden")
    ):
        raise HTTPException(status_code=404, detail="No such conversation")
    return Owner(user_id=user_id, agent=caller.name, conversation_id=conversation_id)


async def task_owner(
    caller: AgentCaller = Depends(require_agent_caller),
    user_token: Optional[str] = Header(default=None, alias="X-User-Token"),
    conversation_id: str = Header(default="", alias="X-Conversation-Id"),
    redis: RedisClient = Depends(get_redis),
) -> Owner:
    return await _owner(redis, caller, user_token, conversation_id)


async def conversation_owner(
    conversation_id: str,
    caller: AgentCaller = Depends(require_agent_caller),
    user_token: Optional[str] = Header(default=None, alias="X-User-Token"),
    redis: RedisClient = Depends(get_redis),
) -> Owner:
    return await _owner(redis, caller, user_token, conversation_id)


def _expected_version(if_match: Optional[str], if_none_match: Optional[str]) -> Optional[int]:
    """``None`` means create (``If-None-Match: *``); otherwise the version to replace."""
    if if_none_match is not None:
        if if_none_match.strip() != "*" or if_match is not None:
            raise HTTPException(status_code=400, detail="Use either If-None-Match: * or If-Match: <version>")
        return None
    if if_match is None:
        raise HTTPException(status_code=428, detail="PUT needs If-None-Match: * or If-Match: <version>")
    try:
        return int(if_match.strip().removeprefix("W/").strip('"'))
    except ValueError:
        raise HTTPException(status_code=400, detail="If-Match must be a state version") from None


def _respond(record: StateRecord, response: Response) -> StateResponse:
    response.headers["ETag"] = f'"{record.version}"'
    return StateResponse(
        state=record.state, version=record.version, created_at=record.created_at, updated_at=record.updated_at
    )


async def _get(store: AgentStateStore, key: str, owner: Owner, response: Response) -> StateResponse:
    record = await store.get(key, owner)
    if record is None:
        raise HTTPException(status_code=404, detail="No such state")
    return _respond(record, response)


async def _put(
    store: AgentStateStore,
    key: str,
    owner: Owner,
    body: StateBody,
    response: Response,
    if_match: Optional[str],
    if_none_match: Optional[str],
) -> StateResponse:
    expected = _expected_version(if_match, if_none_match)
    try:
        record = await store.put(key, owner, body.state, expected_version=expected)
    except AgentStateError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return _respond(record, response)


async def _delete(store: AgentStateStore, key: str, owner: Owner) -> Response:
    try:
        await store.delete(key, owner)
    except AgentStateError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return Response(status_code=204)


_PUT_RESPONSES = {
    **_STATE_RESPONSES,
    409: {"description": "Version mismatch (or the state already exists on create)"},
    413: {"description": "State is larger than the configured limit"},
    428: {"description": "Neither If-None-Match: * nor If-Match was sent"},
}


# --------------------------------------------------------------------------- #
# Task scope
# --------------------------------------------------------------------------- #


@router.get("/tasks/{task_id}", response_model=StateResponse, responses=_STATE_RESPONSES)
async def get_task_state(
    task_id: str,
    response: Response,
    owner: Owner = Depends(task_owner),
    store: AgentStateStore = Depends(get_agent_state_store),
) -> StateResponse:
    return await _get(store, task_key(task_id), owner, response)


@router.put("/tasks/{task_id}", response_model=StateResponse, responses=_PUT_RESPONSES)
async def put_task_state(
    task_id: str,
    body: StateBody,
    response: Response,
    owner: Owner = Depends(task_owner),
    store: AgentStateStore = Depends(get_agent_state_store),
    if_match: Optional[str] = Header(default=None),
    if_none_match: Optional[str] = Header(default=None),
) -> StateResponse:
    return await _put(store, task_key(task_id), owner, body, response, if_match, if_none_match)


@router.delete("/tasks/{task_id}", status_code=204, responses=_STATE_RESPONSES)
async def delete_task_state(
    task_id: str,
    owner: Owner = Depends(task_owner),
    store: AgentStateStore = Depends(get_agent_state_store),
) -> Response:
    return await _delete(store, task_key(task_id), owner)


# --------------------------------------------------------------------------- #
# Conversation scope
# --------------------------------------------------------------------------- #


@router.get("/conversations/{conversation_id}", response_model=StateResponse, responses=_STATE_RESPONSES)
async def get_conversation_state(
    response: Response,
    owner: Owner = Depends(conversation_owner),
    store: AgentStateStore = Depends(get_agent_state_store),
) -> StateResponse:
    return await _get(store, conversation_key(owner.conversation_id, owner.agent), owner, response)


@router.put("/conversations/{conversation_id}", response_model=StateResponse, responses=_PUT_RESPONSES)
async def put_conversation_state(
    body: StateBody,
    response: Response,
    owner: Owner = Depends(conversation_owner),
    store: AgentStateStore = Depends(get_agent_state_store),
    if_match: Optional[str] = Header(default=None),
    if_none_match: Optional[str] = Header(default=None),
) -> StateResponse:
    key = conversation_key(owner.conversation_id, owner.agent)
    return await _put(store, key, owner, body, response, if_match, if_none_match)


@router.delete("/conversations/{conversation_id}", status_code=204, responses=_STATE_RESPONSES)
async def delete_conversation_state(
    owner: Owner = Depends(conversation_owner),
    store: AgentStateStore = Depends(get_agent_state_store),
) -> Response:
    return await _delete(store, conversation_key(owner.conversation_id, owner.agent), owner)
