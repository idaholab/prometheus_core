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

"""LiteLLM agent registry client used by Prometheus agents."""

import asyncio
import logging
import math
import os
import time
from typing import Any, Dict, Optional

import httpx
from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict

logger = logging.getLogger(__name__)


class AgentRegistryClient:
    """Client for registering A2A agent cards with LiteLLM's agent registry."""

    DEFAULT_MAX_RETRIES = 10
    # Seconds between registry checks after startup (REGISTRY_CHECK_INTERVAL_SECONDS).
    DEFAULT_CHECK_INTERVAL = 5.0
    # Shortest accepted interval: every running agent makes the check, so a typo
    # such as 1e-9 must not turn it into a hot loop against the registry.
    MIN_CHECK_INTERVAL = 0.1

    def __init__(
        self,
        registry_url: str,
        *,
        master_key: str = "",
        agent_secret: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.registry_url = str(registry_url or "").strip()
        self.master_key = str(master_key or "")
        self.agent_secret = agent_secret
        self.timeout = timeout

    @classmethod
    def from_env(cls, registry_url: str) -> "AgentRegistryClient":
        """Create a registry client using environment-based credentials."""
        return cls(
            registry_url,
            master_key=os.getenv("LITELLM_MASTER_KEY", ""),
            agent_secret=os.getenv("AGENT_SECRET"),
        )

    @property
    def headers(self) -> Dict[str, str]:
        """Return LiteLLM admin auth headers without exposing secret values in logs."""
        if not self.master_key:
            return {}
        return {"Authorization": f"Bearer {self.master_key}"}

    @staticmethod
    def agent_name(agent_card: AgentCard) -> str:
        """Return the LiteLLM route key for an agent card."""
        return agent_card.name.lower().replace(" ", "-")

    @staticmethod
    def resolve_max_retries(max_retries: Optional[int]) -> int:
        """Resolve registry retry count without allowing bad config to block startup."""
        default_retries = AgentRegistryClient.DEFAULT_MAX_RETRIES
        raw_value: Any = max_retries
        source = "max_retries"
        if raw_value is None:
            raw_value = os.getenv("REGISTRY_MAX_RETRIES")
            source = "REGISTRY_MAX_RETRIES"
        if raw_value in (None, ""):
            return default_retries

        try:
            resolved = int(raw_value)
        except (TypeError, ValueError):
            logger.warning(f"Invalid {source}={raw_value!r}; using {default_retries}")
            return default_retries

        if resolved < 0:
            logger.warning(f"Invalid {source}={raw_value!r}; using 0")
            return 0
        return resolved

    @classmethod
    def resolve_check_interval(cls, raw_value: Optional[str] = None) -> float:
        """Seconds between registry checks after startup; 0 disables them.

        Reads ``REGISTRY_CHECK_INTERVAL_SECONDS`` when ``raw_value`` is None. Unset or
        empty means the default. A value that is not a finite number, or is negative,
        logs a warning and uses the default; a positive value below
        ``MIN_CHECK_INTERVAL`` is raised to it. Bad config never blocks startup.
        """
        source = "REGISTRY_CHECK_INTERVAL_SECONDS"
        raw = (os.getenv(source) if raw_value is None else raw_value) or ""
        raw = raw.strip()
        default = cls.DEFAULT_CHECK_INTERVAL
        if not raw:  # unset or empty (compose forwards empty for "use the default")
            return default
        try:
            value = float(raw)
        except ValueError:
            value = math.nan
        if not math.isfinite(value) or value < 0:
            logger.warning("Invalid %s=%r; using %g", source, raw, default)
            return default
        if 0 < value < cls.MIN_CHECK_INTERVAL:
            logger.warning(
                "%s=%r is below %g; using %g",
                source,
                raw,
                cls.MIN_CHECK_INTERVAL,
                cls.MIN_CHECK_INTERVAL,
            )
            return cls.MIN_CHECK_INTERVAL
        return value

    @staticmethod
    def _registry_entries(body: Any) -> list:
        """The entry list of a ``GET /v1/agents`` body.

        Accepts a bare list or one wrapped in ``data`` / ``agents``, as the
        client-agent's discovery does. Raises ``ValueError`` on anything else, so an
        unexpected body is reported as a failed check rather than read as "no
        agents" (which would re-register on every check).
        """
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in ("data", "agents"):
                wrapped = body.get(key)
                if isinstance(wrapped, list):
                    return wrapped
        raise ValueError(f"unexpected registry listing: {type(body).__name__}")

    def build_payload(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """Build the LiteLLM registration payload without logging secret-bearing values."""
        agent_name = self.agent_name(agent_card)
        agent_card_params = dict(raw_agent_card or MessageToDict(agent_card))
        jsonrpc_interface = next(
            (
                interface
                for interface in agent_card.supported_interfaces
                if interface.protocol_binding.upper() == "JSONRPC"
            ),
            None,
        )
        if jsonrpc_interface is not None:
            # LiteLLM's registry keeps the upstream route in the legacy top-level
            # URL fields even when it serves a protocol-v1 supportedInterfaces card.
            agent_card_params["url"] = jsonrpc_interface.url
            agent_card_params["protocolVersion"] = jsonrpc_interface.protocol_version
        registration_payload: Dict[str, Any] = {
            "agent_name": agent_name,
            "agent_card_params": agent_card_params,
        }
        if self.agent_secret:
            registration_payload["static_headers"] = {
                "Authorization": f"Bearer {self.agent_secret}",
            }
        return agent_name, registration_payload

    def register_once(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Perform one registration attempt, raising on any failure."""
        agent_name, registration_payload = self.build_payload(
            agent_card,
            raw_agent_card=raw_agent_card,
        )

        with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
            # A POST replaces any entry of the same name (the registry keys entries by
            # agent_name), so there is no delete first: a delete would leave a window
            # in which the agent is not listed, and same-name replicas would delete
            # each other's entry.
            logger.info("Registering '%s' with LiteLLM at %s", agent_name, self.registry_url)
            response = client.post(f"{self.registry_url}/v1/agents", json=registration_payload)
            response.raise_for_status()
            logger.info("Registered '%s' with LiteLLM at %s", agent_name, self.registry_url)

    async def register_once_async(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Perform one async registration attempt, raising on any failure."""
        agent_name, registration_payload = self.build_payload(
            agent_card,
            raw_agent_card=raw_agent_card,
        )

        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            # A POST replaces any entry of the same name (the registry keys entries by
            # agent_name), so there is no delete first: a delete would leave a window
            # in which the agent is not listed, and same-name replicas would delete
            # each other's entry.
            logger.info("Registering '%s' with LiteLLM at %s", agent_name, self.registry_url)
            response = await client.post(
                f"{self.registry_url}/v1/agents",
                json=registration_payload,
            )
            response.raise_for_status()
            logger.info("Registered '%s' with LiteLLM at %s", agent_name, self.registry_url)

    async def is_registered_async(self, agent_card: AgentCard) -> bool:
        """Whether the registry currently lists this agent, by name.

        Raises on a transport or HTTP error, so a registry that is down is not
        mistaken for one that has forgotten the agent.
        """
        agent_name = self.agent_name(agent_card)
        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            response = await client.get(f"{self.registry_url}/v1/agents")
            response.raise_for_status()
            entries = self._registry_entries(response.json())
        return any(
            isinstance(entry, dict) and entry.get("agent_name") == agent_name for entry in entries
        )

    async def keep_registered_async(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
        interval: float = DEFAULT_CHECK_INTERVAL,
    ) -> None:
        """Re-register whenever the registry no longer lists this agent.

        Registration happens once at startup, so a registry that restarts or is
        cleared while the agent keeps running (``make up`` clears it on every
        launch) silently drops the agent from discovery until the agent itself
        restarts. This loop checks every ``interval`` seconds and re-registers
        when the entry is gone. A check that fails (registry down) is logged and
        retried on the next tick, and so is a registry that was not up when
        startup registration gave up. Runs until cancelled.

        Matching is by agent name only: same-name replicas share one entry, which
        should carry their shared service address (``EXTERNAL_AGENT_URL``).
        """
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError(f"interval must be a positive number of seconds, got {interval!r}")
        interval = max(interval, self.MIN_CHECK_INTERVAL)
        while True:
            await asyncio.sleep(interval)
            try:
                if await self.is_registered_async(agent_card):
                    continue
                logger.warning(
                    "'%s' is no longer listed by the registry at %s; re-registering",
                    self.agent_name(agent_card),
                    self.registry_url,
                )
                await self.register_once_async(agent_card, raw_agent_card=raw_agent_card)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # repr: some httpx errors (ReadTimeout) have an empty str()
                logger.warning("Registry check failed (%r); will retry in %gs", e, interval)

    def register_with_retries(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        initial_delay: float = 2.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        """Register with exponential backoff until success or retry exhaustion."""
        resolved_max_retries = self.resolve_max_retries(max_retries)

        delay = initial_delay
        for attempt in range(resolved_max_retries + 1):
            try:
                self.register_once(agent_card, raw_agent_card=raw_agent_card)
                return
            except Exception as e:
                if attempt >= resolved_max_retries:
                    logger.error(
                        f"Failed to register with LiteLLM after {resolved_max_retries + 1} "
                        f"attempt(s): {e}"
                    )
                    logger.warning("Continuing without registration")
                    return
                logger.warning(
                    f"Registry registration attempt {attempt + 1}/{resolved_max_retries + 1} "
                    f"failed: {e}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)

    async def register_with_retries_async(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        initial_delay: float = 2.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        """Register asynchronously with exponential backoff until success or retry exhaustion."""
        resolved_max_retries = self.resolve_max_retries(max_retries)

        delay = initial_delay
        for attempt in range(resolved_max_retries + 1):
            try:
                await self.register_once_async(agent_card, raw_agent_card=raw_agent_card)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt >= resolved_max_retries:
                    logger.error(
                        f"Failed to register with LiteLLM after {resolved_max_retries + 1} "
                        f"attempt(s): {e}"
                    )
                    logger.warning("Continuing without registration")
                    return
                logger.warning(
                    f"Registry registration attempt {attempt + 1}/{resolved_max_retries + 1} "
                    f"failed: {e}. Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
