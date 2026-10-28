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

"""The orchestrator's tool catalog as ADK tools.

Each catalog entry (``agent_loop.build_tool_catalog``) becomes one ADK tool: a
skill dispatches over A2A (``tool_discovery.call_a2a_agent``), a workflow
template runs its compiled ADK ``Workflow`` (``to_adk_workflow``), and
``ask_user`` is a long-running tool that pauses the run for a form. Tools whose
spec requires approval carry ``approval_required = True``, which the SDK
approval plugin turns into an ``adk_request_confirmation`` pause.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, Mapping, Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.sessions.state import State
from google.adk.tools import BaseTool, LongRunningFunctionTool, ToolContext
from google.genai import types

import task_graph
import tool_discovery
from artifact_handling import merge_artifacts_into_context, summarize_artifacts_for_context
from capability_cache import get_capability_cache
from param_schema import normalize_params_for_input_schema
from workflow_library import get_workflow_registry, to_adk_workflow, verify_workflow_source_health
from workflow_library.compiler import CompiledWorkflow, StepInvokeFn

from . import agent_loop, runtime, task_tracking
from .skills import invoke_skill
from .utils import extract_result_text

# Session-state keys the tools read and write (seeded by ``agent_loop.run_turn``).
CONVERSATION_ID_KEY = "conversation_id"
CONTEXT_KEY = "context"

# The confirmation payload key of a specialist's INPUT_REQUIRED pause. The payload holds
# the specialist's request and its A2A task; the answer's payload adds ``provided_inputs``.
SPECIALIST_INPUT_KEY = "input_required"

# The hidden tool that pauses on a specialist's INPUT_REQUIRED raised in a re-run (see
# ``SpecialistInputTool``), and the key of the arguments that re-run the skill call.
SPECIALIST_INPUT_TOOL = "specialist_input"
RESUME_ARGS_KEY = "resume_args"
# Session state: the ``specialist_input`` calls ``pause_on_specialist_input`` made, by call id.
# Only these run; a call the model makes itself is refused.
SPECIALIST_CALLS_KEY = "specialist_input_calls"
# Session state: every skill call's inputs and result in this run, by result key
# (``skill_id``, then ``skill_id#2``...); chat_flow copies them into the turn.
TOOL_INPUTS_KEY = "turn_tool_inputs"
TOOL_RESULTS_KEY = "turn_tool_results"
# Temp state (``temp:`` keys are never stored): the sensitive answers of a form, by field.
SENSITIVE_ANSWERS_KEY = f"{State.TEMP_PREFIX}sensitive_answers"
# Temp state: the system prompt's digest of each skill's newest inputs across the
# conversation (``agent_loop.recent_skill_inputs``), which only the conversation store holds.
RECENT_SKILL_INPUTS_KEY = f"{State.TEMP_PREFIX}recent_skill_inputs"
# Session state: the user's explicit workflow selection, {"workflow_id", "version", "source"}.
WORKFLOW_SELECTION_KEY = "workflow_selection"


def _declaration(spec: agent_loop.ToolSpec) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=spec.name,
        description=spec.description,
        parameters_json_schema=spec.parameters,
    )


def _state_dict(tool_context: ToolContext) -> Dict[str, Any]:
    return tool_context.state.to_dict()


def _record_result(tool_context: ToolContext, skill_id: str, inputs: Dict[str, Any], result: Any) -> None:
    """Record one skill call of this run under a run-unique key, as the turn's tool results."""
    results = dict(tool_context.state.get(TOOL_RESULTS_KEY) or {})
    key = skill_id
    index = 2
    while key in results:
        key = f"{skill_id}#{index}"
        index += 1
    results[key] = result
    tool_inputs = dict(tool_context.state.get(TOOL_INPUTS_KEY) or {})
    tool_inputs[key] = {name: value for name, value in inputs.items() if not name.startswith("_")}
    tool_context.state[TOOL_RESULTS_KEY] = results
    tool_context.state[TOOL_INPUTS_KEY] = tool_inputs


