"""
Client Agent - Orchestrates nuclear analysis workflows.

The implementation lives under ``orchestrator/``.  This module stays as the
stable executable/import surface for Docker, tests, and external callers that
import ``agent`` directly.
"""
import sys
from typing import Any, Dict, Optional

# Add shared module to path for the container layout.
sys.path.insert(0, "/app")

from prometheus_api.agent import ArtifactReference, EventQueue, PrometheusAgent, RequestContext

from artifact_handling import (
    merge_artifact_catalogs,
    merge_artifacts_into_context,
    resolve_artifact_inputs,
    summarize_artifacts_for_context,
)
from capability_cache import get_capability_cache
from conversation_store import get_conversation, store_conversation
from orchestrator import chat_flow as _chat_flow
from orchestrator import debug_commands as _debug_commands
from orchestrator import execution as _execution
from orchestrator import parameters as _parameters
from orchestrator import planning_flow as _planning_flow
from orchestrator import runtime as _runtime
from orchestrator import service as _service
from orchestrator import skills as _skills
from orchestrator import utils as _utils
from orchestrator.models import AgentState, ConversationRequest, ConversationResponse
from param_schema import (
    extract_required_param_paths,
    flatten_schema_properties,
    get_nested_value,
    has_param_path,
    is_user_input_schema,
    normalize_params_for_input_schema,
    set_nested_value,
)
from planner import PlanningResult, WorkflowPlanningCandidate, compile_plan_with_tools
from tool_discovery import discover_agents, get_all_tools_dynamic
from workflow_library import execute_workflow, get_workflow_registry, match_workflows

AGENT_PORT = _runtime.AGENT_PORT
MODEL_NAME = _runtime.MODEL_NAME
DISCOVERY_REFRESH_SECONDS = _runtime.DISCOVERY_REFRESH_SECONDS
ENABLE_WORKFLOW_LIBRARY = _runtime.ENABLE_WORKFLOW_LIBRARY
_tools_cache = _runtime._tools_cache
_refresh_task = _runtime._refresh_task
_refresh_lock = _runtime._refresh_lock
_status_redis_client = _runtime._status_redis_client

create_llm = _runtime.create_llm
_get_status_redis_client = _runtime._get_status_redis_client
store_status_update = _runtime.store_status_update
initialize_tools = _runtime.initialize_tools
get_refresh_lock = _runtime.get_refresh_lock
refresh_dynamic_components = _runtime.refresh_dynamic_components
discovery_refresh_loop = _runtime.discovery_refresh_loop
create_tools = _runtime.create_tools
refresh_discovery = _runtime.refresh_discovery
get_status = _runtime.get_status

extract_json_from_text = _utils.extract_json_from_text
extract_material_ids_from_text = _utils.extract_material_ids_from_text
enrich_material_params = _utils.enrich_material_params
extract_result_text = _utils.extract_result_text
normalize_suggested_queries = _utils.normalize_suggested_queries
collect_suggested_queries = _utils.collect_suggested_queries
build_comparison_summary = _utils.build_comparison_summary
normalize_by_mode = _utils.normalize_by_mode
get_value_by_path = _utils.get_value_by_path
set_param_path = _utils.set_param_path
rule_matches_query = _utils.rule_matches_query

get_selected_skills = _parameters.get_selected_skills
resolve_user_required_params = _parameters.resolve_user_required_params
order_skills_for_workflow = _parameters.order_skills_for_workflow
_humanize_param_path = _parameters._humanize_param_path
build_plan_param_metadata = _parameters.build_plan_param_metadata
merge_context_map = _parameters.merge_context_map
extract_provided_context_maps = _parameters.extract_provided_context_maps
collect_context_maps_from_history = _parameters.collect_context_maps_from_history
attach_artifact_context = _parameters.attach_artifact_context
derive_params_from_rules = _parameters.derive_params_from_rules
resolve_params_via_capability_metadata = _parameters.resolve_params_via_capability_metadata

_unique_workflow_skills = _planning_flow._unique_workflow_skills

