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
Synthesis Agent - Specialist for multi-result material analysis synthesis.

Consumes outputs from data/radiation/corrosion/thermal specialists and produces
a consolidated engineering summary for workflow final output.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from prometheus_api.agent import PrometheusAgent
from prometheus_api.llm_client import LLMConfig

PROMPTS_DIR = Path(__file__).with_name("prompts")


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


ANALYSIS_PROMPT_TEMPLATE = _load_prompt("analysis.txt")


class SynthesisAgent(PrometheusAgent):
    """Agent that synthesizes specialist outputs into a single report object."""

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        material_id = params.get("material_id")
        tool_results = params.get("tool_results")
        user_query = params.get("query")
        operating_context = params.get("context", {})

        if not material_id:
            return {"error": "material_id is required"}
        if not isinstance(tool_results, dict) or not tool_results:
            return {"error": "tool_results is required and must be a non-empty object"}

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Synthesizing specialist analyses for {material_id}.",
        )

        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            material_id=material_id,
            user_query=user_query or "(not provided)",
            operating_context_json=json.dumps(operating_context, indent=2, default=str),
            tool_results_json=json.dumps(tool_results, indent=2, default=str),
        )

        try:
            llm_config = LLMConfig.from_env()
            async with self.llm_client(context, config=llm_config) as llm:
                response = await llm.medium(
                    prompt,
                    max_tokens=1800,
                )
            text = response.text
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0].strip()

            synthesized = json.loads(text)
            if not isinstance(synthesized, dict):
                synthesized = {"executive_summary": str(text).strip()}

            synthesized["material_id"] = material_id
            synthesized["analysis_type"] = "synthesis"
            synthesized["timestamp"] = datetime.now(timezone.utc).isoformat()
            synthesized["model_used"] = response.provider_model or response.model_alias
            return synthesized
        except Exception as exc:
            return {
                "material_id": material_id,
                "analysis_type": "synthesis",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": f"Synthesis failed: {exc}",
                "tool_results": tool_results,
            }


if __name__ == "__main__":
    agent = SynthesisAgent(agent_name="Synthesis Agent")
    agent.run()
