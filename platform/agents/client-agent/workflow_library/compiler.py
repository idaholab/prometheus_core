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

"""Workflow compiler and validator."""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

from google.adk.agents import Context
from google.adk.events import RequestInput
from google.adk.workflow import START, Edge, FunctionNode, JoinNode, Workflow

from .binding import get_path, resolve_step_params, set_path
from .naming import workflow_slug, workflow_tool_name
from .schema import CompiledPattern, CompiledWorkflow, WorkflowDefinition, WorkflowStep

if TYPE_CHECKING:
    from capability_cache import AgentCapability
else:
    AgentCapability = Any


class WorkflowCompileError(ValueError):
    """Raised when workflow validation fails in strict mode."""


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _compile_pattern(pattern: str) -> CompiledPattern:
    """Compile `{field}` placeholders into deterministic regex with named groups."""
    placeholder_names = _PLACEHOLDER_RE.findall(pattern)
    regex_pattern = ""
    idx = 0
    for match in _PLACEHOLDER_RE.finditer(pattern):
        start, end = match.span()
        regex_pattern += re.escape(pattern[idx:start])
        name = match.group(1).replace(".", "_")
        regex_pattern += rf"(?P<{name}>[^\s,;]+)"
        idx = end
    regex_pattern += re.escape(pattern[idx:])
    compiled = re.compile(regex_pattern, flags=re.IGNORECASE)
    specificity = len([ch for ch in pattern if ch not in "{}"]) + len(placeholder_names) * 5
    return CompiledPattern(
        source=pattern,
        regex=compiled,
        placeholder_names=placeholder_names,
        specificity=specificity,
    )


def _extract_input_binding_refs(
    value: Any,
    refs: List[Tuple[str, bool]],
    inherited_optional: bool = False,
) -> None:
    """Collect `input.*` binding refs with effective optionality.

    Optionality is inherited through nested binding nodes so parent-level
    optional sections do not accidentally become required workflow inputs.
    """
    if isinstance(value, dict):
        optional = inherited_optional or bool(value.get("optional", False))
        if "from" in value and isinstance(value.get("from"), str):
            source = str(value["from"])
            if source.startswith("input."):
                refs.append((source[len("input.") :], optional))
            return
        for v in value.values():
            _extract_input_binding_refs(v, refs, inherited_optional=optional)
    elif isinstance(value, list):
        for item in value:
            _extract_input_binding_refs(item, refs, inherited_optional=inherited_optional)