def _merge_artifacts(tool_context: ToolContext, result: Any) -> None:
    artifacts = result.get("artifacts") if isinstance(result, dict) else None
    if artifacts:
        context = tool_context.state.get(CONTEXT_KEY) or {}
        tool_context.state[CONTEXT_KEY] = merge_artifacts_into_context(context, artifacts)


class _SpecTool(BaseTool):
    """A tool declared by a catalog ``ToolSpec``."""

    def __init__(self, spec: agent_loop.ToolSpec) -> None:
        super().__init__(name=spec.name, description=spec.description)
        self.spec = spec
        self.approval_required = spec.requires_approval

    def _get_declaration(self) -> Optional[types.FunctionDeclaration]:
        return _declaration(self.spec)


class A2ASkillTool(_SpecTool):
    """One specialist skill, dispatched with ``call_a2a_agent`` and tracked as a Task Graph node.

    The node is a child of the turn's root (``task_tracking.track_skill``). A specialist's
    INPUT_REQUIRED pause leaves it ``input-required``, and the answer resumes the same node.
    """

    async def run_async(self, *, args: Dict[str, Any], tool_context: ToolContext) -> Any:
        capability = await get_capability_cache().get_capability_by_skill_id(self.spec.target)
        if capability is None:
            return {"status": "failed", "error": f"Capability '{self.spec.target}' is not currently available."}
        params = dict(args)
        artifacts = summarize_artifacts_for_context((tool_context.state.get(CONTEXT_KEY) or {}).get("artifacts"))
        if artifacts:
            params["artifacts"] = artifacts
        conversation_id = str(tool_context.state.get(CONVERSATION_ID_KEY) or "")
        params["conversation_id"] = conversation_id
        params["_artifact_callback"] = task_tracking.record_produced_artifacts
        confirmation = tool_context.tool_confirmation
        resumed = confirmation.payload if confirmation is not None else None
        resume_node: Dict[str, Optional[str]] = {}
        if isinstance(resumed, dict) and SPECIALIST_INPUT_KEY in resumed:
            if not confirmation.confirmed:
                # The user moved on: the paused specialist task does not resume.
                if resumed.get("task_graph_node_id"):
                    task_graph.update_own_state(
                        conversation_id,
                        str(resumed["task_graph_node_id"]),
                        own_state="canceled",
                        message="The user replied instead.",
                    )
                return {"status": "not_executed", "message": "Not executed: the user replied instead."}
            # The answer resumes the specialist's own A2A task and its Task Graph node.
            # Sensitive answers come out of band (temp state); they are never stored.
            sensitive = tool_context.state.get(SENSITIVE_ANSWERS_KEY) or {}
            names = {str(item.get("name") or "") for item in (resumed.get(SPECIALIST_INPUT_KEY) or {}).get("missing_inputs") or []}
            params["provided_inputs"] = {
                **dict(resumed.get("provided_inputs") or {}),
                **{name: value for name, value in sensitive.items() if name in names},
            }
            params["_a2a_task_id"] = resumed.get("a2a_task_id")
            params["_a2a_context_id"] = resumed.get("a2a_context_id")
            if resumed.get("task_graph_node_id") and resumed.get("task_graph_root_id"):
                resume_node = {
                    "resume_node_id": resumed["task_graph_node_id"],
                    "resume_root_id": resumed["task_graph_root_id"],
                }
        node_id: Optional[str] = None
        try:
            async with task_tracking.track_skill(
                conversation_id,
                self.spec.target,
                agent=getattr(capability, "agent_name", None),
                title=self.spec.target,
                **resume_node,
            ) as tracker:
                node_id = tracker.node_id
                if capability.supports_streaming:

                    async def on_status(message: str) -> None:
                        text = str(message or "").strip()
                        if text:
                            tracker.progress(text)
                            runtime.store_status_update(conversation_id, f"[{self.spec.target}] {text}")

                    async def on_background(metadata: Dict[str, Any]) -> None:
                        # The agent declared itself long-running: detach this turn.
                        task_tracking.request_background()
                        runtime.store_status_update(conversation_id, f"[{self.spec.target}] running in the background.")

                    params["_status_callback"] = on_status
                    params["_background_callback"] = on_background
                result = await tool_discovery.call_a2a_agent(
                    capability.agent_url,
                    self.spec.target,
                    _prefer_streaming=capability.supports_streaming,
                    **params,
                )
                if isinstance(result, dict) and result.get("status") == "input_required":
                    tracker.input_required()
                elif isinstance(result, dict) and result.get("error"):
                    tracker.fail(result["error"])
                else:
                    tracker.complete(result_ref=task_tracking._first_artifact_ref(result))
        except asyncio.CancelledError:
            # track_skill finalizes a cancelled dispatch as completed; record the cancel over it.
            if node_id:
                task_graph.update_own_state(conversation_id, node_id, own_state="canceled")
            raise
        if isinstance(result, dict) and result.get("status") == "input_required":
            # Pause the run on the specialist's question; chat_flow shows it as the form.
            input_required = result.get("input_required") or {}
            request = {
                SPECIALIST_INPUT_KEY: input_required,
                "a2a_task_id": result.get("_a2a_task_id"),
                "a2a_context_id": result.get("_a2a_context_id"),
                "task_graph_node_id": node_id or None,
                "task_graph_root_id": (task_tracking.current_root_id() or node_id) if node_id else None,
            }
            if confirmation is not None:
                # A confirmed re-run (an approval, an answered form) cannot pause: ADK
                # re-runs it outside the step that emits a confirmation request. The
                # request goes back as this result, and ``pause_on_specialist_input``
                # raises it as a fresh ``specialist_input`` call.
                return {"status": "input_required", "tool": self.name, "request": request, RESUME_ARGS_KEY: dict(args)}
            tool_context.request_confirmation(hint=str(input_required.get("hint") or ""), payload=request)
            tool_context.actions.skip_summarization = True
            return {"status": "input_required"}
        if isinstance(result, dict) and result.get("error"):
            _record_result(tool_context, self.spec.target, args, {"error": result["error"]})
            return {"status": "failed", "error": str(result["error"])}
        _record_result(tool_context, self.spec.target, args, result)
        _merge_artifacts(tool_context, result)
        return agent_loop._compact_result(result, "succeeded")