_parse_slash_command = _debug_commands._parse_slash_command
_is_slash_command_query = _debug_commands._is_slash_command_query
_format_debug_skill = _debug_commands._format_debug_skill
_collect_registered_agent_debug_entries = _debug_commands._collect_registered_agent_debug_entries
_format_agents_debug_response = _debug_commands._format_agents_debug_response
_collect_conversation_artifacts_for_debug = _debug_commands._collect_conversation_artifacts_for_debug
_format_artifact_size = _debug_commands._format_artifact_size
_format_artifacts_debug_response = _debug_commands._format_artifacts_debug_response
_maybe_handle_slash_command = _debug_commands._maybe_handle_slash_command

_format_plan_for_response = _execution._format_plan_for_response
_latest_conversation_entry = _execution._latest_conversation_entry
_coerce_followup_value = _execution._coerce_followup_value
_lookup_context_value = _execution._lookup_context_value
resolve_missing_inputs_from_state = _execution.resolve_missing_inputs_from_state
_questions_from_pending_subagent_requests = _execution._questions_from_pending_subagent_requests
resume_pending_subagent_requests = _execution.resume_pending_subagent_requests

_needs_info_response = _chat_flow._needs_info_response
_completed_response = _chat_flow._completed_response
_error_response = _chat_flow._error_response

_ORIGINALS: Dict[str, Any] = {
    "find_tool_for_skill": _skills.find_tool_for_skill,
    "invoke_skill": _skills.invoke_skill,
    "compile_query_plan": _planning_flow.compile_query_plan,
    "extract_refinement_param_updates": _planning_flow.extract_refinement_param_updates,
    "plan_analysis": _planning_flow.plan_analysis,
    "show_plan": _planning_flow.show_plan,
    "invoke_agent_generic": _execution.invoke_agent_generic,
    "ask_followup_dynamic": _execution.ask_followup_dynamic,
    "extract_followup_answers_from_query": _execution.extract_followup_answers_from_query,
    "apply_followup_answers_to_state": _execution.apply_followup_answers_to_state,
    "execute_current_plan": _execution.execute_current_plan,
    "execute_approved_plan": _execution.execute_approved_plan,
    "chat": _chat_flow.chat,
}
_DEFAULT_WRAPPERS: Dict[str, Any] = {}


def _exported(name: str) -> Any:
    value = globals().get(name)
    wrapper = _DEFAULT_WRAPPERS.get(name)
    if wrapper is not None and value is wrapper:
        return _ORIGINALS[name]
    return value


def _sync_runtime_exports() -> None:
    globals()["AGENT_PORT"] = _runtime.AGENT_PORT
    globals()["MODEL_NAME"] = _runtime.MODEL_NAME
    globals()["DISCOVERY_REFRESH_SECONDS"] = _runtime.DISCOVERY_REFRESH_SECONDS
    globals()["ENABLE_WORKFLOW_LIBRARY"] = _runtime.ENABLE_WORKFLOW_LIBRARY
    globals()["_tools_cache"] = _runtime._tools_cache
    globals()["_refresh_task"] = _runtime._refresh_task
    globals()["_refresh_lock"] = _runtime._refresh_lock
    globals()["_status_redis_client"] = _runtime._status_redis_client


