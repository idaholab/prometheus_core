from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from artifact_handling import resolve_artifact_inputs, summarize_artifacts_for_context
from capability_cache import get_capability_cache
from param_schema import (
    extract_required_param_paths,
    flatten_schema_properties,
    get_nested_value,
    has_param_path,
    set_nested_value,
)
from workflow_library import get_workflow_registry

from . import runtime
from .utils import get_value_by_path, normalize_by_mode, rule_matches_query, set_param_path


def get_selected_skills(routing_decision: Optional[Dict[str, Any]]) -> List[str]:
    """Return a stable, deduplicated ordered list of skills to invoke."""
    if not routing_decision:
        return []
    skills: List[str] = []
    primary = routing_decision.get("primary_skill")
    if primary:
        skills.append(primary)
    for skill in routing_decision.get("supporting_skills", []):
        if skill and skill not in skills:
            skills.append(skill)
    return skills


async def resolve_user_required_params(routing_decision: Optional[Dict[str, Any]]) -> List[str]:
    """Resolve user-provided required params for the current routing decision."""
    if not routing_decision:
        return []

    workflow_type = routing_decision.get("workflow_type")
    workflow_id = routing_decision.get("workflow_id")
    workflow_version = routing_decision.get("workflow_version")
    if workflow_type == "workflow_template" and workflow_id and runtime.ENABLE_WORKFLOW_LIBRARY:
        workflow = get_workflow_registry().get(str(workflow_id), version=workflow_version)
        if workflow:
            return sorted(set(workflow.required_input_paths))

    cache = get_capability_cache()
    required: set[str] = set()
    for skill_id in get_selected_skills(routing_decision):
        capability = await cache.get_capability_by_skill_id(skill_id)
        if not capability:
            continue
        required.update(extract_required_param_paths(capability.input_schema))

    if required:
        return sorted(required)
    return sorted(set(routing_decision.get("required_params", []) or []))


def order_skills_for_workflow(routing_decision: Optional[Dict[str, Any]]) -> List[str]:
    """Return selected skills ordered for the requested workflow semantics.

    For sequential workflows, orders skills based on metadata from agent cards:
    - execution_priority: "early", "normal", or "late"
    - usage_notes: Explicit hints like "call this first"
    - provides/derivation_rules: Skills that provide context run before consumers

    This is fully data-driven - no hardcoded domain knowledge about what skills do.

    Args:
        routing_decision: Dict with workflow_type and selected skills

    Returns:
        List of skill_ids in execution order
    """
    skills = get_selected_skills(routing_decision)
    if not skills or len(skills) <= 1:
        return skills
    if not routing_decision or routing_decision.get("workflow_type") != "sequential":
        return skills

    cache = get_capability_cache()
    scored: List[Any] = []

    # Build map of which skills provide context keys
    providers: Dict[str, List[str]] = {}  # context_key -> [skill_ids that provide it]
    for skill_id in skills:
        capability = cache.get_by_skill_id(skill_id)
        if capability and capability.provides:
            for provide_rule in capability.provides:
                if isinstance(provide_rule, dict) and provide_rule.get("type") == "context_map":
                    context_key = provide_rule.get("context_key")
                    if context_key:
                        if context_key not in providers:
                            providers[context_key] = []
                        providers[context_key].append(skill_id)

    for idx, skill_id in enumerate(skills):
        capability = cache.get_by_skill_id(skill_id)
        usage_notes = (capability.usage_notes or "").lower() if capability else ""

        # Lower score means earlier execution
        score = idx * 100  # Preserve original order by default

        # 1. Use execution_priority from agent card metadata
        if capability and capability.execution_priority:
            priority_map = {"early": -500, "normal": 0, "late": 500}
            score += priority_map.get(capability.execution_priority, 0)

        # 2. Explicit prerequisite hint from usage_notes
        if "always call this first" in usage_notes or "call this first" in usage_notes:
            score -= 1000

        # 3. Skills that provide context should run before skills that consume it
        if capability and capability.provides:
            score -= 200  # Provider skills run early

        # 4. Skills with derivation rules are consumers, should run later
        if capability and capability.derivation_rules:
            # Check if this skill derives params from context maps
            for rule in capability.derivation_rules:
                if isinstance(rule, dict):
                    derive = rule.get("derive", {})
                    if isinstance(derive, dict) and derive.get("type") == "from_context_map":
                        context_key = derive.get("context_key")
                        # If there's a provider for this context in the selected skills, run after it
                        if context_key and context_key in providers:
                            score += 300
                            break

        scored.append((score, idx, skill_id))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [skill_id for _, _, skill_id in scored]


