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
Data Agent - Dummy specialist agent for material data retrieval.
Does not perform actual modeling and simulation work and contains a
small dataset generated with an open LLM model. Use this only for
orchestration debugging!
Implements A2A protocol using prometheus_api with Bearer token authentication
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict

from prometheus_api.agent import PrometheusAgent
from prometheus_api.llm_client import LLMConfig
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

ANALYSIS_PROMPT_TEMPLATE = """\
You are a materials engineer. Analyze this material data and provide expert insights.

Material ID: {material_id}
Data: {material_json}

Provide a brief expert commentary as a JSON object:
{{
    "material_assessment": "<brief assessment of material suitability>",
    "key_strengths": [<list of 2-3 key advantages>],
    "potential_concerns": [<list of 2-3 potential concerns>],
    "recommended_monitoring": [<list of 2-3 specific monitoring recommendations>],
    "compatibility_notes": "<brief note on compatibility with reactor environment>"
}}

Be concise and focus on actionable insights."""

# Simulated material database
MATERIAL_DATABASE = {
    "SS316": {
        "material_id": "SS316",
        "name": "Stainless Steel 316 - Primary Coolant Piping",
        "specification": "ASTM A312 Type 316",
        "composition": {
            "C": 0.08, "Cr": 17.0, "Ni": 12.0, "Mo": 2.5,
            "Mn": 2.0, "Si": 1.0, "P": 0.045, "S": 0.030, "Fe": "balance"
        },
        "mechanical_properties": {
            "yield_strength_mpa": 290,
            "tensile_strength_mpa": 580,
            "elongation_percent": 40,
            "hardness_hb": 217
        },
        "thermal_properties": {
            "conductivity_w_mk": 16.3,
            "expansion_coeff_per_k": 15.9e-6,
            "specific_heat_j_kgk": 500
        },
        "installation_date": "2018-06-15",
        "design_life_years": 40,
        "location": "Primary coolant loop piping",
        "operating_environment": {
            "temperature_range_c": [280, 343],
            "pressure_mpa": 15.5,
            "coolant": "Light water (H2O) with boric acid",
            "radiation_field": "Moderate neutron flux"
        }
    },
    "SS316L": {
        "material_id": "SS316L",
        "name": "Stainless Steel 316L - Heat Exchanger",
        "specification": "ASTM A240 Type 316L",
        "composition": {
            "C": 0.03, "Cr": 17.0, "Ni": 12.0, "Mo": 2.5,
            "Mn": 2.0, "Si": 1.0, "P": 0.045, "S": 0.030, "Fe": "balance"
        },
        "mechanical_properties": {
            "yield_strength_mpa": 270,
            "tensile_strength_mpa": 560,
            "elongation_percent": 45,
            "hardness_hb": 201
        },
        "thermal_properties": {
            "conductivity_w_mk": 16.3,
            "expansion_coeff_per_k": 15.9e-6,
            "specific_heat_j_kgk": 500
        },
        "installation_date": "2015-03-20",
        "design_life_years": 40,
        "location": "Heat exchanger tubes",
        "operating_environment": {
            "temperature_range_c": [200, 320],
            "pressure_mpa": 10.5,
            "coolant": "Demineralized water",
            "radiation_field": "Low"
        }
    },
    "SS304": {
        "material_id": "SS304",
        "name": "Stainless Steel 304 - Structural Components",
        "specification": "ASTM A240 Type 304",
        "composition": {
            "C": 0.08, "Cr": 19.0, "Ni": 9.0,
            "Mn": 2.0, "Si": 1.0, "P": 0.045, "S": 0.030, "Fe": "balance"
        },
        "mechanical_properties": {
            "yield_strength_mpa": 215,
            "tensile_strength_mpa": 505,
            "elongation_percent": 40,
            "hardness_hb": 201
        },
        "thermal_properties": {
            "conductivity_w_mk": 16.2,
            "expansion_coeff_per_k": 17.3e-6,
            "specific_heat_j_kgk": 500
        },
        "installation_date": "2012-09-10",
        "design_life_years": 40,
        "location": "Containment structure internals",
        "operating_environment": {
            "temperature_range_c": [20, 250],
            "pressure_mpa": 0.4,
            "coolant": "Air/steam atmosphere",
            "radiation_field": "Very low"
        }
    },
    "SS347": {
        "material_id": "SS347",
        "name": "Stainless Steel 347 - High Temperature Piping",
        "specification": "ASTM A312 Type 347",
        "composition": {
            "C": 0.08, "Cr": 18.0, "Ni": 11.0, "Nb": 0.8,
            "Mn": 2.0, "Si": 1.0, "P": 0.045, "S": 0.030, "Fe": "balance"
        },
        "mechanical_properties": {
            "yield_strength_mpa": 240,
            "tensile_strength_mpa": 550,
            "elongation_percent": 40,
            "hardness_hb": 201
        },
        "thermal_properties": {
            "conductivity_w_mk": 16.3,
            "expansion_coeff_per_k": 17.8e-6,
            "specific_heat_j_kgk": 500
        },
        "installation_date": "2016-11-05",
        "design_life_years": 40,
        "location": "Steam generator feedwater piping",
        "operating_environment": {
            "temperature_range_c": [250, 400],
            "pressure_mpa": 18.0,
            "coolant": "High-temperature water/steam",
            "radiation_field": "Low"
        }
    }
}


# Static records shared across the focused retrieval skills. In a real agent
# these would be looked up per material; here they are fixed debug fixtures.
INSPECTION_HISTORY = {
    "last_inspection": "2023-04-10",
    "inspection_type": "Ultrasonic Testing (UT)",
    "result": "acceptable",
    "inspections": [
        {"date": "2020-04-15", "type": "UT", "result": "acceptable", "defects_found": 0},
        {"date": "2021-10-20", "type": "VT", "result": "acceptable", "defects_found": 0},
        {"date": "2023-04-10", "type": "UT", "result": "acceptable", "defects_found": 0},
    ],
}

