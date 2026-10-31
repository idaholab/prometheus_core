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
import contextvars
import logging
import math
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict

logger = logging.getLogger(__name__)

# True while this module's own registry requests run. A context variable is local to
# the task, so the caller's other httpx traffic keeps its logging. httpx logs one INFO
# line per request, which for a check every few seconds floods the agent log.
_registry_request: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "prometheus_registry_request", default=False
)


class _QuietRegistryRequests(logging.Filter):
    """Drop httpx's below-WARNING lines for the registry client's own requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or not _registry_request.get()


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(f, _QuietRegistryRequests) for f in _httpx_logger.filters):
    _httpx_logger.addFilter(_QuietRegistryRequests())


def _redact_url(url: str) -> str:
    """``url`` without any userinfo (credentials before ``@``), for logging."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable registry URL>"
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def _describe_error(error: BaseException) -> str:
    """A log-safe summary of a registry error: its type, plus the status for HTTP errors.

    Never the exception's text: an ``httpx.HTTPStatusError`` message holds the full
    request URL, including any credentials in ``REGISTRY_URL``.
    """
    if isinstance(error, httpx.HTTPStatusError):
        return f"{type(error).__name__} {error.response.status_code}"
    return type(error).__name__


def _already_exists(response: httpx.Response) -> bool:
    """Whether a registration was refused because the name is taken.

    LiteLLM answers ``POST /v1/agents`` for a name it already has with 400 "Agent
    with name X already exists"; the platform backend overwrites instead.
    """
    return response.status_code in (400, 409) and "already exists" in response.text.lower()


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
        logs a warning and uses the default. A positive value below
        ``MIN_CHECK_INTERVAL`` is returned with a warning; ``keep_registered_async``
        raises it to the floor. Bad config never blocks startup.
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
                "%s=%r is below %g; checking every %gs",
                source,
                raw,
                cls.MIN_CHECK_INTERVAL,
                cls.MIN_CHECK_INTERVAL,
            )
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

    @property
    def safe_registry_url(self) -> str:
        """The registry URL without credentials, for logs."""
        return _redact_url(self.registry_url)

    def _existing_entry_id(self, body: Any, agent_name: str) -> str:
        """The ``agent_id`` of the listed entry named ``agent_name``."""
        for entry in self._registry_entries(body):
            if isinstance(entry, dict) and entry.get("agent_name") == agent_name:
                return str(entry["agent_id"])
        raise LookupError(f"the registry says '{agent_name}' exists but does not list it")

    def register_once(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Perform one registration attempt, raising on any failure.

        The platform backend replaces the entry of the same name on a POST, so
        there is normally no delete (a delete first would leave a window in which
        the agent is unlisted). A LiteLLM registry instead refuses a name it already
        has (400 "already exists"); only then is that entry deleted by its
        ``agent_id`` and the POST repeated.
        """
        agent_name, registration_payload = self.build_payload(
            agent_card,
            raw_agent_card=raw_agent_card,
        )
        agents_url = f"{self.registry_url}/v1/agents"
        token = _registry_request.set(True)
        try:
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                logger.info(
                    "Registering '%s' with LiteLLM at %s", agent_name, self.safe_registry_url
                )
                response = client.post(agents_url, json=registration_payload)
                if _already_exists(response):
                    logger.info("'%s' is already registered; replacing its entry", agent_name)
                    listing = client.get(agents_url)
                    listing.raise_for_status()
                    agent_id = self._existing_entry_id(listing.json(), agent_name)
                    client.delete(f"{agents_url}/{agent_id}").raise_for_status()
                    response = client.post(agents_url, json=registration_payload)
                response.raise_for_status()
        finally:
            _registry_request.reset(token)
        logger.info("Registered '%s' with LiteLLM at %s", agent_name, self.safe_registry_url)

    async def register_once_async(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Perform one async registration attempt, raising on any failure.

        Same as ``register_once``: POST, and only when a LiteLLM registry refuses a
        name it already has, delete that entry by its ``agent_id`` and POST again.
        """
        agent_name, registration_payload = self.build_payload(
            agent_card,
            raw_agent_card=raw_agent_card,
        )
        agents_url = f"{self.registry_url}/v1/agents"
        token = _registry_request.set(True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                logger.info(
                    "Registering '%s' with LiteLLM at %s", agent_name, self.safe_registry_url
                )
                response = await client.post(agents_url, json=registration_payload)
                if _already_exists(response):
                    logger.info("'%s' is already registered; replacing its entry", agent_name)
                    listing = await client.get(agents_url)
                    listing.raise_for_status()
                    agent_id = self._existing_entry_id(listing.json(), agent_name)
                    (await client.delete(f"{agents_url}/{agent_id}")).raise_for_status()
                    response = await client.post(agents_url, json=registration_payload)
                response.raise_for_status()
        finally:
            _registry_request.reset(token)
        logger.info("Registered '%s' with LiteLLM at %s", agent_name, self.safe_registry_url)

    async def is_registered_async(self, agent_card: AgentCard) -> bool:
        """Whether the registry currently lists this agent, by name.

        Raises on a transport or HTTP error, so a registry that is down is not
        mistaken for one that has forgotten the agent.
        """
        agent_name = self.agent_name(agent_card)
        token = _registry_request.set(True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                response = await client.get(f"{self.registry_url}/v1/agents")
                response.raise_for_status()
                entries = self._registry_entries(response.json())
        finally:
            _registry_request.reset(token)
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

        An ``interval`` below ``MIN_CHECK_INTERVAL`` is raised to it; this is the
        only place the floor is applied. The first failed check is logged at
        WARNING and repeats at DEBUG until a check succeeds (logged at INFO), so an
        agent with no registry, or a rejected token, does not warn every few seconds.
        """
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError(f"interval must be a positive number of seconds, got {interval!r}")
        interval = max(interval, self.MIN_CHECK_INTERVAL)
        agent_name = self.agent_name(agent_card)
        logger.info(
            "Checking the registry still lists this agent every %gs ('%s' at %s)",
            interval,
            agent_name,
            self.safe_registry_url,
        )
        failing = False
        while True:
            await asyncio.sleep(interval)
            try:
                if not await self.is_registered_async(agent_card):
                    logger.warning(
                        "'%s' is no longer listed by the registry at %s; re-registering",
                        agent_name,
                        self.safe_registry_url,
                    )
                    await self.register_once_async(agent_card, raw_agent_card=raw_agent_card)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if failing:
                    logger.debug("Registry check failed again (%s)", _describe_error(e))
                else:
                    logger.warning(
                        "Registry check failed (%s) at %s; retrying every %gs, "
                        "repeats are logged at DEBUG until a check succeeds",
                        _describe_error(e),
                        self.safe_registry_url,
                        interval,
                    )
                failing = True
                continue
            if failing:
                logger.info("Registry check succeeded again at %s", self.safe_registry_url)
                failing = False

    async def register_and_keep_registered_async(
        self,
        agent_card: AgentCard,
        *,
        raw_agent_card: Optional[Dict[str, Any]] = None,
        interval: float = DEFAULT_CHECK_INTERVAL,
        max_retries: Optional[int] = None,
    ) -> None:
        """Register with the startup retry policy, then keep the agent listed.

        For an agent that overrides ``PrometheusAgent.register_with_registry_async``
        (a custom name or payload): call this from the override with
        ``interval=self.registry_check_interval()``. A registry that is down at
        startup does not raise (the retries give up with a warning and the checks
        join it once it is up). An interval of 0 registers once and returns;
        otherwise this runs until cancelled.
        """
        await self.register_with_retries_async(
            agent_card, raw_agent_card=raw_agent_card, max_retries=max_retries
        )
        if interval == 0:
            return
        await self.keep_registered_async(
            agent_card, raw_agent_card=raw_agent_card, interval=interval
        )

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
                        "Failed to register with LiteLLM at %s after %d attempt(s): %s",
                        self.safe_registry_url,
                        resolved_max_retries + 1,
                        _describe_error(e),
                    )
                    logger.warning("Continuing without registration")
                    return
                logger.warning(
                    "Registry registration attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    resolved_max_retries + 1,
                    _describe_error(e),
                    delay,
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
                        "Failed to register with LiteLLM at %s after %d attempt(s): %s",
                        self.safe_registry_url,
                        resolved_max_retries + 1,
                        _describe_error(e),
                    )
                    logger.warning("Continuing without registration")
                    return
                logger.warning(
                    "Registry registration attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    resolved_max_retries + 1,
                    _describe_error(e),
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