def _humanize_param_path(path: str) -> str:
    """Convert dotted param path into a readable fallback label."""
    token = str(path or "").split(".")[-1]
    return token.replace("_", " ").strip().capitalize() or str(path)


def build_plan_param_metadata(
    selected_skills: List[str],
    capabilities_by_skill: Dict[str, Any],
    selected_workflow: Optional[Any] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build UI-friendly param metadata (label/description/type/unit) for plan display."""
    metadata: Dict[str, Dict[str, Any]] = {}
    properties: Dict[str, Dict[str, Any]] = {}

    for skill_id in selected_skills:
        capability = capabilities_by_skill.get(skill_id)
        if not capability:
            continue
        properties.update(flatten_schema_properties(capability.input_schema))

    for path, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        is_object = prop.get("type") == "object" or "properties" in prop
        if is_object:
            continue
        metadata[path] = {
            "label": str(prop.get("title") or _humanize_param_path(path)),
            "description": str(prop.get("description") or "").strip(),
            "type": prop.get("type"),
            "unit": prop.get("unit"),
        }

    if selected_workflow is not None:
        overrides = (selected_workflow.definition.ui.input_overrides or {})
        for path, override in overrides.items():
            entry = dict(metadata.get(path, {}))
            label = getattr(override, "label", None)
            description = getattr(override, "description", None)
            field_type = getattr(override, "type", None)
            unit = getattr(override, "unit", None)

            if label:
                entry["label"] = str(label)
            elif "label" not in entry:
                entry["label"] = _humanize_param_path(path)

            if description:
                entry["description"] = str(description).strip()
            elif "description" not in entry:
                entry["description"] = ""

            if field_type:
                entry["type"] = field_type
            if unit:
                entry["unit"] = unit
            metadata[path] = entry

    return metadata


def merge_context_map(target_context: Dict[str, Any], context_key: str, entries: Dict[str, Any]) -> None:
    """Merge entries into a context map key (supports dotted context key paths)."""
    if not entries:
        return
    existing = get_nested_value(target_context, context_key)
    existing_map = existing if isinstance(existing, dict) else {}
    merged = {**existing_map, **entries}
    if "." in context_key:
        set_nested_value(target_context, context_key, merged)
    else:
        target_context[context_key] = merged


def extract_provided_context_maps(
    result_data: Any,
    provides: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Extract context-map entries from a skill result using metadata rules.

    Context maps enable data sharing between skills in sequential workflows.
    A skill can declare that it "provides" certain context (e.g., material_max_temps)
    which downstream skills can then derive parameters from.

    This function applies metadata-defined extraction rules from the agent card's
    "provides" field to extract key-value pairs from the skill result.

    Example rule:
    {
        "type": "context_map",
        "context_key": "material_max_temps",
        "item_key_path": "material_id",
        "item_value_path": "operating_environment.temperature_range_c.1",
        "key_normalizer": "upper_no_space_hyphen",
        "value_type": "number"
    }

    Args:
        result_data: The skill invocation result
        provides: List of context_map rules from agent card

    Returns:
        Dict mapping context_key to extracted key-value pairs
    """
    extracted: Dict[str, Dict[str, Any]] = {}
    if not isinstance(result_data, dict):
        return extracted

    for rule in provides or []:
        if not isinstance(rule, dict) or rule.get("type") != "context_map":
            continue

        context_key = rule.get("context_key")
        item_key_path = rule.get("item_key_path")
        item_value_path = rule.get("item_value_path")
        key_normalizer = rule.get("key_normalizer")
        value_type = rule.get("value_type")
        if not context_key or not item_value_path:
            continue

        # Extract entries from result (handles both single-item and by_material batch results)
        entries: Dict[str, Any] = {}
        candidates: List[Any] = [result_data]
        by_material = result_data.get("by_material")
        if isinstance(by_material, dict):
            candidates = list(by_material.values())

        for candidate in candidates:
            # Extract key (e.g., material_id)
            key_value = get_value_by_path(candidate, item_key_path)
            if key_value is None and isinstance(candidate, dict):
                key_value = candidate.get("material_id")
            if key_value is None:
                continue

            # Extract value (e.g., max temperature)
            value = get_value_by_path(candidate, item_value_path)
            if value is None:
                continue
            if value_type == "number" and not isinstance(value, (int, float)):
                try:
                    value = float(value)
                except Exception:
                    continue

            # Normalize key (e.g., "SS-316L" → "SS316L")
            normalized_key = normalize_by_mode(key_value, key_normalizer)
            if normalized_key is None:
                continue
            entries[str(normalized_key)] = value

        if entries:
            existing = extracted.get(context_key, {})
            extracted[context_key] = {**existing, **entries}

    return extracted


def collect_context_maps_from_history(
    conversation_history: List[Dict[str, Any]],
    capabilities_by_skill: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Rebuild context maps from prior tool results using capability metadata.

    In multi-turn conversations, we need to remember context provided by earlier
    skill invocations. This function replays the conversation history and re-extracts
    all context maps using the same metadata rules that were applied originally.

    This enables parameter derivation in later turns to use data from earlier turns
    (e.g., using max_temp retrieved in turn 1 for analysis in turn 2).

    Args:
        conversation_history: List of conversation messages with tool_results
        capabilities_by_skill: Map of skill_id to AgentCapability with "provides" metadata

    Returns:
        Aggregated context maps from all history
    """
    aggregated: Dict[str, Dict[str, Any]] = {}
    for message in conversation_history or []:
        tool_results = message.get("tool_results")
        if not isinstance(tool_results, dict):
            continue
        for skill_id, result_data in tool_results.items():
            capability = capabilities_by_skill.get(skill_id)
            if not capability:
                continue
            # Re-extract context maps using capability metadata
            extracted = extract_provided_context_maps(result_data, capability.provides)
            for context_key, entries in extracted.items():
                current = aggregated.get(context_key, {})
                aggregated[context_key] = {**current, **entries}
    return aggregated


def attach_artifact_context(
    params: Optional[Dict[str, Any]],
    context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Attach conversation artifact metadata to downstream skill invocations."""
    merged = dict(params or {})
    if "artifacts" not in merged:
        artifacts = summarize_artifacts_for_context((context or {}).get("artifacts"))
        if artifacts:
            merged["artifacts"] = artifacts
    return merged


def derive_params_from_rules(
    query: str,
    params: Dict[str, Any],
    rules: List[Dict[str, Any]],
    context: Dict[str, Any],
    history_context_maps: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Derive missing parameter values from metadata-defined derivation rules.

    Derivation rules enable skills to automatically populate parameters from context
    without user input. For example, a rule might say "derive max_temperature from
    the material_max_temps context map using material_id as the lookup key."

    Example derivation rule:
    {
        "target_param": "context.max_temperature_c",
        "derive": {
            "type": "from_context_map",
            "context_key": "material_max_temps",
            "lookup_key_param": "material_id",
            "key_normalizer": "upper_no_space_hyphen",
            "value_type": "number"
        },
        "when": {"phrases_any": ["maximum", "max temp"]}
    }

    Args:
        query: User query (for conditional rule matching)
        params: Current parameters
        rules: Derivation rules from agent card
        context: Current context with context maps
        history_context_maps: Context maps from conversation history

    Returns:
        Parameters with derived values added
    """
    derived = dict(params)

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        target_param = rule.get("target_param")
        derive = rule.get("derive", {})
        if not target_param or not isinstance(derive, dict):
            continue
        # Skip if parameter already has a value
        if has_param_path(derived, target_param):
            continue
        # Check rule conditions (e.g., "when query contains 'maximum'")
        if not rule_matches_query(query, rule):
            continue

        # Currently only supports "from_context_map" derivation type
        if derive.get("type") != "from_context_map":
            continue

        context_key = derive.get("context_key")
        lookup_key_param = derive.get("lookup_key_param", "material_id")
        key_normalizer = derive.get("key_normalizer")
        value_type = derive.get("value_type")
        if not context_key:
            continue

        # Get the lookup key value (e.g., "SS316" from params["material_id"])
        lookup_key = get_nested_value(derived, lookup_key_param)
        if lookup_key is None:
            lookup_key = derived.get(lookup_key_param)
        if isinstance(lookup_key, list) and lookup_key:
            lookup_key = lookup_key[0]
        lookup_key = normalize_by_mode(lookup_key, key_normalizer)
        if lookup_key is None:
            continue

        # Look up value in context map (merged with history)
        value_map = get_nested_value(context, context_key)
        map_data: Dict[str, Any] = value_map if isinstance(value_map, dict) else {}
        if context_key in history_context_maps:
            map_data = {**history_context_maps[context_key], **map_data}

        value = map_data.get(str(lookup_key))
        if value is None:
            continue
        # Type conversion if needed
        if value_type == "number" and not isinstance(value, (int, float)):
            try:
                value = float(value)
            except Exception:
                continue

        # Set the derived parameter
        set_param_path(derived, target_param, value)

    return derived


async def resolve_params_via_capability_metadata(
    query: str,
    extracted_params: Optional[Dict[str, Any]],
    selected_skills: List[str],
    context: Optional[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve missing params using capability `derivation_rules` metadata.

    This is the core parameter resolution engine that enables fully data-driven workflows.
    It performs a multi-step process to automatically derive missing parameters:

    1. Rebuild context maps from conversation history
    2. Carry forward known context fields into params
    3. Identify which context maps are needed for pending derivation rules
    4. Prefetch missing context by invoking provider skills (if safe/no-approval)
    5. Apply derivation rules to populate missing parameters

    This enables complex workflows where:
    - Skill A provides data (e.g., max_temperature)
    - Skill B derives parameters from that data (e.g., for analysis)
    - All without hardcoded logic - purely driven by agent card metadata

    Args:
        query: User query
        extracted_params: Parameters extracted from query
        selected_skills: Skills selected by routing decision
        context: Current context state
        conversation_history: Previous conversation turns

    Returns:
        Parameters with derived values added
    """
    params = dict(extracted_params or {})
    if not selected_skills:
        return params

    # Step 1: Look up capability metadata for selected skills
    cache = get_capability_cache()
    capabilities_by_skill: Dict[str, Any] = {}
    for skill_id in selected_skills:
        capability = await cache.get_capability_by_skill_id(skill_id)
        if capability:
            capabilities_by_skill[skill_id] = capability

    # Include all provider skills for history reconstruction
    # (even if not currently selected, we need their context maps from history)
    all_capabilities = await cache.get_capabilities()
    for capability in all_capabilities:
        if capability.provides and capability.skill_id not in capabilities_by_skill:
            capabilities_by_skill[capability.skill_id] = capability

    if not capabilities_by_skill:
        return params

    # Step 2: Rebuild context maps from conversation history
    history_context_maps = collect_context_maps_from_history(
        conversation_history,
        capabilities_by_skill,
    )
    merged_context = dict(context or {})
    for context_key, entries in history_context_maps.items():
        merge_context_map(merged_context, context_key, entries)

    # Step 3: Build effective query including recent user intents for rule matching
    recent_user_intents = [
        str(msg.get("content", ""))
        for msg in (conversation_history or [])[-8:]
        if msg.get("role") == "user" and msg.get("content")
    ]
    effective_query = " ".join([query or "", *recent_user_intents]).strip()
    if not effective_query:
        effective_query = query or ""

    # Step 4: Carry forward known context fields into params for required context.* paths
    selected_input_schemas: List[Dict[str, Any]] = []
    for skill_id in selected_skills:
        capability = capabilities_by_skill.get(skill_id)
        if not capability:
            continue
        if isinstance(capability.input_schema, dict):
            selected_input_schemas.append(capability.input_schema)
        required_paths = extract_required_param_paths(capability.input_schema)
        for path in required_paths:
            if not path.startswith("context.") or has_param_path(params, path):
                continue
            value = get_nested_value(merged_context, path)
            if value is not None:
                set_param_path(params, path, value)

    # Step 4b: Resolve declared artifact-reference params from conversation artifact metadata.
    params = resolve_artifact_inputs(
        params=params,
        query=effective_query,
        context=merged_context,
        input_schemas=selected_input_schemas,
    )

    # Step 5: Identify pending derivation rules and needed context maps
    pending_rules: List[Dict[str, Any]] = []
    for skill_id in selected_skills:
        capability = capabilities_by_skill.get(skill_id)
        if not capability:
            continue
        for rule in capability.derivation_rules or []:
            if not isinstance(rule, dict):
                continue
            target_param = rule.get("target_param")
            derive = rule.get("derive", {})
            if not target_param or not isinstance(derive, dict):
                continue
            if derive.get("type") != "from_context_map":
                continue
            if has_param_path(params, target_param):
                continue
            if not rule_matches_query(effective_query, rule):
                continue
            pending_rules.append(rule)

    needed_context_keys = {
        rule.get("derive", {}).get("context_key")
        for rule in pending_rules
        if isinstance(rule.get("derive"), dict)
    }
    needed_context_keys = {
        key for key in needed_context_keys
        if key and (
            not isinstance(get_nested_value(merged_context, key), dict)
            or not get_nested_value(merged_context, key)
        )
    }

    # Step 6: Metadata-driven prefetch - invoke provider skills to populate needed context
    # Only invoke skills that don't require approval and whose params are satisfied
    if needed_context_keys:
        for skill_id, capability in capabilities_by_skill.items():
            if not capability or capability.requires_approval or not capability.provides:
                continue
            provided_keys = {
                p.get("context_key")
                for p in capability.provides
                if isinstance(p, dict) and p.get("type") == "context_map" and p.get("context_key")
            }
            if not provided_keys.intersection(needed_context_keys):
                continue

            required_paths = extract_required_param_paths(capability.input_schema)
            if not all(has_param_path(params, path) for path in required_paths):
                continue

            # Prefetch: invoke the provider skill
            prefetched = await invoke_skill(
                skill_id,
                params,
                conversation_id=f"prefetch-{uuid.uuid4()}",
                emit_status=False,
            )
            if "result" not in prefetched:
                continue

            # Extract and merge context maps from prefetch result
            extracted_maps = extract_provided_context_maps(prefetched["result"], capability.provides)
            for context_key, entries in extracted_maps.items():
                merge_context_map(merged_context, context_key, entries)
                current = history_context_maps.get(context_key, {})
                history_context_maps[context_key] = {**current, **entries}

            # Update needed keys
            needed_context_keys = {
                key for key in needed_context_keys
                if (
                    not isinstance(get_nested_value(merged_context, key), dict)
                    or not get_nested_value(merged_context, key)
                )
            }
            if not needed_context_keys:
                break

    # Step 7: Apply derivation rules to populate missing parameters
    for skill_id in selected_skills:
        capability = capabilities_by_skill.get(skill_id)
        if not capability:
            continue
        params = derive_params_from_rules(
            query=effective_query,
            params=params,
            rules=capability.derivation_rules,
            context=merged_context,
            history_context_maps=history_context_maps,
        )

    return params