def _extract_required_schema_paths(schema: Dict[str, Any], prefix: str = "") -> List[str]:
    """Extract required leaf paths from a JSON-object schema."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return []
    properties = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    paths: List[str] = []
    for field in required:
        field_path = f"{prefix}{field}"
        field_schema = properties.get(field, {})
        is_object = isinstance(field_schema, dict) and (
            field_schema.get("type") == "object" or "properties" in field_schema
        )
        if is_object:
            nested = _extract_required_schema_paths(field_schema, prefix=f"{field_path}.")
            if nested:
                paths.extend(nested)
            else:
                paths.append(field_path)
        else:
            paths.append(field_path)
    return paths


def _get_binding_node(params: Dict[str, Any], path: str) -> Any:
    current: Any = params
    for token in path.split("."):
        if not isinstance(current, dict) or token not in current:
            return None
        current = current[token]
    return current


def _resolve_required_binding_source(params: Dict[str, Any], required_path: str) -> Optional[str]:
    """Resolve where a required step input comes from.

    Returns normalized source markers:
    - `input.<path>`
    - `context.<path>`
    - `step.<...>` (runtime-produced)
    - `literal`
    - `None` when no binding is declared
    """
    node = _get_binding_node(params, required_path)
    if isinstance(node, dict) and isinstance(node.get("from"), str):
        return str(node["from"])
    if isinstance(node, dict) and "literal" in node:
        return "literal"

    parts = required_path.split(".")
    for idx in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:idx])
        suffix = ".".join(parts[idx:])
        parent = _get_binding_node(params, prefix)
        if not isinstance(parent, dict):
            continue
        if isinstance(parent.get("from"), str):
            source = str(parent["from"])
            if suffix:
                return f"{source}.{suffix}"
            return source
        if "literal" in parent:
            return "literal"
    return None


def _build_ancestor_map(steps: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    deps_by_step: Dict[str, List[str]] = {
        str(step.get("id")): list(step.get("depends_on", []) or [])
        for step in steps
        if step.get("id")
    }
    memo: Dict[str, Set[str]] = {}

    def ancestors(step_id: str) -> Set[str]:
        if step_id in memo:
            return memo[step_id]
        result: Set[str] = set()
        for dep in deps_by_step.get(step_id, []):
            if dep in result:
                continue
            result.add(dep)
            result.update(ancestors(dep))
        memo[step_id] = result
        return result

    for step_id in deps_by_step:
        ancestors(step_id)
    return memo


def _is_context_source_from_ancestors(
    context_source: str,
    step_id: str,
    steps_by_id: Dict[str, Dict[str, Any]],
    ancestors_by_step: Dict[str, Set[str]],
) -> bool:
    if not context_source:
        return False
    upstream_ids = ancestors_by_step.get(step_id, set())
    if not upstream_ids:
        return False

    for upstream_id in upstream_ids:
        upstream = steps_by_id.get(upstream_id)
        if not upstream:
            continue
        for output in upstream.get("outputs", []) or []:
            if not isinstance(output, dict):
                continue
            target = str(output.get("to_context") or "").strip()
            if not target:
                continue
            if context_source == target or context_source.startswith(f"{target}."):
                return True
    return False


def _derive_required_inputs_from_step_schemas(
    definition: WorkflowDefinition,
    capabilities_by_skill: Dict[str, AgentCapability],
) -> List[str]:
    """Infer required workflow inputs by inspecting each step's required skill params."""
    steps = [step.model_dump() for step in definition.steps]
    steps_by_id = {str(step.get("id")): step for step in steps if step.get("id")}
    ancestors_by_step = _build_ancestor_map(steps)
    required_inputs: Set[str] = set()

    for step in definition.steps:
        step_id = step.id
        cap = capabilities_by_skill.get(step.skill_id)
        if not cap or not isinstance(cap.input_schema, dict):
            continue

        required_paths = _extract_required_schema_paths(cap.input_schema)
        params_spec = step.params or {}
        for required_path in required_paths:
            source = _resolve_required_binding_source(params_spec, required_path)
            if not source:
                continue
            if source == "literal":
                continue
            if source.startswith("step."):
                continue
            if source.startswith("input."):
                path = source[len("input.") :].strip()
                if path:
                    required_inputs.add(path)
                continue
            if source.startswith("context."):
                context_path = source[len("context.") :].strip()
                if not context_path:
                    continue
                if _is_context_source_from_ancestors(
                    context_source=context_path,
                    step_id=step_id,
                    steps_by_id=steps_by_id,
                    ancestors_by_step=ancestors_by_step,
                ):
                    continue
                required_inputs.add(f"context.{context_path}")

    return sorted(required_inputs)


def _validate_dependencies(step_ids: List[str], steps: List[Dict[str, Any]]) -> None:
    id_set = set(step_ids)
    for step in steps:
        for dep in step.get("depends_on", []) or []:
            if dep not in id_set:
                raise WorkflowCompileError(f"Unknown depends_on reference '{dep}' in step '{step.get('id')}'")


def _detect_cycles(step_ids: List[str], steps: List[Dict[str, Any]]) -> None:
    graph: Dict[str, List[str]] = {}
    for step in steps:
        graph[step["id"]] = list(step.get("depends_on", []) or [])

    visiting: Set[str] = set()
    visited: Set[str] = set()

    def dfs(node: str) -> None:
        if node in visiting:
            raise WorkflowCompileError(f"Dependency cycle detected at step '{node}'")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            dfs(dep)
        visiting.remove(node)
        visited.add(node)

    for node in step_ids:
        dfs(node)


