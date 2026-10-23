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

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional

from prometheus_api.llm_client import AsyncLLMClient, LLMConfig

from capability_cache import get_capability_cache
from tool_discovery import get_all_tools_dynamic
from workflow_library import get_workflow_registry

logger = logging.getLogger(__name__)

AGENT_PORT = int(os.getenv("AGENT_PORT", "8000"))
DISCOVERY_REFRESH_SECONDS = int(os.getenv("DISCOVERY_REFRESH_SECONDS", "300"))
ENABLE_WORKFLOW_LIBRARY = os.getenv("ENABLE_WORKFLOW_LIBRARY", "true").lower() in {"1", "true", "yes"}

_tools_cache = None
_refresh_task: Optional[asyncio.Task] = None
_refresh_lock: Optional[asyncio.Lock] = None
_status_redis_client: Any = None
StatusEmitter = Callable[[str], Awaitable[None]]
_status_emitters: ContextVar[tuple[StatusEmitter, ...]] = ContextVar(
    "status_emitters",
    default=(),
)
_status_emit_tasks: ContextVar[Optional[List[asyncio.Task]]] = ContextVar(
    "status_emit_tasks",
    default=None,
)
_status_emit_tail: ContextVar[Optional[asyncio.Task]] = ContextVar(
    "status_emit_tail",
    default=None,
)


def create_llm() -> AsyncLLMClient:
    """Create a provider-agnostic async client."""
    config = LLMConfig.from_env()
    return AsyncLLMClient(config=config, app_name="Client Agent")


def _get_status_redis_client():
    """Lazy Redis client for status history updates."""
    global _status_redis_client
    if _status_redis_client is None:
        from prometheus_api.redis_utils import create_redis_client

        _status_redis_client = create_redis_client(ping=False)
        if _status_redis_client is None:
            raise RuntimeError("Redis client could not be created; check REDIS_URL/REDIS_PASSWORD")
    return _status_redis_client


async def _safe_emit_status(emitter: StatusEmitter, message: str) -> None:
    try:
        await emitter(message)
    except Exception as exc:
        logger.warning("[STATUS] Failed to emit streaming status update: %s", exc)


async def _emit_status_to_all(
    emitters: tuple[StatusEmitter, ...],
    message: str,
    previous: Optional[asyncio.Task],
) -> None:
    if previous is not None:
        await previous
    for emitter in emitters:
        await _safe_emit_status(emitter, message)


def _emit_status_update(message: str) -> None:
    emitters = _status_emitters.get()
    if not emitters:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    task_list = _status_emit_tasks.get()
    task = loop.create_task(
        _emit_status_to_all(
            emitters,
            message,
            _status_emit_tail.get(),
        )
    )
    _status_emit_tail.set(task)
    if task_list is not None:
        task_list.append(task)


@contextmanager
def status_stream(emitter: StatusEmitter) -> Iterator[List[asyncio.Task]]:
    """Register a request-local status emitter for the current async context."""
    tasks: List[asyncio.Task] = []
    emitter_token = _status_emitters.set((*_status_emitters.get(), emitter))
    tasks_token = _status_emit_tasks.set(tasks)
    tail_token = _status_emit_tail.set(None)
    try:
        yield tasks
    finally:
        _status_emitters.reset(emitter_token)
        _status_emit_tasks.reset(tasks_token)
        _status_emit_tail.reset(tail_token)


async def wait_for_status_stream(tasks: List[asyncio.Task]) -> None:
    pending = [task for task in tasks if not task.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def store_status_update(conversation_id: Optional[str], message: str, final: bool = False) -> None:
    """Stream a status message for the active request and persist it in Redis."""
    conv_id = str(conversation_id or "").strip()
    text = str(message or "").strip()
    if not conv_id or not text:
        return

    _emit_status_update(text)

    try:
        status_data = {
            "message": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "final": final,
        }
        redis_client = _get_status_redis_client()
        redis_client.set(f"agent:status:{conv_id}", json.dumps(status_data), ex=900)
        history_key = f"agent:status_history:{conv_id}"
        redis_client.rpush(history_key, json.dumps(status_data))
        redis_client.ltrim(history_key, -300, -1)
        redis_client.expire(history_key, 900)
    except Exception as exc:
        logger.warning("[STATUS] Failed to store status update: %s", exc)


async def initialize_tools():
    """Initialize tools on startup - called once.

    Discovers tools dynamically from the registry by querying
    registered agents and their capabilities.
    """
    global _tools_cache

    print("Discovering tools from registry...")
    _tools_cache = await get_all_tools_dynamic()
    print(f"Initialized {len(_tools_cache)} tools")


def get_refresh_lock() -> asyncio.Lock:
    """Get a singleton lock used for coordinated discovery refresh."""
    global _refresh_lock
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    return _refresh_lock


async def refresh_dynamic_components(trigger: str = "manual") -> Dict[str, Any]:
    """Refresh discovery-dependent runtime components."""
    lock = get_refresh_lock()
    async with lock:
        print(f"Refreshing dynamic components (trigger={trigger})...")
        await initialize_tools()
        cache = get_capability_cache()
        await cache.refresh()
        workflow_refresh = None
        if ENABLE_WORKFLOW_LIBRARY:
            registry = get_workflow_registry()
            capabilities = await cache.get_capabilities()
            get_agent_cards = getattr(cache, "get_agent_cards", None)
            agent_cards = await get_agent_cards() if callable(get_agent_cards) else []
            workflow_refresh = registry.refresh(capabilities, agent_cards=agent_cards)
        return {
            "status": "ok",
            "trigger": trigger,
            "tools": len(_tools_cache or []),
            "workflow_library": workflow_refresh,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


async def discovery_refresh_loop() -> None:
    """Periodically refresh tools and capability cache for runtime discovery."""
    interval = max(30, DISCOVERY_REFRESH_SECONDS)
    while True:
        await asyncio.sleep(interval)
        try:
            await refresh_dynamic_components(trigger="background")
        except Exception as e:
            logger.warning("[WARN] Background discovery refresh failed: %s", e)


def create_tools():
    """Get all available analysis tools from cache."""
    if _tools_cache is None:
        raise RuntimeError("Tools not initialized. Call initialize_tools() first.")
    return _tools_cache


async def refresh_discovery():
    """Manually refresh dynamic discovery artifacts without restarting the service."""
    result = await refresh_dynamic_components(trigger="api")
    return result