class WorkflowTool(_SpecTool):
    """One workflow template, run as its compiled ADK ``Workflow``."""

    def __init__(self, spec: agent_loop.ToolSpec, compiled: CompiledWorkflow, invoke: StepInvokeFn) -> None:
        super().__init__(spec)
        self.compiled = compiled
        self.invoke = invoke
        self.workflow = to_adk_workflow(compiled, invoke)

    async def run_async(self, *, args: Dict[str, Any], tool_context: ToolContext) -> Any:
        compiled, workflow = self.compiled, self.workflow
        selection = tool_context.state.get(WORKFLOW_SELECTION_KEY) or {}
        version = selection.get("version") if selection.get("workflow_id") == compiled.definition.id else None
        if version and version != compiled.version:
            # The user picked an explicit version of this template (catalog start).
            selected = get_workflow_registry().get(compiled.definition.id, version=version)
            if selected is None:
                return {"status": "failed", "error": f"Workflow '{compiled.definition.id}' version {version} is unavailable."}
            compiled, workflow = selected, to_adk_workflow(selected, self.invoke)
        health_error = await verify_workflow_source_health(compiled)
        if health_error:
            return {"status": "failed", "error": health_error}
        context = dict(tool_context.state.get(CONTEXT_KEY) or {})
        inputs = normalize_params_for_input_schema(dict(args))
        artifacts = summarize_artifacts_for_context(context.get("artifacts"))
        if artifacts:
            inputs["artifacts"] = artifacts
        function_call_id = tool_context.function_call_id
        output = await tool_context.run_node(
            workflow,
            node_input={
                "input": inputs,
                "context": context,
                "conversation_id": str(tool_context.state.get(CONVERSATION_ID_KEY) or ""),
            },
            run_id=function_call_id,
            override_branch=f"{self.name}@{function_call_id}",
            raise_on_wait=True,
        )
        output = output if isinstance(output, dict) else {}
        for payload in (output.get("step_results") or {}).values():
            if isinstance(payload, dict):
                _merge_artifacts(tool_context, payload.get("result"))
                if payload.get("skill_id") and payload.get("status") == "succeeded":
                    _record_result(
                        tool_context, str(payload["skill_id"]), dict(payload.get("params") or {}), payload.get("result")
                    )
        return {
            "status": "succeeded" if output.get("success") else "failed",
            "step_statuses": output.get("step_statuses") or {},
            "errors": output.get("errors") or [],
            "summary": agent_loop._truncate(extract_result_text(output.get("final_output")), agent_loop.SUMMARY_CHARS),
            "final_output": agent_loop._truncate(
                json.dumps(output.get("final_output"), default=str), agent_loop.RESULT_CHARS
            ),
        }


