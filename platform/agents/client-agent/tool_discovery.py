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
Dynamic tool discovery from A2A registry.
Creates callable tools by discovering agents and their skills from the registry.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model
from prometheus_api.agent import ArtifactReference, PrometheusAgent
from prometheus_api.a2a_stream import stream_a2a_request

logger = logging.getLogger(__name__)

REGISTRY_URL = PrometheusAgent.registry_url()
AGENT_SECRET = os.getenv("AGENT_SECRET", "")
import socket as _socket

_AGENT_PORT = (os.getenv("AGENT_PORT") or "8000").strip()
SELF_AGENT_URL = (os.getenv("EXTERNAL_AGENT_URL") or f"http://{_socket.gethostname()}:{_AGENT_PORT}").rstrip("/")
# Docker Compose sets the container hostname to the service name; this is the
# agent_name key used when the client-agent registers with the registry.
_SELF_AGENT_ID = _socket.gethostname()
StatusCallback = Callable[[str], Awaitable[None]]
# Invoked once when a downstream agent emits a status tagged metadata.background
# (declare_long_running). Receives the event metadata dict.
BackgroundCallback = Callable[[Dict[str, Any]], Awaitable[None]]
# Invoked with the artifact ids a dispatch returned, so the orchestrator can
# attribute them to the turn that made the call.
ArtifactCallback = Callable[[List[str]], None]
_A2A_V1_TASK_STATES = {
    "TASK_STATE_UNSPECIFIED",
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_AUTH_REQUIRED",
}
_MISSING_INPUT_FIELDS = {
    "name",
    "description",
    "user_prompt",
    "type",
    "options",
    "resolvable_from_context",
    "sensitive",
    "required",
}
_MISSING_INPUT_TYPES = {"string", "number", "integer", "boolean", "enum"}


class A2AContractError(ValueError):
    """Raised when an agent response violates the required A2A v1 contract."""


def _registry_headers() -> Dict[str, str]:
    """Bearer AGENT_SECRET, accepted by the backend's registry and by every agent."""
    headers = {}
    if AGENT_SECRET:
        headers["Authorization"] = f"Bearer {AGENT_SECRET}"
    return headers


def _normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def is_self_agent(agent_id: str, agent_url: str) -> bool:
    """Return True when a discovered agent record points to this orchestrator.

    Primary check: agent_id (the registry routing key) matches the container
    hostname, which Docker Compose sets to the service name. URL comparison is
    a fallback for cases where the hostname-derived URL is available.
    """
    if _SELF_AGENT_ID and (agent_id or "").strip() == _SELF_AGENT_ID:
        return True
    return _normalize_url(agent_url) == _normalize_url(SELF_AGENT_URL)


async def discover_agents() -> List[Dict[str, Any]]:
    """Query the registry for all registered A2A agents.

    Returns a normalised list where each entry contains:
      agent_id   – the agent_name used as registry routing key
      name       – human-readable name from agent_card_params
      url        – downstream agent base URL (from agent_card_params.url)
      agent_name – same as agent_id, kept for clarity
      agent_card_params – full card dict including skills + inputSchema
    """
    async with httpx.AsyncClient(timeout=10.0, headers=_registry_headers()) as client:
        response = await client.get(f"{REGISTRY_URL}/v1/agents")
        response.raise_for_status()
        raw = response.json()

    result = []
    # Accept a bare list or one wrapped in a key
    entries = raw if isinstance(raw, list) else raw.get("data", raw.get("agents", []))
    for entry in entries:
        card = entry.get("agent_card_params") or {}
        agent_name = entry.get("agent_name", "")
        result.append({
            "agent_id": agent_name,
            "agent_name": agent_name,
            "name": card.get("name", agent_name),
            "url": card.get("url", ""),
            "agent_card_params": card,
        })
    return result