def compile_workflow(
    raw: Dict[str, Any],
    source_path: Path,
    capabilities_by_skill: Optional[Dict[str, AgentCapability]] = None,
    strict: bool = True,
) -> CompiledWorkflow:
    """Compile a workflow YAML mapping into a validated `CompiledWorkflow`."""
    definition = WorkflowDefinition.model_validate(raw)

    if not definition.steps:
        raise WorkflowCompileError(f"Workflow '{definition.id}' has no steps")

    step_ids = [step.id for step in definition.steps]
    if len(step_ids) != len(set(step_ids)):
        raise WorkflowCompileError(f"Workflow '{definition.id}' has duplicate step IDs")

    steps_raw = [step.model_dump() for step in definition.steps]
    _validate_dependencies(step_ids, steps_raw)
    _detect_cycles(step_ids, steps_raw)

    compiled_patterns: List[CompiledPattern] = []
    for pattern in definition.matching.patterns:
        compiled_patterns.append(_compile_pattern(pattern))

    required_input_paths = list(definition.inputs.required or [])
    warnings: List[str] = []

    refs: List[Tuple[str, bool]] = []
    for step in definition.steps:
        _extract_input_binding_refs(step.params, refs)
    optional_inputs = set(definition.inputs.optional or [])
    for path, is_optional in refs:
        if not path:
            continue
        if is_optional or path in optional_inputs:
            continue
        if path not in required_input_paths:
            required_input_paths.append(path)

    if capabilities_by_skill is not None:
        inferred_required = _derive_required_inputs_from_step_schemas(definition, capabilities_by_skill)
        for path in inferred_required:
            if path not in required_input_paths:
                required_input_paths.append(path)

        for step in definition.steps:
            if step.skill_id not in capabilities_by_skill:
                message = (
                    f"Workflow '{definition.id}' step '{step.id}' references unknown skill "
                    f"'{step.skill_id}'"
                )
                if strict:
                    raise WorkflowCompileError(message)
                warnings.append(message)

    return CompiledWorkflow(
        definition=definition,
        source_path=source_path,
        compiled_patterns=compiled_patterns,
        required_input_paths=sorted(set(required_input_paths)),
        step_ids=step_ids,
        warnings=warnings,
    )


StepInvokeFn = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]

# A2A identifiers that let a resumed step continue the specialist task it paused.
_A2A_RESUME_KEYS = ("_a2a_context_id", "_a2a_task_id", "_task_graph_root_id", "_task_graph_node_id")


def _should_skip_by_when(step: WorkflowStep, context: Dict[str, Any]) -> bool:
    when = step.when or {}
    not_in_context = when.get("not_in_context")
    if isinstance(not_in_context, str):
        return get_path(context, not_in_context) is not None
    return False


def _apply_step_outputs(
    step: WorkflowStep,
    result: Any,
    context: Dict[str, Any],
    context_delta: Dict[str, Any],
) -> None:
    for output in step.outputs or []:
        if not isinstance(output, dict):
            continue
        to_context = output.get("to_context")
        from_path = output.get("from")
        if not to_context:
            continue
        if from_path:
            value = get_path(result, str(from_path))
            if value is None and str(from_path) == "result":
                value = result
        else:
            value = result
        if value is None:
            continue
        set_path(context, str(to_context), value)
        set_path(context_delta, str(to_context), value)


def _resolve_final_output(workflow: CompiledWorkflow, step_results: Dict[str, Any]) -> Any:
    final_ref = (workflow.definition.outputs.final or {}).get("from")
    if isinstance(final_ref, str) and final_ref:
        source = {"step": step_results}
        if final_ref.startswith("step."):
            return get_path(source, final_ref)
        return get_path(step_results, final_ref)

    for step in workflow.definition.steps:
        if step.is_final and step.id in step_results:
            return step_results[step.id].get("result")
    if workflow.definition.steps:
        last_id = workflow.definition.steps[-1].id
        if last_id in step_results:
            return step_results[last_id].get("result")
    return None


def _merge_envelopes(node_input: Dict[str, Any], joined: bool) -> Dict[str, Any]:
    """Merge the run envelopes that reach a node into one.

    A node behind a `JoinNode` receives `{predecessor_name: envelope}`; any other
    node receives one envelope, or the workflow input from START, which has no
    `steps` yet.
    """
    envelopes = list(node_input.values()) if joined else [node_input or {}]
    merged = {key: value for key, value in envelopes[0].items() if key != "steps"}
    merged["steps"] = {}
    for envelope in envelopes:
        merged["steps"].update(envelope.get("steps") or {})
    return merged