def _sync_compat() -> None:
    """Propagate compatibility-module monkeypatches into split modules."""
    _runtime.AGENT_PORT = globals().get("AGENT_PORT", _runtime.AGENT_PORT)
    _runtime.MODEL_NAME = globals().get("MODEL_NAME", _runtime.MODEL_NAME)
    _runtime.DISCOVERY_REFRESH_SECONDS = globals().get(
        "DISCOVERY_REFRESH_SECONDS", _runtime.DISCOVERY_REFRESH_SECONDS
    )
    _runtime.ENABLE_WORKFLOW_LIBRARY = globals().get(
        "ENABLE_WORKFLOW_LIBRARY", _runtime.ENABLE_WORKFLOW_LIBRARY
    )

    _runtime.create_llm = globals().get("create_llm", _runtime.create_llm)
    _runtime.create_tools = globals().get("create_tools", _runtime.create_tools)
    _runtime.get_capability_cache = globals().get("get_capability_cache", _runtime.get_capability_cache)
    _runtime.get_all_tools_dynamic = globals().get("get_all_tools_dynamic", _runtime.get_all_tools_dynamic)
    _runtime.get_workflow_registry = globals().get("get_workflow_registry", _runtime.get_workflow_registry)
    _runtime.store_status_update = globals().get("store_status_update", _runtime.store_status_update)
    _runtime.refresh_dynamic_components = globals().get(
        "refresh_dynamic_components", _runtime.refresh_dynamic_components
    )

    for module in (_parameters, _planning_flow, _execution, _debug_commands, _chat_flow, _service):
        if hasattr(module, "get_capability_cache"):
            module.get_capability_cache = globals().get("get_capability_cache", module.get_capability_cache)
        if hasattr(module, "get_workflow_registry"):
            module.get_workflow_registry = globals().get("get_workflow_registry", module.get_workflow_registry)
        if hasattr(module, "execute_workflow"):
            module.execute_workflow = globals().get("execute_workflow", module.execute_workflow)
        if hasattr(module, "discover_agents"):
            module.discover_agents = globals().get("discover_agents", module.discover_agents)
        if hasattr(module, "get_conversation"):
            module.get_conversation = globals().get("get_conversation", module.get_conversation)
        if hasattr(module, "store_conversation"):
            module.store_conversation = globals().get("store_conversation", module.store_conversation)
        if hasattr(module, "compile_plan_with_tools"):
            module.compile_plan_with_tools = globals().get(
                "compile_plan_with_tools", module.compile_plan_with_tools
            )
        if hasattr(module, "match_workflows"):
            module.match_workflows = globals().get("match_workflows", module.match_workflows)

    _skills.find_tool_for_skill = _exported("find_tool_for_skill")
    _skills.invoke_skill = _exported("invoke_skill")
    _skills.get_capability_cache = globals().get("get_capability_cache", _skills.get_capability_cache)

    _parameters.get_capability_cache = globals().get("get_capability_cache", _parameters.get_capability_cache)
    _parameters.get_workflow_registry = globals().get("get_workflow_registry", _parameters.get_workflow_registry)

    _planning_flow.compile_query_plan = _exported("compile_query_plan")
    _planning_flow.extract_refinement_param_updates = _exported("extract_refinement_param_updates")
    _planning_flow.plan_analysis = _exported("plan_analysis")
    _planning_flow.show_plan = _exported("show_plan")

    _execution.invoke_skill = _exported("invoke_skill")
    _execution.invoke_agent_generic = _exported("invoke_agent_generic")
    _execution.ask_followup_dynamic = _exported("ask_followup_dynamic")
    _execution.extract_followup_answers_from_query = _exported("extract_followup_answers_from_query")
    _execution.apply_followup_answers_to_state = _exported("apply_followup_answers_to_state")
    _execution.execute_current_plan = _exported("execute_current_plan")
    _execution.execute_approved_plan = _exported("execute_approved_plan")

    _chat_flow.compile_query_plan = _exported("compile_query_plan")
    _chat_flow.extract_refinement_param_updates = _exported("extract_refinement_param_updates")
    _chat_flow.plan_analysis = _exported("plan_analysis")
    _chat_flow.show_plan = _exported("show_plan")
    _chat_flow.execute_current_plan = _exported("execute_current_plan")
    _chat_flow.execute_approved_plan = _exported("execute_approved_plan")
    _chat_flow.ask_followup_dynamic = _exported("ask_followup_dynamic")
    _chat_flow.apply_followup_answers_to_state = _exported("apply_followup_answers_to_state")
    _chat_flow.extract_followup_answers_from_query = _exported("extract_followup_answers_from_query")

    _service.ArtifactReference = globals().get("ArtifactReference", _service.ArtifactReference)
    _service.chat = _exported("chat")


async def find_tool_for_skill(skill_id: str, refresh_on_miss: bool = True):
    _sync_compat()
    result = await _skills.find_tool_for_skill(skill_id, refresh_on_miss=refresh_on_miss)
    _sync_runtime_exports()
    return result


