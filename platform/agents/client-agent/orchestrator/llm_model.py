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

"""Resolve the orchestrator's semantic LLM alias to the deployment's provider model."""

from __future__ import annotations

import logging
import time

import httpx
from prometheus_api.llm_client import LLMConfig

from tool_discovery import _litellm_headers

from .runtime import DISCOVERY_REFRESH_SECONDS

logger = logging.getLogger(__name__)

ORCHESTRATOR_LLM_ALIAS = "medium"

# alias -> (provider model, monotonic time it was resolved)
_cache: dict[str, tuple[str, float]] = {}


def _reset_cache() -> None:
    """Drop every cached resolution."""
    _cache.clear()


def cached_llm_model(alias: str = ORCHESTRATOR_LLM_ALIAS) -> str | None:
    """Return the cached provider model for ``alias`` while it is fresh, without I/O."""
    entry = _cache.get(alias)
    if entry is None:
        return None
    model, resolved_at = entry
    if DISCOVERY_REFRESH_SECONDS > 0 and time.monotonic() - resolved_at >= DISCOVERY_REFRESH_SECONDS:
        return None
    return model


async def _resolve_from_proxy(proxy_url: str, alias: str) -> str | None:
    async with httpx.AsyncClient(timeout=2.0, headers=_litellm_headers()) as client:
        response = await client.get(f"{proxy_url.rstrip('/')}/model/info")
        response.raise_for_status()
        raw = response.json()

    # LiteLLM returns a list directly or wrapped in a key — handle both
    entries = raw if isinstance(raw, list) else raw.get("data", [])
    for entry in entries:
        if entry.get("model_name") == alias:
            model = (entry.get("litellm_params") or {}).get("model")
            return str(model) if model else None
    return None


async def resolve_llm_model(alias: str = ORCHESTRATOR_LLM_ALIAS) -> str | None:
    """Return the provider model the deployment binds to ``alias``, or None.

    Proxy mode reads ``/model/info`` from LiteLLM; fallback mode reads the
    fallback YAML. A non-None result is cached for DISCOVERY_REFRESH_SECONDS.
    """
    cached = cached_llm_model(alias)
    if cached is not None:
        return cached

    try:
        config = LLMConfig.from_env()
        if config.proxy_url:
            model = await _resolve_from_proxy(config.proxy_url, alias)
        else:
            fallback = config.load_fallback_models().get(alias)
            model = fallback.provider_model if fallback else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not resolve LLM alias %r: %s", alias, type(exc).__name__)
        return None

    if model is None:
        logger.warning("LLM alias %r is not configured in the deployment", alias)
        return None

    _cache[alias] = (model, time.monotonic())
    return model