OPERATIONAL_HISTORY = {
    "operating_hours": 125000,
    "thermal_cycles": 1250,
    "repairs": [],
    "modifications": [],
}

REGULATORY_INFO = {
    "applicable_codes": [
        "ASME Section III",
        "ASME Section XI",
        "10 CFR 50.55a",
        "10 CFR 50.61",
    ],
    "limits": {
        "max_fluence_n_cm2": 1.0e20,
        "max_dbtt_shift_c": 55.6,
        "min_upper_shelf_energy_j": 68,
        "max_flaw_size_mm": 6.35,
        "max_creep_strain_percent": 1.0,
    },
    "inspection_requirements": {
        "volumetric_interval_years": 10,
        "surface_interval_years": 10,
        "visual_interval_years": 3,
    },
}


class MaterialDataAgent(PrometheusAgent):
    """Agent for material data retrieval."""

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """Route material-data requests on the invoked skill_id.

        Skills:
        - list_materials        — catalog of all materials (no material_id)
        - get_material_data      — full profile + AI interpretation
        - get_material_properties — composition + mechanical + thermal only
        - get_material_history   — inspection + operational history only
        - get_regulatory_limits  — regulatory codes and limits only
        """
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Parsing material data request.",
        )

        material_id = params.get("material_id")

        # The base executor injects the invoked skill as params["skill_id"].
        # When absent (direct call), default by presence of a material_id.
        skill_id = str(params.get("skill_id") or "").strip()
        if not skill_id:
            skill_id = "list_materials" if not material_id else "get_material_data"

        if skill_id == "list_materials":
            return await self._list_materials(context, event_queue)

        # Every other skill needs a known material_id.
        if not material_id:
            return {
                "error": "Parameter 'material_id' is required for this skill.",
                "skill_id": skill_id,
                "available_materials": list(MATERIAL_DATABASE.keys()),
            }
        if material_id not in MATERIAL_DATABASE:
            return {
                "error": f"Material {material_id} not found",
                "skill_id": skill_id,
                "available_materials": list(MATERIAL_DATABASE.keys()),
            }

        material = MATERIAL_DATABASE[material_id]
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Retrieving '{skill_id}' for material {material_id}.",
        )

        if skill_id == "get_material_properties":
            return self._material_properties(material_id, material)
        if skill_id == "get_material_history":
            return self._material_history(material_id)
        if skill_id == "get_regulatory_limits":
            return self._regulatory_limits(material_id)
        # get_material_data (and any unknown skill) → full profile + interpretation.
        return await self._material_data(material_id, material, context, event_queue)

    async def _list_materials(
        self, context: RequestContext, event_queue: EventQueue
    ) -> Dict[str, Any]:
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Listing all available materials.",
        )
        materials = [
            {
                "material_id": mat_id,
                "name": data["name"],
                "specification": data["specification"],
                "max_temp_c": data["operating_environment"]["temperature_range_c"][1],
                "applications": data["location"],
            }
            for mat_id, data in MATERIAL_DATABASE.items()
        ]
        return {
            "query_type": "list_materials",
            "skill_id": "list_materials",
            "materials": materials,
            "count": len(materials),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _material_properties(material_id: str, material: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "query_type": "material_properties",
            "skill_id": "get_material_properties",
            "material_id": material_id,
            "specification": material.get("specification"),
            "composition": material.get("composition"),
            "mechanical_properties": material.get("mechanical_properties"),
            "thermal_properties": material.get("thermal_properties"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _material_history(material_id: str) -> Dict[str, Any]:
        return {
            "query_type": "material_history",
            "skill_id": "get_material_history",
            "material_id": material_id,
            "inspection_history": INSPECTION_HISTORY,
            "operational_history": OPERATIONAL_HISTORY,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _regulatory_limits(material_id: str) -> Dict[str, Any]:
        return {
            "query_type": "regulatory_limits",
            "skill_id": "get_regulatory_limits",
            "material_id": material_id,
            "regulatory_info": REGULATORY_INFO,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _material_data(
        self,
        material_id: str,
        material: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """Full material profile plus an AI interpretation."""
        base_data = {
            "material_id": material_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_type": "material_data",
            "skill_id": "get_material_data",
            "material_data": material,
            "inspection_history": INSPECTION_HISTORY,
            "operational_history": OPERATIONAL_HISTORY,
            "regulatory_info": REGULATORY_INFO,
        }

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message="Generating expert interpretation.",
        )
        try:
            prompt = ANALYSIS_PROMPT_TEMPLATE.format(
                material_id=material_id,
                material_json=json.dumps(material, indent=2),
            )

            llm_config = LLMConfig.from_env()
            async with self.llm_client(context, config=llm_config) as llm:
                response = await llm.medium(
                    prompt,
                    max_tokens=1024,
                )

            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            base_data["ai_interpretation"] = json.loads(response_text)
            base_data["model_used"] = response.provider_model or response.model_alias
            await self.send_status_update(
                context=context,
                event_queue=event_queue,
                message="Expert interpretation complete.",
            )
        except Exception as e:
            base_data["ai_interpretation"] = {"error": f"Interpretation failed: {str(e)}"}
            await self.send_status_update(
                context=context,
                event_queue=event_queue,
                message="Interpretation failed; returning base material data.",
            )

        return base_data


if __name__ == "__main__":
    agent = MaterialDataAgent(agent_name="Material Data Agent")
    agent.run()
