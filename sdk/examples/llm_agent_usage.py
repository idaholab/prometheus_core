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

"""PrometheusAgent example using the shared async LLM client.

This agent reads LLM configuration, including credentials, from environment
variables and uses self.llm_client(context).

Run locally with the same LLM setup as examples/llm_client_usage.py:

    REGISTRY_URL=http://localhost:4000 uv run python examples/llm_agent_usage.py
"""

from __future__ import annotations

from typing import Any, Dict

from prometheus_api.agent import EventQueue, MissingInput, PrometheusAgent, RequestContext


class LLMAnalysisAgent(PrometheusAgent):
    """Small A2A agent that delegates analysis text generation to LLMClient."""

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        query = str(params.get("query") or params.get("message") or "").strip()
        if not query:
            await self.send_input_required(
                context=context,
                event_queue=event_queue,
                missing_inputs=[
                    MissingInput(
                        name="query",
                        description="Engineering question or result text to analyze.",
                        user_prompt="What should I analyze?",
                        type="string",
                    )
                ],
                hint="This agent needs an analysis query before it can call the LLM.",
            )
            return {}

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Calling the configured LLM alias.",
        )

        async with self.llm_client(context) as llm:
            response = await llm.medium(
                [
                    {
                        "role": "system",
                        "content": "You are a concise engineering analysis assistant.",
                    },
                    {"role": "user", "content": query},
                ],
            )

        return {
            "conversation_id": context.context_id,
            "status": "completed",
            "answer": response.text,
            "model_alias": response.model_alias,
            "provider_model": response.provider_model,
            "usage": response.usage,
        }


if __name__ == "__main__":
    agent = LLMAnalysisAgent(agent_name="LLM Analysis Agent")
    agent.run()
