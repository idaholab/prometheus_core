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
"""Just-in-time credentials for ADK tools, from the agent's credential broker.

A tool asks for a credential with a ``credential_resource`` attribute (and an optional
``credential_scope`` dict). The plugin fetches the credential before that one call and
puts it under a ``temp:`` state key named after the call's ``function_call_id``. ADK's
session services strip ``temp:`` keys from an event before they store it, and the plugin
overwrites the key with ``None`` when the call ends, so the value never reaches the
session store, an event, a log or DeepLynx.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.sessions.state import State
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from ...agent.identity import get_current_identity
from ...credentials import Credential
from ...storage_client.connection import ConnectionConfig

if TYPE_CHECKING:
    from ...agent.base import PrometheusAgent

logger = logging.getLogger(__name__)

_CREDENTIAL_KEY_PREFIX = f"{State.TEMP_PREFIX}prometheus_credential:"


def _credential_key(tool_context: ToolContext) -> str:
    return f"{_CREDENTIAL_KEY_PREFIX}{tool_context.function_call_id}"


def tool_credential(tool_context: ToolContext) -> Optional[Credential]:
    """Return the credential the plugin fetched for the current tool call, if any."""
    value = tool_context.state.get(_credential_key(tool_context))
    return value if isinstance(value, Credential) else None


async def deeplynx_config(agent: "PrometheusAgent", user_id: str) -> ConnectionConfig:
    """Build the DeepLynx ``ConnectionConfig`` for *user_id*.

    Inside an identity scope, the config carries the broker's per-user ``jwt_token``.
    Outside one (development mode), it falls back to the ``DEEPLYNX_*`` service-account
    configuration of ``ConnectionConfig.from_env()``.

    Raises:
        ValueError: When *user_id* is not the user of the current identity scope.
    """
    identity = get_current_identity()
    if identity is None:
        return ConnectionConfig.from_env()
    if identity.user_id != user_id:
        raise ValueError(
            f"DeepLynx config requested for user {user_id!r} "
            f"inside the identity scope of {identity.user_id!r}"
        )
    credential = await agent.get_credential("deeplynx")
    return ConnectionConfig.from_credential(credential)


class CredentialPlugin(BasePlugin):
    """Give each tool that declares ``credential_resource`` a credential for that call only."""

    def __init__(self, agent: "PrometheusAgent") -> None:
        super().__init__(name="prometheus_credentials")
        self._agent = agent

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict[str, Any]]:
        resource = getattr(tool, "credential_resource", None)
        if not resource:
            return None
        scope = getattr(tool, "credential_scope", None)
        credential = await self._agent.get_credential(resource, scope)
        tool_context.state[_credential_key(tool_context)] = credential
        logger.debug("Credential for %s issued to tool %s", resource, tool.name)
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        self._clear(tool, tool_context)
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict[str, Any]]:
        self._clear(tool, tool_context)
        return None

    @staticmethod
    def _clear(tool: BaseTool, tool_context: ToolContext) -> None:
        # ADK's State has no delete; overwriting the key replaces the value in the
        # call's state delta, so the response event never carries the credential.
        if getattr(tool, "credential_resource", None):
            tool_context.state[_credential_key(tool_context)] = None
