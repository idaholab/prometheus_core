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
Radiation Damage Agent -  Dummy specialist agent for radiation damage analysis.
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

RADIATION_DAMAGE_JSON_TYPE = "prometheus.radiation_damage.result.v1"

# Skill routing: the invoked skill (params["skill_id"]) selects a focus the
# model emphasizes on top of the shared structured analysis.
DEFAULT_SKILL = "analyze_radiation_damage"
SKILL_FOCUS = {
    "analyze_radiation_damage": "Provide the full radiation damage analysis across every field.",
    "calculate_dpa": (
        "Prioritize the displacement damage calculation: dpa, total_fluence_n_cm2, "
        "and fluence_spectrum are the key outputs."
    ),
    "assess_embrittlement": (
        "Prioritize embrittlement and regulatory margin: dbtt_shift_c, "
        "regulatory_compliance, and remaining_service_life_years are the key outputs."
    ),
}

ANALYSIS_PROMPT_TEMPLATE = """\
You are a radiation damage specialist. Analyze radiation-induced damage for material: {material_id}
{context_str}
Provide a comprehensive radiation damage analysis as a JSON object with this structure:
{{
    "total_fluence_n_cm2": <scientific notation as float>,
    "dpa": <float, displacements per atom>,
    "dbtt_shift_c": <float, ductile-to-brittle transition temperature shift in Celsius>,
    "void_swelling_percent": <float>,
    "helium_concentration_appm": <float, atomic parts per million>,
    "hydrogen_concentration_appm": <float>,
    "fluence_spectrum": {{
        "thermal": <float>,
        "epithermal": <float>,
        "fast": <float>
    }},
    "damage_mechanisms": [<list of active damage mechanisms>],
    "structural_integrity": "<acceptable/degraded/critical>",
    "remaining_service_life_years": <float>,
    "surveillance_capsule_data": {{
        "capsules_remaining": <int>,
        "next_withdrawal_date": "<ISO date>"
    }},
    "recommendations": [<list of specific recommendations>],
    "regulatory_compliance": {{
        "regulatory_limit_dbtt_c": 93.3,
        "margin_to_limit_c": <float>,
        "status": "<within_limits/approaching_limit/exceeds_limit>"
    }},
    "confidence": <float 0-1>
}}

Consider neutron embrittlement, void swelling, helium embrittlement, and transmutation effects. Follow 10 CFR 50.61 regulatory limits."""


def _build_radiation_summary(material_id: str, analysis: Dict[str, Any]) -> str:
    integrity = str(analysis.get("structural_integrity") or "unknown")
    dpa = analysis.get("dpa")
    remaining_life = analysis.get("remaining_service_life_years")

    parts: List[str] = [f"Radiation damage analysis for {material_id} completed."]
    if dpa is not None:
        parts.append(f"Accumulated DPA: {dpa:.2f}.")
    if remaining_life is not None:
        parts.append(f"Estimated remaining service life: {remaining_life:.1f} years.")
    parts.append(f"Structural integrity: {integrity}.")
    return " ".join(parts)


def _build_radiation_report(material_id: str, analysis: Dict[str, Any]) -> str:
    integrity = str(analysis.get("structural_integrity") or "unknown")
    confidence = analysis.get("confidence")
    mechanisms = analysis.get("damage_mechanisms") or []
    recommendations = analysis.get("recommendations") or []
    fluence_spectrum = analysis.get("fluence_spectrum") or {}
    surveillance = analysis.get("surveillance_capsule_data") or {}
    regulatory = analysis.get("regulatory_compliance") or {}

    lines = [
        f"Radiation Damage Analysis for {material_id}",
        "",
        f"- Structural integrity: {integrity}",
        f"- Confidence: {confidence}",
        f"- Total fluence: {analysis.get('total_fluence_n_cm2')} n/cm²",
        f"- DPA: {analysis.get('dpa')}",
        f"- DBTT shift: {analysis.get('dbtt_shift_c')} C",
        f"- Void swelling: {analysis.get('void_swelling_percent')} %",
        f"- Helium concentration: {analysis.get('helium_concentration_appm')} appm",
        f"- Hydrogen concentration: {analysis.get('hydrogen_concentration_appm')} appm",
        f"- Remaining service life: {analysis.get('remaining_service_life_years')} years",
        "",
        "Fluence spectrum:",
        f"- Thermal: {fluence_spectrum.get('thermal')}",
        f"- Epithermal: {fluence_spectrum.get('epithermal')}",
        f"- Fast: {fluence_spectrum.get('fast')}",
        "",
        "Surveillance capsule data:",
        f"- Capsules remaining: {surveillance.get('capsules_remaining')}",
        f"- Next withdrawal: {surveillance.get('next_withdrawal_date')}",
        "",
        "Regulatory compliance:",
        f"- Regulatory DBTT limit: {regulatory.get('regulatory_limit_dbtt_c')} C",
        f"- Margin to limit: {regulatory.get('margin_to_limit_c')} C",
        f"- Status: {regulatory.get('status')}",
    ]

    if mechanisms:
        lines.extend(["", "Active damage mechanisms:"])
        for m in mechanisms:
            lines.append(f"- {m}")

    if recommendations:
        lines.extend(["", "Recommendations:"])
        for item in recommendations:
            lines.append(f"- {item}")

    return "\n".join(lines)


class RadiationDamageAgent(PrometheusAgent):
    """Agent for radiation damage analysis."""

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
        for key in ("temperature_c", "pressure_mpa", "operating_hours"):
            resolved[key] = params[key] if params.get(key) is not None else operating_context.get(key)
        return resolved

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """
        Perform radiation damage analysis using the configured LLM.

        Generates expert-level radiation damage analysis from material properties
        and operating conditions.
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
                        description="Canonical material identifier for the radiation damage analysis.",
                        user_prompt="Which material should I analyze for radiation damage?",
                        type="string",
                        resolvable_from_context=True,
                    )
                ],
                hint="I need the target material before I can run the radiation damage analysis.",
            )
            return {"status": "input_required"}

        # Send status update
        await self.send_status_update(context=context, event_queue=event_queue)

        operating_context = {
            "temperature_c": resolved.get("temperature_c"),
            "pressure_mpa": resolved.get("pressure_mpa"),
            "operating_hours": resolved.get("operating_hours"),
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
            analysis["analysis_type"] = "radiation_damage"
            analysis["skill_id"] = skill_id
            analysis["model_used"] = response.provider_model or response.model_alias

            message = _build_radiation_summary(material_id, analysis)
            report = _build_radiation_report(material_id, analysis)

            await self.send_json_artifact(
                context=context,
                event_queue=event_queue,
                payload=analysis,
                name=f"{material_id.lower()}_{skill_id}",
                description=f"Radiation damage analysis result for {material_id}.",
                json_type=RADIATION_DAMAGE_JSON_TYPE,
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
                "analysis_type": "radiation_damage",
                "error": f"Analysis failed: {str(e)}",
            }


if __name__ == "__main__":
    agent = RadiationDamageAgent(agent_name="Radiation Damage Analysis Agent")
    agent.run()
