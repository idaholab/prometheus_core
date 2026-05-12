from __future__ import annotations

import json
from typing import Any, Dict

from capability_cache import get_capability_cache
from param_schema import (
    extract_required_param_paths,
    has_param_path,
    normalize_params_for_input_schema,
)

from . import runtime


async def find_tool_for_skill(skill_id: str, refresh_on_miss: bool = True):
    """Find tool by skill id and optionally refresh discovery once on cache miss."""
    for tool in runtime.create_tools():
        if tool.name == skill_id:
            return tool

    if refresh_on_miss:
        await runtime.refresh_dynamic_components(trigger=f"tool_miss:{skill_id}")
        for tool in runtime.create_tools():
            if tool.name == skill_id:
                return tool

    return None


async def invoke_skill(
    skill_id: str,
    params: Dict[str, Any],
    conversation_id: str,
    emit_status: bool = True,
) -> Dict[str, Any]:
    """Invoke a single discovered skill with validation and normalized output."""
    if emit_status:
        runtime.store_status_update(conversation_id, f"Invoking '{skill_id}'.")
    tool = await find_tool_for_skill(skill_id, refresh_on_miss=True)
    if not tool:
        if emit_status:
            runtime.store_status_update(conversation_id, f"Capability '{skill_id}' is currently unavailable.")
        return {
            "skill_id": skill_id,
            "error": f"Capability '{skill_id}' is not currently available.",
        }

    cache = get_capability_cache()
    capability = await cache.get_capability_by_skill_id(skill_id)

    required_params = extract_required_param_paths(capability.input_schema) if capability else []
    material_ids = params.get("material_ids")

    async def invoke_once(single_params: Dict[str, Any]) -> Dict[str, Any]:
        input_schema = capability.input_schema if capability else None
        invoke_params = normalize_params_for_input_schema(dict(single_params), input_schema=input_schema)
        invoke_params["conversation_id"] = conversation_id
        if capability and getattr(capability, "supports_streaming", False):
            async def _status_callback(message: str) -> None:
                text = str(message or "").strip()
                if text:
                    runtime.store_status_update(conversation_id, f"[{skill_id}] {text}")

            invoke_params["_status_callback"] = _status_callback
        missing = [param for param in required_params if not has_param_path(invoke_params, param)]
        if missing:
            if emit_status:
                runtime.store_status_update(
                    conversation_id,
                    f"Missing required parameters for '{skill_id}': {', '.join(missing)}.",
                )
            return {
                "error": f"Missing required parameters for '{skill_id}': {missing}",
                "missing_required_params": missing,
            }
        try:
            raw_result = await tool.ainvoke(invoke_params)
            if isinstance(raw_result, str):
                try:
                    result_data = json.loads(raw_result)
                except json.JSONDecodeError:
                    result_data = {"raw_response": raw_result}
            else:
                result_data = raw_result
            if isinstance(result_data, dict) and result_data.get("status") == "input_required":
                return {
                    "input_required": result_data.get("input_required", {}),
                    "_a2a_context_id": result_data.get("_a2a_context_id"),
                    "_a2a_task_id": result_data.get("_a2a_task_id"),
                }
            if isinstance(result_data, dict) and result_data.get("error"):
                missing = [param for param in required_params if not has_param_path(invoke_params, param)]
                payload = {"error": str(result_data.get("error"))}
                if missing:
                    payload["missing_required_params"] = missing
                return payload
            if emit_status:
                runtime.store_status_update(conversation_id, f"'{skill_id}' completed.")
            return {"result": result_data}
        except Exception as e:
            if emit_status:
                runtime.store_status_update(conversation_id, f"'{skill_id}' failed: {e}")
            return {"error": str(e)}

    # Batch path for comparison-style queries with multiple material IDs
    if "material_id" in required_params and isinstance(material_ids, list) and len(material_ids) > 1:
        by_material: Dict[str, Any] = {}
        errors: Dict[str, Any] = {}
        for material_id in material_ids:
            single = dict(params)
            single.pop("material_ids", None)
            single["material_id"] = material_id
            one = await invoke_once(single)
            if "input_required" in one:
                return {
                    "skill_id": skill_id,
                    "input_required": one["input_required"],
                    "_a2a_context_id": one.get("_a2a_context_id"),
                    "_a2a_task_id": one.get("_a2a_task_id"),
                }
            if "error" in one:
                errors[material_id] = one["error"]
            else:
                by_material[material_id] = one.get("result")

        if errors and not by_material:
            return {"skill_id": skill_id, "error": json.dumps(errors)}

        result_payload: Dict[str, Any] = {
            "materials": material_ids,
            "by_material": by_material,
        }
        if errors:
            result_payload["partial_errors"] = errors
        return {"skill_id": skill_id, "result": result_payload}

    one = await invoke_once(params)
    if "input_required" in one:
        return {
            "skill_id": skill_id,
            "input_required": one["input_required"],
            "_a2a_context_id": one.get("_a2a_context_id"),
            "_a2a_task_id": one.get("_a2a_task_id"),
        }
    if "error" in one:
        item = {"skill_id": skill_id, "error": one["error"]}
        if one.get("missing_required_params"):
            item["missing_required_params"] = one["missing_required_params"]
        return item
    return {"skill_id": skill_id, "result": one.get("result")}
