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
"""Approval plugin: a card skill with ``requires_approval`` becomes an ADK confirmation.

The plugin covers PPLT-114 gates 1 and 2 (REQ-016-05). A tool needs approval when the agent
card skill whose ``id`` equals the tool name has ``requires_approval: true``, or when the tool
object carries ``approval_required = True``. The first call of such a tool asks for a
confirmation with ``tool_context.request_confirmation`` and answers with
``PENDING_APPROVAL_RESULT``, so the tool does not run; ADK then emits its
``adk_request_confirmation`` call, which the bridge plugin maps to ``input-required``. When
the user answers, ADK calls the tool again with ``tool_context.tool_confirmation`` set: a
confirmed call runs, and a rejected call answers ``REJECTED_RESULT`` without running.

Each answer is appended to the invocation state key ``APPROVALS_STATE_KEY``
(``temp:approvals``) as ``{"tool", "function_call_id", "confirmed", "approver"}``, so the
provenance plugin can write it into ``tool_calls`` on the execution record.
"""

from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from ...agent.base import PrometheusAgent

APPROVALS_STATE_KEY = "temp:approvals"
PENDING_APPROVAL_RESULT: dict[str, Any] = {"status": "pending_approval"}
REJECTED_RESULT: dict[str, Any] = {"status": "rejected"}


class ApprovalPlugin(BasePlugin):
    """Pause a tool that needs approval until the user confirms or rejects the call."""

    def __init__(self, agent: PrometheusAgent) -> None:
        super().__init__(name="prometheus_approval")
        self.agent = agent

    def requires_approval(self, tool: BaseTool) -> bool:
        """Return whether the tool or its card skill asks for approval before it runs."""
        if getattr(tool, "approval_required", False) is True:
            return True
        skills = self.agent.get_raw_agent_card().get("skills") or []
        return any(
            isinstance(skill, dict)
            and skill.get("id") == tool.name
            and skill.get("requires_approval") is True
            for skill in skills
        )

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        if not self.requires_approval(tool):
            return None

        confirmation = tool_context.tool_confirmation
        if confirmation is None:
            tool_context.request_confirmation(
                hint=f"Approve or reject the call to {tool.name}.",
                payload={"tool": tool.name, "arguments": tool_args},
            )
            # The pause is not a result for the model to summarize; without this the
            # flow calls the model again, which calls the tool again.
            tool_context.actions.skip_summarization = True
            return dict(PENDING_APPROVAL_RESULT)

        approvals = list(tool_context.state.get(APPROVALS_STATE_KEY) or [])
        approvals.append(
            {
                "tool": tool.name,
                "function_call_id": tool_context.function_call_id,
                "confirmed": confirmation.confirmed,
                "approver": tool_context.user_id,
            }
        )
        tool_context.state[APPROVALS_STATE_KEY] = approvals
        if not confirmation.confirmed:
            return dict(REJECTED_RESULT)
        return None