def ask_user(questions: list, tool_context: ToolContext) -> Dict[str, Any]:
    """Ask the user clarification questions; the answers resume this call."""
    # The form is a pause, not a result to summarize; without this the model is called again.
    tool_context.actions.skip_summarization = True
    return {"status": "pending", "questions": agent_loop._normalize_questions(questions)}


class AskUserTool(LongRunningFunctionTool):
    """``ask_user``: pauses the run until the user answers the form."""

    def __init__(self) -> None:
        super().__init__(ask_user)
        self.spec = agent_loop.ASK_USER_SPEC

    def _get_declaration(self) -> Optional[types.FunctionDeclaration]:
        return _declaration(self.spec)


class SpecialistInputTool(BaseTool):
    """Hidden tool: pause on a specialist's request, then re-run its skill call with the answer.

    Its call comes from ``pause_on_specialist_input``, never from the model, so it is
    registered for dispatch without a declaration.
    """

    def __init__(self, skills: Mapping[str, A2ASkillTool]) -> None:
        super().__init__(name=SPECIALIST_INPUT_TOOL, description="Pause for a specialist's missing inputs.")
        self.skills = skills

    async def process_llm_request(self, *, tool_context: ToolContext, llm_request: LlmRequest) -> None:
        llm_request.tools_dict[self.name] = self

    async def run_async(self, *, args: Dict[str, Any], tool_context: ToolContext) -> Any:
        expected = (tool_context.state.get(SPECIALIST_CALLS_KEY) or {}).get(str(tool_context.function_call_id or ""))
        if expected is None or json.dumps(expected, sort_keys=True, default=str) != json.dumps(
            args, sort_keys=True, default=str
        ):
            # Only the calls pause_on_specialist_input made run; the model may not forge one.
            return {"status": "failed", "error": f"{SPECIALIST_INPUT_TOOL} is not a tool the model may call."}
        request = dict(args.get("request") or {})
        if tool_context.tool_confirmation is None:
            hint = str((request.get(SPECIALIST_INPUT_KEY) or {}).get("hint") or "")
            tool_context.request_confirmation(hint=hint, payload=request)
            tool_context.actions.skip_summarization = True
            return {"status": "input_required"}
        skill = self.skills.get(str(args.get("tool") or ""))
        if skill is None:
            return {"status": "failed", "error": f"Unknown tool '{args.get('tool')}'."}
        # The answer (in tool_confirmation) resumes the specialist's task in the skill call.
        return await skill.run_async(args=dict(args.get(RESUME_ARGS_KEY) or {}), tool_context=tool_context)