async def get_agent_card(agent_id: str, direct_url: Optional[str] = None) -> Dict[str, Any]:
    """Get the full agent card for an agent.

    agent_id is the agent_name (registry routing key). Prefer the specialist's
    direct well-known agent-card endpoint because a gateway's `/a2a/{agent_name}`
    response drops non-standard per-skill metadata such as `inputSchema`.
    Falls back to the registry and finally to the discovery summary payload.
    """
    normalized_direct_url = _normalize_url(direct_url or "")
    if normalized_direct_url:
        for path in ("/api/agent-card", "/.well-known/agent-card.json", "/.well-known/agent.json"):
            try:
                async with httpx.AsyncClient(timeout=10.0, headers=_registry_headers()) as client:
                    response = await client.get(f"{normalized_direct_url}{path}")
                    if response.status_code == 200:
                        return response.json()
            except Exception:
                pass

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_registry_headers()) as client:
            response = await client.get(f"{REGISTRY_URL}/a2a/{agent_id}")
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    # Fallback: find the card in the full agent list
    agents = await discover_agents()
    for agent in agents:
        if agent["agent_id"] == agent_id:
            return agent.get("agent_card_params", {})
    return {}


def create_input_schema_from_skill(skill: Dict) -> type[BaseModel]:
    """
    Create Pydantic model from skill's inputSchema.

    Dynamically generates a Pydantic model class from a JSON schema definition
    in the agent card. This lets the tool validate inputs and provide proper
    type information to the LLM.

    Handles:
    - Simple schemas (single question parameter)
    - Complex schemas (multiple typed parameters)
    - Reserved field name conflicts (schema, model_fields, etc.)
    - Optional vs required parameters
    - Nested objects, arrays, enums

    Args:
        skill: Skill dictionary from agent card with optional "inputSchema" field

    Returns:
        Dynamically created Pydantic model class
    """
    # Reserved Pydantic v2 field names that conflict with BaseModel class attributes.
    # Note: "schema" is NOT reserved in Pydantic v2 (it was only in v1).
    RESERVED_NAMES = {"model_fields", "model_config", "model_computed_fields"}

    # Generic fallback schema when a skill does not define inputSchema.
    # Allow extra kwargs so drop-in skills can still be called.
    class DefaultGenericInput(BaseModel):
        conversation_id: Optional[str] = Field(
            default=None,
            description="Conversation ID for status tracking"
        )
        model_config = ConfigDict(extra="allow")

    # If no inputSchema provided, use default
    if "inputSchema" not in skill:
        return DefaultGenericInput

    input_schema = skill["inputSchema"]
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    # Build field definitions for dynamic model
    fields = {}
    for prop_name, prop_schema in properties.items():
        # Rename reserved field names to avoid Pydantic conflicts
        field_name = prop_name
        if prop_name in RESERVED_NAMES:
            field_name = f"{prop_name}_"

        # Determine field type from JSON schema type
        prop_type = prop_schema.get("type", "string")

        if prop_type == "object":
            field_type = Dict[str, Any]
        elif prop_type == "array":
            field_type = List[Any]
        elif prop_type == "integer":
            field_type = int
        elif prop_type == "number":
            field_type = float
        elif prop_type == "boolean":
            field_type = bool
        else:
            field_type = str

        # Propagate an `enum` constraint into the tool schema as a Literal so the
        # planner LLM is restricted to valid values. Without this the field
        # degrades to a bare type and the planner can invent a plausible-but-
        # invalid value (e.g. mode="forward_sampling" when the only allowed value
        # is "toy_polynomial"), which the specialist then rejects.
        enum_values = prop_schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            try:
                field_type = Literal[tuple(enum_values)]  # type: ignore[valid-type]
            except TypeError:
                # Unhashable enum members (rare): leave the base type in place.
                pass

        # Build field metadata once. For optional fields we must provide the default
        # directly to Field(...); mutating FieldInfo.default later does not reliably
        # mark the field optional in dynamic create_model() schemas.
        field_kwargs = {
            "description": prop_schema.get("description", ""),
        }
        if prop_name in RESERVED_NAMES:
            # Preserve original JSON key when serializing/deserializing.
            field_kwargs["alias"] = prop_name

        if prop_name in required:
            fields[field_name] = (field_type, Field(**field_kwargs))
        else:
            default_value = prop_schema.get("default", None)
            fields[field_name] = (
                Optional[field_type],
                Field(default=default_value, **field_kwargs),
            )

    # Always add conversation_id for status tracking (not part of skill schema but needed for A2A)
    if "conversation_id" not in fields:
        fields["conversation_id"] = (
            Optional[str],
            Field(default=None, description="Conversation ID for status tracking")
        )

    # Create dynamic Pydantic model with populate_by_name for alias support
    model_name = f"{skill['id']}_input"

    # Allow extra fields for forward compatibility with evolving skill schemas.
    model = create_model(
        model_name,
        __config__=ConfigDict(populate_by_name=True, extra="allow"),
        **fields,
    )

    return model


