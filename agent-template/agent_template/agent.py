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

"""
TEMPLATE_NAME Agent.

TEMPLATE_DESCRIPTION

This is a Prometheus specialist agent.  Subclass PrometheusAgent and implement
`_execute` — the base class handles the HTTP server, authentication, agent-card
serving, and registry registration for you.
"""

import asyncio  # noqa: F401 - used by parallel design patterns
import logging
from typing import Any

from prometheus_api import load_prompt  # noqa: F401 - used by the LLM pattern below
from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext

# >>> design pattern constants (setup_agent.py replaces this block)
# <<< design pattern constants

# Read secrets and configuration from environment variables.
# Never hard-code API keys or URLs here.
# Example (add `import os` to the imports above):
#   MY_API_KEY = os.getenv("MY_API_KEY")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TEMPLATE_CLASSAgent(PrometheusAgent):
    """TEMPLATE_NAME Agent."""

    # Optional: register agent-owned HTTP endpoints in __init__.
    #
    # def __init__(self, *args: Any, **kwargs: Any) -> None:
    #     super().__init__(*args, **kwargs)
    #     self.add_http_endpoint(
    #         "/api/preview/{artifact_id}",
    #         self.preview_artifact,
    #         methods=["GET"],
    #         endpoint_id="artifact_preview",
    #         purpose="artifact",
    #         description="Return preview metadata for one artifact.",
    #         content_types=["application/json"],
    #     )
    #     self.add_static_endpoint(
    #         "/viewer",
    #         "viewer-assets",
    #         endpoint_id="viewer_assets",
    #         purpose="viewer_plugin",
    #         description="Serve viewer plugin JavaScript and CSS.",
    #         content_types=["text/javascript", "text/css"],
    #     )
    #
    # async def preview_artifact(self, request):
    #     from starlette.responses import JSONResponse
    #
    #     return JSONResponse({"artifact_id": request.path_params["artifact_id"]})

    async def _execute(
        self,
        params: dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> dict[str, Any]:
        """Process one request.

        Args:
            params: Parameters from the caller's JSON payload, plus ``skill_id``
                from the message metadata (the skill the orchestrator selected).
            context: The A2A request context.  Use ``context.context_id`` as a
                stable key for per-conversation state.
            event_queue: Pass to the ``send_*`` helpers to emit progress updates
                and artifacts.

        Returns:
            A plain ``dict``.  The base class wraps it as the final ``completed``
            task status automatically — do not enqueue that event yourself.
        """
        # ------------------------------------------------------------------
        # 1. Read inputs from params.  These keys must match the properties
        #    declared in agent_card.json's inputSchema.
        # ------------------------------------------------------------------
        input_data = params.get("input_data")
        if not input_data:
            return {"status": "error", "error": "input_data is required"}

        # ------------------------------------------------------------------
        # 2. Send optional progress updates so the UI stays responsive.
        #    The base class sends the initial "working" update automatically;
        #    call this only when you want intermediate messages.
        # ------------------------------------------------------------------
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Processing your request…",
        )

        # ------------------------------------------------------------------
        # 3. Do your actual work here.  `_run_pattern` (below) walks the
        #    steps of the agent's design pattern; fill in each `_step_*`.
        # ------------------------------------------------------------------
        state = await self._run_pattern(input_data, context, event_queue)
        result = {
            "status": "success",
            "input_received": input_data,
            "steps": {name: value for name, value in state.items() if name != "input_data"},
            "message": "Replace this with your agent's processing logic.",
        }

        # ------------------------------------------------------------------
        # 4. Return a plain dict.  Keep keys consistent with the
        #    "output_format" you described in agent_card.json.
        # ------------------------------------------------------------------
        return result

    # >>> design pattern (setup_agent.py replaces this block)
    # ------------------------------------------------------------------
    # Design pattern: Tool Use (Tools & Actions family, linear topology).
    # Steps: decide_tool -> call_tool -> respond. See README.md.
    # ------------------------------------------------------------------

    async def _run_pattern(
        self, input_data: Any, context: RequestContext, event_queue: EventQueue
    ) -> dict[str, Any]:
        """Run the Tool Use steps on one request and return the state they built."""
        state: dict[str, Any] = {"input_data": input_data}
        state["decide_tool"] = await self._step_decide_tool(state, context, event_queue)
        state["call_tool"] = await self._step_call_tool(state, context, event_queue)
        state["respond"] = await self._step_respond(state, context, event_queue)
        return state

    async def _step_decide_tool(
        self, state: dict[str, Any], context: RequestContext, event_queue: EventQueue
    ) -> Any:
        """Tool Use step `decide_tool`: Decide which tool to call and with what arguments."""
        # TODO(author): implement `decide_tool`.
        return None

    async def _step_call_tool(
        self, state: dict[str, Any], context: RequestContext, event_queue: EventQueue
    ) -> Any:
        """Tool Use step `call_tool`: Call the tool."""
        # TODO(author): implement `call_tool`.
        return None

    async def _step_respond(
        self, state: dict[str, Any], context: RequestContext, event_queue: EventQueue
    ) -> Any:
        """Tool Use step `respond`: Incorporate the tool result into the answer."""
        # TODO(author): implement `respond`.
        return None

    # <<< design pattern

    # ----------------------------------------------------------------------
    # PATTERNS — uncomment and adapt as needed.
    # ----------------------------------------------------------------------
    #
    # Calling an LLM (provider and models come from LLM_CONFIG_PROFILE):
    #
    #     system_prompt = load_prompt("system_prompt.txt").format(input_data=input_data)
    #     async with self.llm_client(context) as llm:
    #         response = await llm.medium(system_prompt)
    #     return {"status": "success", "summary": response.text}
    #
    # Dispatching when agent_card.json declares more than one skill:
    #
    #     handler = {
    #         "skill_a": self._handle_a,
    #         "skill_b": self._handle_b,
    #     }.get(params.get("skill_id"))
    #     if handler is None:
    #         return {"status": "error", "error": f"Unknown skill: {params.get('skill_id')}"}
    #     return await handler(params, context, event_queue)
    #
    # Persisting per-conversation state across turns (Redis-backed, with an
    # in-memory fallback for local development):
    #
    #     state = self.load_context_state(str(context.context_id))
    #     state["count"] = state.get("count", 0) + 1
    #     self.save_context_state(str(context.context_id), state)
    #
    # See TUTORIAL.md ("Advanced topics") for emitting artifacts, asking the
    # user for missing inputs (INPUT_REQUIRED), and DeepLynx file storage.


if __name__ == "__main__":
    agent = TEMPLATE_CLASSAgent(agent_name="TEMPLATE_NAME Agent")
    agent.run()
