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

"""Reference PrometheusAgent example showing common agent actions.

This example demonstrates:
- transient status updates
- durable conversation messages
- per-context state persistence
- INPUT_REQUIRED follow-ups
- fetching upstream data through a reusable client
- URI-backed and inline JSON artifacts
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from prometheus_api.agent import EventQueue, MissingInput, PrometheusAgent, RequestContext


@dataclass
class ExampleCatalogRecord:
    material_id: str
    display_name: str
    max_temperature_c: float


class ExampleCatalogClient:
    """Tiny in-memory stand-in for an upstream system."""

    def __init__(self) -> None:
        self._records = {
            "SS316": ExampleCatalogRecord(
                material_id="SS316",
                display_name="Stainless Steel 316",
                max_temperature_c=650.0,
            ),
            "IN718": ExampleCatalogRecord(
                material_id="IN718",
                display_name="Inconel 718",
                max_temperature_c=700.0,
            ),
        }

    def get_material(self, material_id: str) -> ExampleCatalogRecord:
        key = str(material_id or "").strip().upper()
        if key not in self._records:
            raise KeyError(f"Unknown material_id: {material_id}")
        return self._records[key]


class ExampleAnalysisAgent(PrometheusAgent):
    """Reference agent using the current PrometheusAgent contract."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.catalog = ExampleCatalogClient()

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        # On resume, params holds every original argument plus the user's answers.
        if params.get("temperature_c") is None:
            await self.send_input_required(
                context=context,
                event_queue=event_queue,
                missing_inputs=[
                    MissingInput(
                        name="temperature_c",
                        description="Operating temperature in degrees Celsius for this analysis case.",
                        user_prompt="What operating temperature should I use?",
                        type="number",
                    )
                ],
                hint="This analysis cannot proceed without an operating temperature.",
            )
            return {}

        material = self.catalog.get_material(str(params.get("material_id") or "").strip().upper())
        temperature_c = float(params["temperature_c"])

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Loaded {material.display_name}.",
        )
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Computing thermal margins.",
        )

        margin_c = material.max_temperature_c - temperature_c
        result_payload = {
            "material_id": material.material_id,
            "material_name": material.display_name,
            "temperature_c": temperature_c,
            "max_temperature_c": material.max_temperature_c,
            "margin_c": margin_c,
            "status": "acceptable" if margin_c >= 0 else "exceeded",
        }

        await self.send_conversation_message(
            context=context,
            event_queue=event_queue,
            message=f"Analysis started for {material.display_name}.",
        )

        await self.send_json_artifact(
            context=context,
            event_queue=event_queue,
            name="analysis_result",
            description="Structured example analysis result",
            payload=result_payload,
            json_type="prometheus.example.analysis_result.v1",
            catalog_artifact=True,
        )

        report_path = Path("/tmp/example-analysis.txt")
        report_path.write_text(
            "\n".join(
                [
                    f"Material: {material.display_name}",
                    f"Requested temperature: {temperature_c} C",
                    f"Allowable maximum: {material.max_temperature_c} C",
                    f"Margin: {margin_c} C",
                ]
            ),
            encoding="utf-8",
        )
        artifact = await self.send_artifact_reference(
            context=context,
            event_queue=event_queue,
            name=report_path.name,
            description="Human-readable analysis report",
            uri=f"file://{report_path}",
            mime_type="text/plain",
        )

        return {
            "conversation_id": context.context_id,
            "status": "completed",
            "message": (
                f"{material.display_name} analyzed at {temperature_c} C. "
                f"Remaining margin: {margin_c} C."
            ),
            "result": result_payload,
            "new_artifacts": [artifact.to_dict()],
        }


if __name__ == "__main__":
    agent = ExampleAnalysisAgent(agent_name="Example Analysis Agent")
    agent.run()