def _normalize_a2a_artifacts(
    artifacts: Any,
    *,
    conversation_id: str,
) -> List[Dict[str, Any]]:
    """Normalize native A2A artifact payloads into catalog-entry dicts."""
    normalized: List[Dict[str, Any]] = []
    for artifact in artifacts or []:
        try:
            reference = ArtifactReference.from_any(
                artifact,
                conversation_id=conversation_id,
            )
        except Exception:
            reference = None
        if reference is None:
            continue
        if not reference.name:
            continue
        metadata = dict(reference.metadata or {})
        if metadata.get("kind") == "conversation_message":
            continue
        if reference.name == "conversation_message":
            continue
        normalized.append(reference.to_dict())
    return normalized


def _extract_status_payload(a2a_result: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Extract one structured payload from an exact A2A v1 status message."""
    status = a2a_result.get("status")
    if not isinstance(status, dict):
        raise A2AContractError("Malformed A2A v1 response: task.status must be an object")
    status_message = status.get("message")
    if not isinstance(status_message, dict):
        raise A2AContractError("Malformed A2A v1 response: task.status.message must be an object")
    parts = status_message.get("parts")
    if not isinstance(parts, list) or len(parts) != 1:
        raise A2AContractError(
            "Malformed A2A v1 response: task.status.message.parts must contain one part"
        )
    part = parts[0]
    if not isinstance(part, dict):
        raise A2AContractError("Malformed A2A v1 response: status part must be an object")
    unexpected = set(part) - {"text", "data", "metadata", "filename", "mediaType"}
    if unexpected:
        raise A2AContractError(
            f"Malformed A2A v1 response: unsupported status part fields {sorted(unexpected)}"
        )
    content_fields = [field for field in ("text", "data") if field in part]
    if len(content_fields) != 1:
        raise A2AContractError(
            "Malformed A2A v1 response: status part must contain exactly one text or data field"
        )
    content_field = content_fields[0]
    if content_field == "data":
        payload = part["data"]
        if not isinstance(payload, dict):
            raise A2AContractError("Malformed A2A v1 response: Part.data must be an object")
        return content_field, payload
    text_content = part["text"]
    if not isinstance(text_content, str):
        raise A2AContractError("Malformed A2A v1 response: Part.text must be a string")
    try:
        payload = json.loads(text_content)
    except json.JSONDecodeError as exc:
        raise A2AContractError(
            "Malformed A2A v1 response: final Part.text must contain a JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise A2AContractError(
            "Malformed A2A v1 response: final Part.text must contain a JSON object"
        )
    return content_field, payload


def _validate_input_required_payload(payload: Dict[str, Any]) -> None:
    if set(payload) != {"missing_inputs", "hint"}:
        raise A2AContractError(
            "Malformed A2A v1 INPUT_REQUIRED response: expected missing_inputs and hint"
        )
    hint = payload["hint"]
    if not isinstance(hint, str) or not hint.strip():
        raise A2AContractError(
            "Malformed A2A v1 INPUT_REQUIRED response: hint must be a non-empty string"
        )
    missing_inputs = payload["missing_inputs"]
    if not isinstance(missing_inputs, list) or not missing_inputs:
        raise A2AContractError(
            "Malformed A2A v1 INPUT_REQUIRED response: missing_inputs must be a non-empty list"
        )
    seen_names: set[str] = set()
    for index, item in enumerate(missing_inputs):
        if not isinstance(item, dict) or set(item) != _MISSING_INPUT_FIELDS:
            raise A2AContractError(
                "Malformed A2A v1 INPUT_REQUIRED response: "
                f"missing_inputs[{index}] must contain the canonical descriptor fields"
            )
        for field in ("name", "description", "user_prompt"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise A2AContractError(
                    "Malformed A2A v1 INPUT_REQUIRED response: "
                    f"missing_inputs[{index}].{field} must be a non-empty string"
                )
        name = item["name"]
        if name in seen_names:
            raise A2AContractError(
                f"Malformed A2A v1 INPUT_REQUIRED response: duplicate field {name!r}"
            )
        seen_names.add(name)
        if item["type"] not in _MISSING_INPUT_TYPES:
            raise A2AContractError(
                "Malformed A2A v1 INPUT_REQUIRED response: "
                f"missing_inputs[{index}].type is unsupported"
            )
        options = item["options"]
        if options is not None and (
            not isinstance(options, list)
            or not all(isinstance(option, str) for option in options)
        ):
            raise A2AContractError(
                "Malformed A2A v1 INPUT_REQUIRED response: "
                f"missing_inputs[{index}].options must be null or a string list"
            )
        for field in ("resolvable_from_context", "sensitive", "required"):
            if not isinstance(item[field], bool):
                raise A2AContractError(
                    "Malformed A2A v1 INPUT_REQUIRED response: "
                    f"missing_inputs[{index}].{field} must be boolean"
                )


async def call_a2a_agent(
    agent_url: str,
    skill_id: str,
    *,
    _prefer_streaming: bool = False,
    _status_callback: Optional[StatusCallback] = None,
    _background_callback: Optional[BackgroundCallback] = None,
    _artifact_callback: Optional[ArtifactCallback] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Call an A2A agent using JSON-RPC protocol.

    Implements the Agent-to-Agent (A2A) communication protocol for invoking
    remote agent skills. Uses JSON-RPC with returnImmediately=false for standard sends,
    and switches to the A2A SSE stream endpoint when the downstream agent card
    advertises streaming support.

    The response extraction requires one direct A2A v1 Part.data for
    INPUT_REQUIRED or one direct Part.text for final JSON results. Native A2A
    artifacts from result.artifacts are mapped into catalog entries separately.

    Args:
        agent_url: Base URL of the agent
        skill_id: The skill ID to invoke
        _prefer_streaming: Whether to use streaming mode
        _status_callback: Callback for intermediate status updates
        _artifact_callback: Called with the ids of the A2A artifacts the agent
            returned, before the reply is validated, so an INPUT_REQUIRED or
            malformed reply still reports what the agent registered
        **kwargs: Parameters for the skill

    Returns:
        Agent's response (unwrapped from A2A protocol)
    """
    request_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    logger.debug("[A2A] Calling agent at %s, skill: %s", agent_url, skill_id)

    # Build A2A JSON-RPC message.
    # Propagate the current user's identity token alongside the skillId so that
    # downstream specialist agents can verify who is calling them.
    message_metadata: Dict[str, Any] = {"skillId": skill_id}
    try:
        from prometheus_api.agent.identity import (
            get_current_identity,
            USER_TOKEN_METADATA_KEY,
        )
        identity = get_current_identity()
        if identity and identity.raw_token:
            message_metadata[USER_TOKEN_METADATA_KEY] = identity.raw_token
    except ImportError:
        pass  # prometheus_api not available; identity metadata omitted

    message = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [],
                "metadata": message_metadata,
            },
            "configuration": {
                "returnImmediately": False,
            },
        }
    }

    request_params = {
        key: value
        for key, value in kwargs.items()
        if not key.startswith("_") and key != "provided_inputs"
    }
    if request_params:
        message["params"]["message"]["parts"].append(
            {
                "text": json.dumps(request_params),
            }
        )
    provided_inputs = kwargs.get("provided_inputs")
    if isinstance(provided_inputs, dict) and provided_inputs:
        message["params"]["message"]["parts"].append(
            {
                "data": {
                    "provided_inputs": provided_inputs,
                },
            }
        )
    # Propagate the conversation scope as the A2A contextId so downstream
    # agents see RequestContext.context_id == conversation_id. This is what
    # scopes the ArtifactRegistry and ContextStateStore on the specialist
    # side. The INPUT_REQUIRED resume path overrides it with the contextId
    # echoed by the downstream agent, which is the same value once the
    # initial call carried it.
    a2a_context_id = kwargs.get("_a2a_context_id") or kwargs.get("conversation_id")
    if a2a_context_id:
        message["params"]["message"]["contextId"] = str(a2a_context_id)
    if kwargs.get("_a2a_task_id"):
        message["params"]["message"]["taskId"] = kwargs["_a2a_task_id"]

    # Route through the registry gateway: agent_url is {REGISTRY_URL}/a2a/{agent_name},
    # which forwards with the agent's own registered credentials.
    # A2A v1 uses one JSON-RPC endpoint and selects the operation by method.
    endpoint = agent_url.rstrip("/")
    headers = {"Content-Type": "application/json", "A2A-Version": "1.0", **_registry_headers()}

    # Use longer timeout for research agents that may take minutes
    timeout_seconds = 900.0  # 15 minutes

    try:
        if _prefer_streaming:
            stream_message = dict(message)
            stream_message["method"] = "SendStreamingMessage"
            stream_endpoint = agent_url.rstrip("/")
            logger.debug("[A2A] Using streaming invocation via %s", stream_endpoint)
            a2a_result = await stream_a2a_request(
                stream_endpoint,
                stream_message,
                headers=headers,
                timeout_seconds=timeout_seconds,
                status_callback=_status_callback if callable(_status_callback) else None,
                background_callback=_background_callback if callable(_background_callback) else None,
            )
        else:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(endpoint, json=message, headers=headers)
                logger.debug("[A2A] Response status: %s", response.status_code)
                response.raise_for_status()
                result = response.json()

                if "error" in result:
                    logger.error("[A2A] Agent returned error: %s", result["error"])
                    raise Exception(f"Agent error: {result['error']}")

                logger.debug("[A2A] Got result: %s", str(result)[:500])

                # A2A v1 wraps a blocking response in SendMessageResponse.task.
                result_payload = result.get("result", {})
                if isinstance(result_payload, dict) and isinstance(
                    result_payload.get("task"), dict
                ):
                    a2a_result = result_payload["task"]
                else:
                    a2a_result = result_payload

        logger.debug("[A2A] Full result structure: %s", json.dumps(a2a_result, indent=2, default=str)[:2000])

        normalized_artifacts = _normalize_a2a_artifacts(
            a2a_result.get("artifacts", []),
            conversation_id=str(kwargs.get("conversation_id") or ""),
        )
        if callable(_artifact_callback) and normalized_artifacts:
            try:
                _artifact_callback([str(a["artifact_id"]) for a in normalized_artifacts if a.get("artifact_id")])
            except Exception as exc:  # attribution must never fail a dispatch
                logger.warning("[A2A] Artifact callback failed for %s: %s", skill_id, exc)

        status = a2a_result.get("status", {})
        state = status.get("state") if isinstance(status, dict) else None
        if state not in _A2A_V1_TASK_STATES:
            raise A2AContractError(
                "Malformed A2A v1 response: task.status.state must be an exact "
                "TASK_STATE_* ProtoJSON value"
            )
        content_field, parsed = _extract_status_payload(a2a_result)
        if state == "TASK_STATE_INPUT_REQUIRED":
            if content_field != "data":
                raise A2AContractError(
                    "Malformed A2A v1 INPUT_REQUIRED response: status message must use Part.data"
                )
            _validate_input_required_payload(parsed)
            return {
                "status": "input_required",
                "input_required": parsed,
                "_a2a_context_id": a2a_result.get("contextId"),
                "_a2a_task_id": a2a_result.get("id"),
            }
        if normalized_artifacts and "artifacts" not in parsed:
            parsed = {**parsed, "artifacts": normalized_artifacts}
        return parsed
    except httpx.TimeoutException:
        raise Exception(f"Agent request timed out after {timeout_seconds}s")
    except httpx.HTTPStatusError:
        raise
    except Exception:
        raise


