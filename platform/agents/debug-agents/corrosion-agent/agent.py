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
Corrosion Analysis Agent - Dummy specialist agent for corrosion analysis based
on LLM queries. Does not perform actual modeling and simulation work. Use this
only for orchestration debugging!
Implements A2A protocol using prometheus_api with Bearer token authentication
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from prometheus_api.agent import MissingInput, PrometheusAgent
from prometheus_api.llm_client import LLMConfig
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

CORROSION_ANALYSIS_JSON_TYPE = "prometheus.corrosion_analysis.result.v1"

# Skill routing: the invoked skill (params["skill_id"]) selects a focus the
# model emphasizes on top of the shared structured analysis.
DEFAULT_SKILL = "analyze_corrosion"
SKILL_FOCUS = {
    "analyze_corrosion": "Provide the full corrosion analysis across every field.",
    "predict_corrosion_rate": (
        "Prioritize predicted corrosion/oxidation rates and degradation timelines: "
        "oxidation_rate_mm_per_year, affected_area_percent, and confidence are the key outputs."
    ),
    "assess_coating_integrity": (
        "Prioritize protective coating condition and remaining service life: "
        "coating_status, affected_area_percent, and recommendations are the key outputs."
    ),
}

ANALYSIS_PROMPT_TEMPLATE = """\
You are a corrosion specialist. Analyze the corrosion state of material: {material_id}
{context_str}
Provide a comprehensive corrosion analysis as a JSON object with the following structure:
{{
    "oxidation_rate_mm_per_year": <float>,
    "pitting_index": <float 0-1>,
    "scc_susceptibility": "<low/medium/high>",
    "coating_status": "<intact/degraded/failed>",
    "environmental_factors": {{
        "ph_level": <float>,
        "dissolved_oxygen_ppb": <float>,
        "chloride_concentration_ppm": <float>
    }},
    "corrosion_mechanisms": [<list of active mechanisms>],
    "affected_area_percent": <float>,
    "recommendations": [<list of actionable recommendations>],
    "risk_level": "<low/medium/high/critical>",
    "confidence": <float 0-1>
}}

Focus on realistic materials corrosion scenarios. Consider general corrosion, pitting, stress corrosion cracking (SCC), flow-accelerated corrosion, and intergranular attack."""


def _build_corrosion_summary(material_id: str, analysis: Dict[str, Any]) -> str:
    risk_level = str(analysis.get("risk_level") or "unknown")
    oxidation_rate = analysis.get("oxidation_rate_mm_per_year")
    pitting_index = analysis.get("pitting_index")

    parts: List[str] = [f"Corrosion analysis for {material_id} completed."]
    if oxidation_rate is not None:
        parts.append(f"Oxidation rate: {oxidation_rate:.4f} mm/year.")
    if pitting_index is not None:
        parts.append(f"Pitting index: {pitting_index:.2f}.")
    parts.append(f"Risk level: {risk_level}.")
    return " ".join(parts)


def _build_corrosion_report(material_id: str, analysis: Dict[str, Any]) -> str:
    risk_level = str(analysis.get("risk_level") or "unknown")
    confidence = analysis.get("confidence")
    scc = analysis.get("scc_susceptibility") or "not provided"
    coating = analysis.get("coating_status") or "not provided"
    recommendations = analysis.get("recommendations") or []
    mechanisms = analysis.get("corrosion_mechanisms") or []
    env = analysis.get("environmental_factors") or {}

    lines = [
        f"Corrosion Analysis for {material_id}",
        "",
        f"- Risk level: {risk_level}",
        f"- Confidence: {confidence}",
        f"- Oxidation rate: {analysis.get('oxidation_rate_mm_per_year')} mm/year",
        f"- Pitting index: {analysis.get('pitting_index')}",
        f"- SCC susceptibility: {scc}",
        f"- Coating status: {coating}",
        f"- Affected area: {analysis.get('affected_area_percent')} %",
        "",
        "Environmental factors:",
        f"- pH level: {env.get('ph_level')}",
        f"- Dissolved oxygen: {env.get('dissolved_oxygen_ppb')} ppb",
        f"- Chloride concentration: {env.get('chloride_concentration_ppm')} ppm",
    ]

    if mechanisms:
        lines.extend(["", "Active corrosion mechanisms:"])
        for m in mechanisms:
            lines.append(f"- {m}")

    if recommendations:
        lines.extend(["", "Recommendations:"])
        for item in recommendations:
            lines.append(f"- {item}")

    return "\n".join(lines)