def _current_context(workflow: CompiledWorkflow, envelope: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return the run context with every succeeded step's outputs applied, and those outputs alone."""
    context = copy.deepcopy(envelope.get("context") or {})
    context_delta: Dict[str, Any] = {}
    for step in workflow.definition.steps:
        entry = envelope["steps"].get(step.id)
        if entry and entry.get("status") == "succeeded":
            _apply_step_outputs(step, entry.get("result"), context, context_delta)
    return context, context_delta


async def _invoke_step(
    ctx: Context,
    step: WorkflowStep,
    envelope: Dict[str, Any],
    context: Dict[str, Any],
    invoke_skill: StepInvokeFn,
    on_error: str,
) -> Union[Dict[str, Any], RequestInput]:
    pending_key = f"workflow_library:{ctx.node_path}"
    interrupt_id = f"wf_input:{ctx.node_path}"
    payload = resolve_step_params(
        params_spec=step.params,
        input_params=envelope.get("input") or {},
        context=context,
        step_results=envelope["steps"],
    )
    # What the template bound for this step, without the conversation-wide additions.
    params = {
        key: value
        for key, value in payload.items()
        if not key.startswith("_") and key not in {"artifacts", "conversation_id"}
    }
    if "artifacts" not in payload and isinstance(context.get("artifacts"), list):
        payload["artifacts"] = context["artifacts"]
    conversation_id = str(envelope.get("conversation_id") or "")
    payload["conversation_id"] = conversation_id

    # A rerun after an answer continues the specialist task that asked for input.
    pending = ctx.state.get(pending_key)
    answers = ctx.resume_inputs.get(interrupt_id)
    if pending is not None and answers is not None:
        payload = {**payload, "provided_inputs": answers, **pending}

    try:
        invoked = await invoke_skill(step.skill_id, payload, conversation_id)
    except Exception as exc:
        if on_error == "fail_fast":
            raise
        invoked = {"error": str(exc)}

    if "input_required" in invoked:
        ctx.state[pending_key] = {key: invoked[key] for key in _A2A_RESUME_KEYS if invoked.get(key)}
        return RequestInput(
            interrupt_id=interrupt_id,
            payload={
                "step_id": step.id,
                "skill_id": step.skill_id,
                "params": params,
                "input_required": invoked.get("input_required"),
            },
        )
    if pending is not None:
        ctx.state[pending_key] = None
    if "error" in invoked:
        if on_error == "fail_fast":
            raise WorkflowStepError(f"Workflow step '{step.id}' failed: {invoked['error']}")
        return {"status": "failed", "params": params, "error": str(invoked["error"])}
    return {"status": "succeeded", "params": params, "result": invoked.get("result")}


class WorkflowStepError(RuntimeError):
    """Raised by a failed step under `fail_fast`, so ADK stops the workflow run."""


def _step_node(
    workflow: CompiledWorkflow,
    step: WorkflowStep,
    invoke_skill: StepInvokeFn,
    joined: bool,
) -> FunctionNode:
    on_error = workflow.definition.execution.on_error

    async def run_step(ctx: Context, node_input: Dict[str, Any]) -> Union[Dict[str, Any], RequestInput]:
        envelope = _merge_envelopes(node_input, joined)
        steps = envelope["steps"]
        context, _ = _current_context(workflow, envelope)
        if any((steps.get(dep) or {}).get("status") != "succeeded" for dep in step.depends_on):
            outcome: Dict[str, Any] = {"status": "blocked"}
        elif _should_skip_by_when(step, context):
            outcome = {"status": "skipped"}
        else:
            invoked = await _invoke_step(ctx, step, envelope, context, invoke_skill, on_error)
            if isinstance(invoked, RequestInput):
                return invoked
            outcome = invoked
        steps[step.id] = {"skill_id": step.skill_id, **outcome}
        return envelope

    return FunctionNode(func=run_step, name=f"step_{workflow_slug(step.id)}", rerun_on_resume=True)


def _finish_node(workflow: CompiledWorkflow, joined: bool) -> FunctionNode:
    definition = workflow.definition

    async def finish(node_input: Dict[str, Any]) -> Dict[str, Any]:
        envelope = _merge_envelopes(node_input, joined)
        steps = envelope["steps"]
        _, context_delta = _current_context(workflow, envelope)
        results = {step_id: entry for step_id, entry in steps.items() if entry.get("status") == "succeeded"}
        errors = [
            {"step_id": step_id, "skill_id": entry.get("skill_id"), "error": entry.get("error") or "unknown error"}
            for step_id, entry in steps.items()
            if entry.get("status") == "failed"
        ]
        return {
            "workflow_id": definition.id,
            "workflow_version": definition.version,
            "step_statuses": {step.id: (steps.get(step.id) or {}).get("status") for step in definition.steps},
            "step_results": results,
            "errors": errors,
            "final_output": _resolve_final_output(workflow, results),
            "context_delta": context_delta,
            "success": not errors,
        }

    return FunctionNode(func=finish, name="finish")


def _connect(target: Any, sources: List[Any], join_name: str) -> List[Edge]:
    """Edges into `target`: from START, from its one source, or through a `JoinNode` that waits for all."""
    if not sources:
        return [Edge(from_node=START, to_node=target)]
    if len(sources) == 1:
        return [Edge(from_node=sources[0], to_node=target)]
    join = JoinNode(name=join_name)
    return [Edge(from_node=source, to_node=join) for source in sources] + [Edge(from_node=join, to_node=target)]


def _dependency_order(steps: List[WorkflowStep]) -> List[WorkflowStep]:
    """Template order, moved only as far as each step's dependencies require."""
    ordered: List[WorkflowStep] = []
    placed: Set[str] = set()
    remaining = list(steps)
    while remaining:
        step = next(item for item in remaining if set(item.depends_on) <= placed)
        ordered.append(step)
        placed.add(step.id)
        remaining.remove(step)
    return ordered


def to_adk_workflow(compiled: CompiledWorkflow, invoke_skill: StepInvokeFn) -> Workflow:
    """Build the ADK graph `Workflow` that runs a compiled template.

    Each step is one `FunctionNode` that awaits `invoke_skill(skill_id, payload,
    conversation_id)` with its `binding.py` inputs; each dependency is one edge,
    root steps start from START, and a step with several predecessors waits
    behind a `JoinNode`. `sequential` also chains the steps in template order;
    `dag` and `parallel` run ready steps up to `max_concurrency` at once. Under
    `fail_fast` a failed step stops the run; under `continue_with_partial` its
    dependents are `blocked` and the other steps go on. A step that needs input
    interrupts with a `RequestInput` and reruns with the answer.

    Run it with the node input `{"input": ..., "context": ..., "conversation_id": ...}`.
    Its output, from the `finish` node, carries `step_statuses`, `step_results`,
    `errors`, `final_output`, `context_delta` and `success`.
    """
    definition = compiled.definition
    execution = definition.execution
    sequential = execution.mode == "sequential"
    steps = _dependency_order(list(definition.steps)) if sequential else list(definition.steps)

    predecessors: Dict[str, List[str]] = {}
    for index, step in enumerate(steps):
        preds = list(step.depends_on)
        if sequential and index > 0 and steps[index - 1].id not in preds:
            preds.append(steps[index - 1].id)
        predecessors[step.id] = preds

    nodes = {
        step.id: _step_node(compiled, step, invoke_skill, joined=len(predecessors[step.id]) > 1) for step in steps
    }
    edges: List[Edge] = []
    for step in steps:
        node = nodes[step.id]
        edges.extend(_connect(node, [nodes[pred] for pred in predecessors[step.id]], f"join_{node.name}"))

    upstream = {pred for preds in predecessors.values() for pred in preds}
    leaves = [nodes[step.id] for step in steps if step.id not in upstream]
    edges.extend(_connect(_finish_node(compiled, joined=len(leaves) > 1), leaves, "join_finish"))

    return Workflow(
        name=workflow_tool_name(definition.id),
        description=definition.description,
        edges=edges,
        max_concurrency=1 if sequential else max(1, int(execution.max_concurrency or 1)),
    )