@dataclass(frozen=True)
class StructuredTool:
    """A discovered A2A skill: name, description, Pydantic input schema, coroutine."""

    name: str
    description: str
    args_schema: type[BaseModel]
    coroutine: Callable[..., Awaitable[str]]

    async def ainvoke(self, tool_input: Dict[str, Any]) -> str:
        """Validate ``tool_input`` against ``args_schema`` and call the skill.

        Only keys the caller supplied are forwarded (defaults are not injected),
        and reserved-name fields are dumped under their original JSON alias.
        Raises ``pydantic.ValidationError`` on invalid input.
        """
        validated = self.args_schema.model_validate(tool_input)
        return await self.coroutine(**validated.model_dump(by_alias=True, exclude_unset=True))


async def create_tool_from_skill(
    agent_url: str,
    skill: Dict[str, Any],
    supports_streaming: bool = False,
) -> StructuredTool:
    """
    Create a tool from an agent skill definition.

    Uses skill metadata from agent card:
    - name becomes tool name
    - description becomes tool description
    - inputSchema becomes Pydantic model

    Args:
        agent_url: Base URL of the agent
        skill: Skill dictionary from agent card

    Returns:
        StructuredTool
    """
    skill_id = skill["id"]
    skill_description = skill.get("description", "")

    # Create async function to call the agent
    async def call_agent(**kwargs) -> str:
        try:
            result = await call_a2a_agent(
                agent_url,
                skill_id,
                _prefer_streaming=supports_streaming,
                **kwargs,
            )
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    return StructuredTool(
        name=skill_id,
        description=skill_description,
        args_schema=create_input_schema_from_skill(skill),
        coroutine=call_agent,
    )


