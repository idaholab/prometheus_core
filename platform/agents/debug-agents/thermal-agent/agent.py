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
Thermal Analysis Agent - Dummy specialist agent for thermal analysis.
Does not perform actual modeling and simulation work. Use this only for
orchestration debugging!
Implements A2A protocol using prometheus_api with Bearer token authentication
"""
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from prometheus_api.agent import MissingInput, PrometheusAgent
from prometheus_api.llm_client import LLMConfig
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

THERMAL_ANALYSIS_JSON_TYPE = "prometheus.thermal_analysis.result.v1"

# Skill routing: the invoked skill (params["skill_id"]) selects a focus the
# model emphasizes on top of the shared structured analysis.
DEFAULT_SKILL = "analyze_thermal"
SKILL_FOCUS = {
    "analyze_thermal": "Provide the full thermal analysis across every field.",
    "calculate_thermal_fatigue": (
        "Prioritize thermal-fatigue assessment: thermal_fatigue_usage_factor, "
        "fatigue_analysis, and thermal_stress_mpa are the key outputs."
    ),
    "assess_creep": (
        "Prioritize creep damage: creep_strain_percent and creep_analysis "
        "(creep_rate, Larson-Miller, rupture_life_fraction_used) are the key outputs."
    ),
}

ANALYSIS_PROMPT_TEMPLATE = """\
You are a thermal analysis specialist. Analyze thermal effects on material: {material_id}
{context_str}
Provide a comprehensive thermal analysis as a JSON object with this structure:
{{
    "operating_temperature_c": <float>,
    "max_temperature_c": <float>,
    "min_temperature_c": <float>,
    "temperature_gradient_c_per_cm": <float>,
    "thermal_cycles_accumulated": <int>,
    "thermal_fatigue_usage_factor": <float 0-1>,
    "creep_strain_percent": <float>,
    "thermal_conductivity_degradation_percent": <float>,
    "thermal_stress_mpa": <float>,
    "cycle_categories": {{
        "startup_shutdown": <int>,
        "load_following": <int>,
        "thermal_transients": <int>
    }},
    "fatigue_analysis": {{
        "design_cycles": <int>,
        "accumulated_cycles": <int>,
        "remaining_cycles": <int>,
        "fatigue_curve": "<ASME reference>"
    }},
    "creep_analysis": {{
        "creep_rate_percent_per_hour": <scientific notation>,
        "larson_miller_parameter": <float>,
        "rupture_life_fraction_used": <float 0-1>,
        "tertiary_creep_onset": "<detected/not_detected>"
    }},
    "status": "<acceptable/degraded/critical>",
    "recommendations": [<list of recommendations>],
    "confidence": <float 0-1>
}}