async def invoke_skill(
    skill_id: str,
    params: Dict[str, Any],
    conversation_id: str,
    emit_status: bool = True,
) -> Dict[str, Any]:
    _sync_compat()
    result = await _skills.invoke_skill(skill_id, params, conversation_id, emit_status=emit_status)
    _sync_runtime_exports()
    return result


async def compile_query_plan(
    state: AgentState,
    explicit_workflow_id: Optional[str] = None,
    explicit_workflow_version: Optional[str] = None,
    selection_source: Optional[str] = None,
    seed_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _sync_compat()
    result = await _planning_flow.compile_query_plan(
        state,
        explicit_workflow_id=explicit_workflow_id,
        explicit_workflow_version=explicit_workflow_version,
        selection_source=selection_source,
        seed_params=seed_params,
    )
    _sync_runtime_exports()
    return result


async def extract_refinement_param_updates(
    query: str,
    routing_decision: Dict[str, Any],
    conversation_history: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    _sync_compat()
    result = await _planning_flow.extract_refinement_param_updates(
        query, routing_decision, conversation_history=conversation_history
    )
    _sync_runtime_exports()
    return result


def plan_analysis(state: AgentState) -> Dict[str, Any]:
    _sync_compat()
    return _planning_flow.plan_analysis(state)


def show_plan(state: AgentState) -> Dict[str, Any]:
    _sync_compat()
    return _planning_flow.show_plan(state)


async def invoke_agent_generic(state: AgentState) -> Dict[str, Any]:
    _sync_compat()
    result = await _execution.invoke_agent_generic(state)
    _sync_runtime_exports()
    return result


async def ask_followup_dynamic(state: AgentState) -> Dict[str, Any]:
    _sync_compat()
    result = await _execution.ask_followup_dynamic(state)
    _sync_runtime_exports()
    return result


async def extract_followup_answers_from_query(state: AgentState, query: str) -> Dict[str, Any]:
    _sync_compat()
    result = await _execution.extract_followup_answers_from_query(state, query)
    _sync_runtime_exports()
    return result


async def apply_followup_answers_to_state(
    state: AgentState,
    followup_answers: Dict[str, Any],
    query: str = "",
) -> AgentState:
    _sync_compat()
    result = await _execution.apply_followup_answers_to_state(state, followup_answers, query=query)
    _sync_runtime_exports()
    return result


async def execute_current_plan(state: AgentState, *, start_message: str) -> AgentState:
    _sync_compat()
    result = await _execution.execute_current_plan(state, start_message=start_message)
    _sync_runtime_exports()
    return result


async def execute_approved_plan(state: AgentState) -> AgentState:
    _sync_compat()
    result = await _execution.execute_approved_plan(state)
    _sync_runtime_exports()
    return result


async def chat(request: ConversationRequest) -> ConversationResponse:
    _sync_compat()
    result = await _chat_flow.chat(request)
    _sync_runtime_exports()
    return result


class OrchestratorAgent(_service.OrchestratorAgent):
    async def _on_startup(self) -> None:
        _sync_compat()
        await super()._on_startup()
        _sync_runtime_exports()

    async def _on_shutdown(self) -> None:
        _sync_compat()
        await super()._on_shutdown()
        _sync_runtime_exports()

    async def _execute(self, params, context, event_queue):
        _sync_compat()
        result = await super()._execute(params, context, event_queue)
        _sync_runtime_exports()
        return result


_DEFAULT_WRAPPERS.update(
    {
        "find_tool_for_skill": find_tool_for_skill,
        "invoke_skill": invoke_skill,
        "compile_query_plan": compile_query_plan,
        "extract_refinement_param_updates": extract_refinement_param_updates,
        "plan_analysis": plan_analysis,
        "show_plan": show_plan,
        "invoke_agent_generic": invoke_agent_generic,
        "ask_followup_dynamic": ask_followup_dynamic,
        "extract_followup_answers_from_query": extract_followup_answers_from_query,
        "apply_followup_answers_to_state": apply_followup_answers_to_state,
        "execute_current_plan": execute_current_plan,
        "execute_approved_plan": execute_approved_plan,
        "chat": chat,
    }
)


if __name__ == "__main__":
    agent = OrchestratorAgent()
    agent.run(port=AGENT_PORT)