async def get_all_tools_dynamic() -> List[StructuredTool]:
    """
    Discover all available agents and create tools dynamically.

    This replaces the hardcoded get_all_tools() function.
    Queries the registry for agents, fetches their agent cards,
    and creates tools from their skills.

    Returns:
        List of StructuredTool
    """
    try:
        agents = await discover_agents()
    except Exception as e:
        logger.warning("Failed to discover agents from registry: %s", e)
        return []

    tools = []

    for agent in agents:
        try:
            agent_id = agent["agent_id"]
            direct_url = agent["url"]   # downstream URL, used only for self-check

            # Never expose this orchestrator's own skills as dynamic tools.
            if is_self_agent(agent_id, direct_url):
                logger.debug("Skipping self agent in tool discovery: %s (%s)", agent_id, direct_url)
                continue

            # Route all calls through the registry gateway rather than directly to the agent.
            agent_url = f"{REGISTRY_URL}/a2a/{agent_id}"

            # A registry's /v1/agents payload can omit full per-skill metadata.
            # Fetch the full card so tool schemas stay authoritative.
            agent_card = await get_agent_card(agent_id, direct_url=direct_url)
            if not agent_card.get("skills"):
                agent_card = agent.get("agent_card_params") or agent_card
            supports_streaming = bool((agent_card.get("capabilities") or {}).get("streaming", False))

            # Create one tool per skill
            for skill in agent_card.get("skills", []):
                tool = await create_tool_from_skill(
                    agent_url,
                    skill,
                    supports_streaming=supports_streaming,
                )
                tools.append(tool)
                logger.debug("Discovered tool: %s from %s", skill["id"], agent_id)
        except Exception as e:
            logger.warning("Failed to create tools for agent %s: %s", agent_id, e)
            continue

    logger.info("Total tools discovered: %d", len(tools))
    return tools
