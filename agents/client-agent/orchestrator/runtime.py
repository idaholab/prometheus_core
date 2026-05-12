from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from langchain_anthropic import ChatAnthropic

from capability_cache import get_capability_cache
from tool_discovery import get_all_tools_dynamic
from workflow_library import get_workflow_registry

AGENT_PORT = int(os.getenv("AGENT_PORT", "8000"))
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-6")
DISCOVERY_REFRESH_SECONDS = int(os.getenv("DISCOVERY_REFRESH_SECONDS", "300"))
ENABLE_WORKFLOW_LIBRARY = os.getenv("ENABLE_WORKFLOW_LIBRARY", "true").lower() in {"1", "true", "yes"}

_tools_cache = None
_refresh_task: Optional[asyncio.Task] = None
_refresh_lock: Optional[asyncio.Lock] = None
_status_redis_client: Any = None


def create_llm():
    """Create the Claude LLM instance."""
    return ChatAnthropic(
        model=MODEL_NAME,
        temperature=0,
        max_tokens=4096,
    )


def _get_status_redis_client():
    """Lazy Redis client for status history updates."""
    global _status_redis_client
    if _status_redis_client is None:
        import redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_password = os.getenv("REDIS_PASSWORD")
        _status_redis_client = redis.Redis.from_url(
            redis_url,
            password=redis_password,
            decode_responses=True
        )
    return _status_redis_client


def store_status_update(conversation_id: Optional[str], message: str, final: bool = False) -> None:
    """Store a status message in Redis for frontend progress rendering."""
    conv_id = str(conversation_id or "").strip()
    text = str(message or "").strip()
    if not conv_id or not text:
        return

    try:
        status_data = {
            "message": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "final": final,
        }
        redis_client = _get_status_redis_client()
        redis_client.setex(f"agent:status:{conv_id}", 900, json.dumps(status_data))
        history_key = f"agent:status_history:{conv_id}"
        redis_client.rpush(history_key, json.dumps(status_data))
        redis_client.ltrim(history_key, -300, -1)
        redis_client.expire(history_key, 900)
    except Exception as exc:
        print(f"[STATUS] Failed to store status update: {exc}")


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
            workflow_refresh = registry.refresh(capabilities)
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
            print(f"[WARN] Background discovery refresh failed: {e}")


def create_tools():
    """Get all available analysis tools from cache."""
    if _tools_cache is None:
        raise RuntimeError("Tools not initialized. Call initialize_tools() first.")
    return _tools_cache


async def refresh_discovery():
    """Manually refresh dynamic discovery artifacts without restarting the service."""
    result = await refresh_dynamic_components(trigger="api")
    return result


async def get_status(conversation_id: str):
    """
    Get the current status of an ongoing analysis.

    Used by the frontend to poll for status updates during long-running operations.
    """
    import redis
    import os

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_password = os.getenv("REDIS_PASSWORD")
    try:
        redis_client = redis.Redis.from_url(
            redis_url,
            password=redis_password,
            decode_responses=True
        )
        key = f"agent:status:{conversation_id}"
        status_data = redis_client.get(key)
        history_key = f"agent:status_history:{conversation_id}"
        history_raw = redis_client.lrange(history_key, 0, -1)
        history: List[Dict[str, Any]] = []
        for item in history_raw:
            try:
                parsed = json.loads(item)
                if isinstance(parsed, dict):
                    history.append(parsed)
            except Exception:
                continue

        if status_data:
            print(f"[STATUS] Found status for {conversation_id}: {status_data[:100]}...")
            payload = json.loads(status_data)
            if history:
                payload["history"] = history
            return payload
        if history:
            latest = history[-1]
            latest["history"] = history
            return latest
        else:
            # Check if there are any status keys to help debug
            all_keys = redis_client.keys("agent:status:*")
            print(f"[STATUS] No status for {conversation_id}. Available keys: {all_keys[:5]}")
            return {"message": "No status available", "final": False}
    except Exception as e:
        print(f"[STATUS] Error: {e}")
        return {"message": f"Error fetching status: {e}", "final": False}
