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

This is a Prometheus specialist agent on the Google ADK runtime.  Each skill in
agent_card.json maps to one ADK agent in ``adk_agents``; the base class runs it
through ``build_runner`` and handles the HTTP server, authentication, agent-card
serving, registry registration, sessions, artifacts, and status events for you.
"""

import asyncio
import logging
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.plugins import BasePlugin
from google.adk.runners import Runner
from google.adk.tools import FunctionTool, ToolContext
from google.adk.workflow import BaseNode
from google.genai import types
from prometheus_api import load_prompt  # noqa: F401 - used by the prompt-file pattern below
from prometheus_api.adk import AdkPrometheusAgent, prometheus_model
from prometheus_api.agent import EventQueue, RequestContext
from prometheus_api.llm_client import AsyncLLMClient

# Read secrets and configuration from environment variables.
# Never hard-code API keys or URLs here.
# Example (add `import os` to the imports above):
#   MY_API_KEY = os.getenv("MY_API_KEY")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def save_report(title: str, body: str, tool_context: ToolContext) -> dict[str, Any]:
    """Save a Markdown report as an artifact of this conversation.

    Args:
        title: A short title for the report.
        body: The report text, in Markdown.
    """
    # save_artifact stores one immutable DeepLynx item per call and links it to
    # this run; the platform shows it to the user as an artifact.
    report = f"# {title}\n\n{body}\n"
    version = await tool_context.save_artifact(
        "report.md",
        types.Part.from_bytes(data=report.encode(), mime_type="text/markdown"),
    )
    return {"status": "success", "filename": "report.md", "version": version}


# The ADK agent of the TEMPLATE_SKILL_ID skill.  It has no model here: the model
# client is request-scoped, so create_runner adds it for each request.  The
# first user message is the request params as JSON (the keys of the skill's
# inputSchema in agent_card.json).
TEMPLATE_SKILL_ID_agent = LlmAgent(
    name="TEMPLATE_SKILL_ID",
    instruction=(
        "You are TEMPLATE_NAME Agent, a Prometheus specialist agent. "
        "The user message is a JSON object with the task input in input_data. "
        "Process the input, then call save_report once with your findings. "
        "Reply with one JSON object with the keys status, input_received and message."
    ),
    tools=[FunctionTool(save_report)],
)


class _CloseLlmClient(BasePlugin):
    """Close the request's LLM client when the runner closes."""

    def __init__(self, client: AsyncLLMClient) -> None:
        super().__init__(name="close_llm_client")
        self._client = client

    async def close(self) -> None:
        await self._client.aclose()


class TEMPLATE_CLASSAgent(AdkPrometheusAgent):
    """TEMPLATE_NAME Agent."""

    # Card skill ID -> ADK agent or Workflow.  Every skill in agent_card.json
    # needs an entry, and every entry needs a card skill: startup raises
    # ValueError otherwise.
    adk_agents = {"TEMPLATE_SKILL_ID": TEMPLATE_SKILL_ID_agent}

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

    def create_runner(
        self,
        context: RequestContext,
        root: BaseNode,
        *,
        event_queue: EventQueue,
        abort_signal: asyncio.Event,
    ) -> Runner:
        """Give a model-less ADK agent this request's model, then build its runner.

        ``prometheus_model`` sends every completion through one AsyncLLMClient
        with a semantic flavor; the LLM config maps the flavor to a model.  The
        base class closes the runner when the run ends, and the runner then
        closes the client.  An agent that already has a model (a test stub)
        keeps it.
        """
        if not isinstance(root, LlmAgent) or root.model:
            return super().create_runner(
                context, root, event_queue=event_queue, abort_signal=abort_signal
            )
        client = self.llm_client(context)
        root = root.clone(update={"model": prometheus_model("default", client)})
        runner = super().create_runner(
            context, root, event_queue=event_queue, abort_signal=abort_signal
        )
        runner.plugin_manager.register_plugin(_CloseLlmClient(client))
        return runner

    # ----------------------------------------------------------------------
    # PATTERNS — uncomment and adapt as needed.
    # ----------------------------------------------------------------------
    #
    # A second skill: add it to agent_card.json and to adk_agents, with its own
    # ADK agent (or a Workflow of FunctionNodes when the skill needs no model).
    #
    #     adk_agents = {"TEMPLATE_SKILL_ID": TEMPLATE_SKILL_ID_agent, "skill_b": skill_b_agent}
    #
    # Loading a long instruction from prompts/ (ADK fills each {name}
    # placeholder from session state, so do not put literal braces in it):
    #
    #     instruction=load_prompt("instructions.txt"),
    #
    # Reading an input artifact in a tool:
    #
    #     async def summarize(filename: str, tool_context: ToolContext) -> dict[str, Any]:
    #         part = await tool_context.load_artifact(filename)
    #         ...
    #
    # Announcing a slow skill (the platform then shows it as background work):
    #
    #     long_running = {"TEMPLATE_SKILL_ID": 300}  # estimated seconds
    #
    # See TUTORIAL.md ("Advanced topics") for asking the user for missing
    # inputs (INPUT_REQUIRED) and DeepLynx file storage.


if __name__ == "__main__":
    agent = TEMPLATE_CLASSAgent(agent_name="TEMPLATE_NAME Agent")
    agent.run()