class CorrosionAnalysisAgent(PrometheusAgent):
    """Agent for corrosion analysis."""

    def _merge_resolved_inputs(self, resolved: Dict[str, Any], params: Dict[str, Any], context: RequestContext) -> Dict[str, Any]:
        merged = dict(resolved or {})
        if params.get("material_id"):
            merged["material_id"] = params["material_id"]

        operating_context = params.get("context", {})
        if isinstance(operating_context, dict):
            for key in ("temperature_c", "pressure_mpa", "operating_hours", "coolant_chemistry"):
                if operating_context.get(key) is not None:
                    merged[key] = operating_context[key]

        for key, value in self.get_provided_inputs(context).items():
            if value is not None:
                merged[key] = value

        return merged

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """
        Perform corrosion analysis on the specified material using the configured LLM.

        Generates expert-level corrosion analysis from material properties and
        operating conditions.
        """
        state = self.load_context_state(str(context.context_id or ""))
        resolved = self._merge_resolved_inputs(state.get("resolved", {}), params, context)

        material_id = resolved.get("material_id")
        if not material_id:
            await self.send_input_required(
                context=context,
                event_queue=event_queue,
                missing_inputs=[
                    MissingInput(
                        name="material_id",
                        description="Canonical material identifier for the corrosion analysis.",
                        user_prompt="Which material should I analyze for corrosion?",
                        type="string",
                        resolvable_from_context=True,
                    )
                ],
                hint="I need the target material before I can run the corrosion analysis.",
            )
            self.save_context_state(
                str(context.context_id or ""),
                {
                    "resolved": resolved,
                    "pending": ["material_id"],
                    "task_id": context.task_id,
                },
            )
            return {"status": "input_required"}

        # Send status update
        await self.send_status_update(context=context, event_queue=event_queue)

        operating_context = {
            "temperature_c": resolved.get("temperature_c"),
            "pressure_mpa": resolved.get("pressure_mpa"),
            "operating_hours": resolved.get("operating_hours"),
            "coolant_chemistry": resolved.get("coolant_chemistry"),
        }

        # Build model context
        context_str = ""
        non_null = {k: v for k, v in operating_context.items() if v is not None}
        if non_null:
            context_str = "\nOperating Conditions:\n"
            if non_null.get("temperature_c"):
                context_str += f"- Temperature: {non_null['temperature_c']}C\n"
            if non_null.get("pressure_mpa"):
                context_str += f"- Pressure: {non_null['pressure_mpa']} MPa\n"
            if non_null.get("coolant_chemistry"):
                context_str += f"- Coolant Chemistry: {json.dumps(non_null['coolant_chemistry'])}\n"
            if non_null.get("operating_hours"):
                context_str += f"- Operating Hours: {non_null['operating_hours']}\n"

        # Route on the invoked skill (injected by the base executor as
        # params["skill_id"]); fall back to the primary analysis skill.
        skill_id = str(params.get("skill_id") or "").strip()
        if skill_id not in SKILL_FOCUS:
            skill_id = DEFAULT_SKILL
        prompt = (
            ANALYSIS_PROMPT_TEMPLATE.format(material_id=material_id, context_str=context_str)
            + f"\n\nSkill focus ({skill_id}): {SKILL_FOCUS[skill_id]}"
        )

        try:
            llm_config = LLMConfig.from_env()
            async with self.llm_client(context, config=llm_config) as llm:
                response = await llm.medium(
                    prompt,
                    max_tokens=2048,
                )

            # Extract JSON from response
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            analysis = json.loads(response_text)

            # Add metadata
            analysis["material_id"] = material_id
            analysis["timestamp"] = datetime.now(timezone.utc).isoformat()
            analysis["analysis_type"] = "corrosion"
            analysis["skill_id"] = skill_id
            analysis["model_used"] = response.provider_model or response.model_alias

            message = _build_corrosion_summary(material_id, analysis)
            report = _build_corrosion_report(material_id, analysis)

            await self.send_json_artifact(
                context=context,
                event_queue=event_queue,
                payload=analysis,
                name=f"{material_id.lower()}_{skill_id}",
                description=f"Corrosion analysis result for {material_id}.",
                json_type=CORROSION_ANALYSIS_JSON_TYPE,
                catalog_artifact=True,
            )

            self.save_context_state(
                str(context.context_id or ""),
                {
                    "resolved": resolved,
                    "pending": [],
                    "task_id": context.task_id,
                    "last_result_timestamp": analysis["timestamp"],
                },
            )

            return {
                **analysis,
                "message": message,
                "report": report,
            }

        except Exception as e:
            return {
                "material_id": material_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "analysis_type": "corrosion",
                "error": f"Analysis failed: {str(e)}",
            }


if __name__ == "__main__":
    agent = CorrosionAnalysisAgent(agent_name="Corrosion Analysis Agent")
    agent.run()