Consider thermal fatigue, creep damage, thermal aging, and thermal stress per ASME Section III."""


def _format_number(value: Any, suffix: str = "") -> str:
    if isinstance(value, bool) or value is None:
        return "not provided"
    if isinstance(value, int):
        return f"{value}{suffix}"
    if isinstance(value, float):
        if value != 0 and abs(value) < 0.001:
            return f"{value:.2e}{suffix}"
        if value.is_integer():
            return f"{int(value)}{suffix}"
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}" if suffix else str(value)


def _build_thermal_summary(material_id: str, analysis: Dict[str, Any]) -> str:
    status = str(analysis.get("status") or "completed").replace("_", " ")
    operating_temperature_c = analysis.get("operating_temperature_c")
    thermal_stress_mpa = analysis.get("thermal_stress_mpa")
    fatigue_usage = analysis.get("thermal_fatigue_usage_factor")

    parts: List[str] = [f"Thermal analysis for {material_id} completed."]
    if operating_temperature_c is not None:
        parts.append(f"Operating temperature: {_format_number(operating_temperature_c, ' C')}.")
    parts.append(f"Overall status: {status}.")
    if thermal_stress_mpa is not None:
        parts.append(f"Thermal stress: {_format_number(thermal_stress_mpa, ' MPa')}.")
    if fatigue_usage is not None:
        parts.append(f"Fatigue usage factor: {_format_number(fatigue_usage)}.")
    return " ".join(parts)


def _build_thermal_report(material_id: str, analysis: Dict[str, Any]) -> str:
    status = str(analysis.get("status") or "unknown").replace("_", " ")
    confidence = analysis.get("confidence")
    recommendations = analysis.get("recommendations") or []
    fatigue = analysis.get("fatigue_analysis") or {}
    creep = analysis.get("creep_analysis") or {}
    cycle_categories = analysis.get("cycle_categories") or {}

    lines = [
        f"Thermal Analysis for {material_id}",
        "",
        f"- Overall status: {status}",
        f"- Confidence: {_format_number(confidence)}",
        f"- Operating temperature: {_format_number(analysis.get('operating_temperature_c'), ' C')}",
        f"- Thermal stress: {_format_number(analysis.get('thermal_stress_mpa'), ' MPa')}",
        f"- Thermal fatigue usage factor: {_format_number(analysis.get('thermal_fatigue_usage_factor'))}",
        f"- Creep strain: {_format_number(analysis.get('creep_strain_percent'), ' %')}",
        f"- Thermal conductivity degradation: {_format_number(analysis.get('thermal_conductivity_degradation_percent'), ' %')}",
        "",
        "Cycle summary:",
        f"- Total thermal cycles: {_format_number(analysis.get('thermal_cycles_accumulated'))}",
        f"- Startup and shutdown cycles: {_format_number(cycle_categories.get('startup_shutdown'))}",
        f"- Load-following cycles: {_format_number(cycle_categories.get('load_following'))}",
        f"- Thermal transients: {_format_number(cycle_categories.get('thermal_transients'))}",
        "",
        "Fatigue analysis:",
        f"- Design cycles: {_format_number(fatigue.get('design_cycles'))}",
        f"- Accumulated cycles: {_format_number(fatigue.get('accumulated_cycles'))}",
        f"- Remaining cycles: {_format_number(fatigue.get('remaining_cycles'))}",
        f"- Fatigue curve: {fatigue.get('fatigue_curve') or 'not provided'}",
        "",
        "Creep analysis:",
        f"- Creep rate: {_format_number(creep.get('creep_rate_percent_per_hour'), ' %/hour')}",
        f"- Larson-Miller parameter: {_format_number(creep.get('larson_miller_parameter'))}",
        f"- Rupture life fraction used: {_format_number(creep.get('rupture_life_fraction_used'))}",
        f"- Tertiary creep onset: {creep.get('tertiary_creep_onset') or 'not provided'}",
    ]

    if recommendations:
        lines.extend(["", "Recommendations:"])
        for item in recommendations:
            lines.append(f"- {item}")

    return "\n".join(lines)


class ThermalAnalysisAgent(PrometheusAgent):
    """Agent for thermal analysis."""

    @staticmethod
    def _resolve_inputs(params: Dict[str, Any]) -> Dict[str, Any]:
        """Read every input from params.

        Operating conditions come nested under ``context`` from the model, or at the
        top level when the user answered an INPUT_REQUIRED form; the answer wins.
        """
        operating_context = params.get("context")
        if not isinstance(operating_context, dict):
            operating_context = {}
        resolved: Dict[str, Any] = {"material_id": params.get("material_id")}
        for key in ("temperature_c", "pressure_mpa", "operating_hours", "thermal_cycles"):
            resolved[key] = params[key] if params.get(key) is not None else operating_context.get(key)
        return resolved

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """
        Perform thermal analysis using the configured LLM.

        Generates expert-level thermal analysis from material properties and
        operating conditions.
        """
        resolved = self._resolve_inputs(params)

        material_id = resolved.get("material_id")
        if not material_id:
            await self.send_input_required(
                context=context,
                event_queue=event_queue,
                missing_inputs=[
                    MissingInput(
                        name="material_id",
                        description="Canonical material identifier for the thermal analysis.",
                        user_prompt="Which material should I analyze thermally?",
                        type="string",
                        resolvable_from_context=True,
                    )
                ],
                hint="I need the target material before I can run the thermal analysis.",
            )
            return {"status": "input_required"}

        operating_context = {
            "temperature_c": resolved.get("temperature_c"),
            "pressure_mpa": resolved.get("pressure_mpa"),
            "operating_hours": resolved.get("operating_hours"),
            "thermal_cycles": resolved.get("thermal_cycles"),
        }

        if operating_context.get("temperature_c") is None:
            await self.send_input_required(
                context=context,
                event_queue=event_queue,
                missing_inputs=[
                    MissingInput(
                        name="temperature_c",
                        description="Operating temperature in Celsius at which the material should be evaluated.",
                        user_prompt="What operating temperature should I use for the thermal analysis (in Celsius)?",
                        type="number",
                        resolvable_from_context=True,
                    )
                ],
                hint="Thermal analysis requires an operating temperature before it can proceed.",
            )
            return {"status": "input_required"}

        # Send status update
        await self.send_status_update(context=context, event_queue=event_queue)

        context_str = ""
        if operating_context:
            context_str = "\nOperating Conditions:\n"
            if operating_context.get("temperature_c"):
                context_str += f"- Temperature: {operating_context['temperature_c']}C\n"
            if operating_context.get("pressure_mpa"):
                context_str += f"- Pressure: {operating_context['pressure_mpa']} MPa\n"
            if operating_context.get("operating_hours"):
                context_str += f"- Operating Hours: {operating_context['operating_hours']}\n"

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
            if llm_config.proxy_url:
                llm_config = llm_config.with_api_key(os.getenv("LITELLM_MASTER_KEY"))
            async with self.llm_client(context, config=llm_config) as llm:
                response = await llm.medium(
                    prompt,
                    max_tokens=2048,
                )

            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            analysis = json.loads(response_text)
            analysis["material_id"] = material_id
            analysis["timestamp"] = datetime.now(timezone.utc).isoformat()
            analysis["analysis_type"] = "thermal"
            analysis["skill_id"] = skill_id
            analysis["model_used"] = response.provider_model or response.model_alias
            analysis["operating_temperature_c"] = operating_context.get(
                "temperature_c",
                analysis.get("operating_temperature_c"),
            )
            if operating_context.get("pressure_mpa") is not None:
                analysis["pressure_mpa"] = operating_context["pressure_mpa"]
            if operating_context.get("operating_hours") is not None:
                analysis["operating_hours"] = operating_context["operating_hours"]
            if operating_context.get("thermal_cycles") is not None:
                analysis["thermal_cycles_input"] = operating_context["thermal_cycles"]

            message = _build_thermal_summary(material_id, analysis)
            report = _build_thermal_report(material_id, analysis)

            await self.send_json_artifact(
                context=context,
                event_queue=event_queue,
                payload=analysis,
                name=f"{material_id.lower()}_{skill_id}",
                description=f"Thermal analysis result for {material_id}.",
                json_type=THERMAL_ANALYSIS_JSON_TYPE,
                catalog_artifact=True,
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
                "analysis_type": "thermal",
                "error": f"Analysis failed: {str(e)}",
            }


if __name__ == "__main__":
    agent = ThermalAnalysisAgent(agent_name="Thermal Analysis Agent")
    agent.run()