def pause_on_specialist_input(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """Answer the model step with a ``specialist_input`` call for each re-run that a specialist paused.

    Each call is recorded under its id in session state; ``SpecialistInputTool`` runs only
    a recorded call with the recorded arguments.
    """
    last = llm_request.contents[-1] if llm_request.contents else None
    recorded = dict(callback_context.state.get(SPECIALIST_CALLS_KEY) or {})
    calls: list[types.Part] = []
    for part in last.parts or [] if last is not None else []:
        response = part.function_response.response if part.function_response else None
        if not (isinstance(response, dict) and response.get("status") == "input_required" and "request" in response):
            continue
        call_id = f"specialist_{uuid.uuid4().hex[:16]}"
        args = {"tool": response["tool"], "request": response["request"], RESUME_ARGS_KEY: response[RESUME_ARGS_KEY]}
        recorded[call_id] = args
        calls.append(types.Part(function_call=types.FunctionCall(id=call_id, name=SPECIALIST_INPUT_TOOL, args=args)))
    if not calls:
        return None
    callback_context.state[SPECIALIST_CALLS_KEY] = recorded
    return LlmResponse(content=types.Content(role="model", parts=calls))


def a2a_skill_tool(spec: agent_loop.ToolSpec) -> BaseTool:
    """The ADK tool of one skill catalog entry."""
    return A2ASkillTool(spec)


def workflow_tool(
    spec: agent_loop.ToolSpec,
    compiled: CompiledWorkflow,
    invoke: StepInvokeFn = invoke_skill,
) -> BaseTool:
    """The ADK tool that runs one compiled workflow template as a single call."""
    return WorkflowTool(spec, compiled, invoke)


def before_tool(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext) -> Optional[Dict[str, Any]]:
    """Normalize and check a skill call's arguments; a problem answers the call instead of a dispatch."""
    spec = getattr(tool, "spec", None)
    if not isinstance(spec, agent_loop.ToolSpec) or spec.kind != "skill":
        return None
    normalized = normalize_params_for_input_schema(dict(args), spec.input_schema)
    args.clear()
    args.update(normalized)
    problem = agent_loop._validation_problem(spec, args, _state_dict(tool_context))
    if problem:
        return {"status": "failed", "error": problem}
    missing = agent_loop._missing_user_inputs(spec, args)
    if missing:
        return {
            "status": "failed",
            "error": f"Missing user input(s) {', '.join(missing)}; ask the user with ask_user, then call again.",
        }
    return None


def build_tools(catalog: Mapping[str, agent_loop.ToolSpec]) -> list[BaseTool]:
    """One ADK tool per catalog entry; a workflow that no longer compiles is left out."""
    tools: list[BaseTool] = []
    for spec in catalog.values():
        if spec.kind == "ask_user":
            tools.append(AskUserTool())
        elif spec.kind == "skill":
            tools.append(a2a_skill_tool(spec))
        else:
            compiled = get_workflow_registry().get(spec.target)
            if compiled is not None:
                tools.append(workflow_tool(spec, compiled))
    skills = {tool.name: tool for tool in tools if isinstance(tool, A2ASkillTool)}
    if skills:
        tools.append(SpecialistInputTool(skills))
    return tools


def build_client_agent(catalog: Mapping[str, agent_loop.ToolSpec], model: BaseLlm) -> LlmAgent:
    """The orchestrator as one ADK ``LlmAgent`` over the tool catalog."""

    def instruction(context: ReadonlyContext) -> str:
        return agent_loop._system_prompt(dict(context.state), catalog)

    return LlmAgent(
        name="client_agent",
        model=model,
        instruction=instruction,
        tools=build_tools(catalog),
        before_tool_callback=before_tool,
        before_model_callback=pause_on_specialist_input,
    )
