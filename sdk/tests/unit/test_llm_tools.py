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

"""Tests for LLM tool-calling helpers (spec 014)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from prometheus_api.llm_client import (
    ChatResponse,
    LLMClientError,
    LLMToolCallError,
    ToolCall,
    ToolDefinition,
    acall_tool,
    assistant_message,
    call_tool,
    normalize_messages,
    parse_finish_reason,
    parse_tool_calls,
    require_tool_calls,
    tool_result_message,
    tool_schemas,
)


def _proxy_raw(
    *,
    content=None,
    tool_calls=None,
    finish_reason="tool_calls",
):
    """Build a mapping-shaped payload the way the LiteLLM proxy returns it."""
    message: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "model": "resolved-medium",
        "choices": [{"message": message, "finish_reason": finish_reason}],
    }


def _proxy_call(call_id="call_1", name="lookup", arguments='{"query": "iron"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


class _ObjectMessage:
    """Stands in for a LiteLLM message object, including its pydantic-style dump."""

    def __init__(self, content, tool_calls):
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=False):
        data = {"role": self.role, "content": self.content, "tool_calls": self.tool_calls}
        if exclude_none:
            data = {key: value for key, value in data.items() if value is not None}
        return data


def _object_raw(*, content=None, tool_calls=None, finish_reason="tool_calls"):
    """Build an attribute-shaped payload the way the LiteLLM SDK returns it."""
    return SimpleNamespace(
        model="resolved-medium",
        choices=[
            SimpleNamespace(
                message=_ObjectMessage(content, tool_calls),
                finish_reason=finish_reason,
            )
        ],
    )


def _object_call(call_id="call_1", name="lookup", arguments='{"query": "iron"}'):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(raw, *, text=""):
    return ChatResponse(
        text=text,
        model_alias="medium",
        provider_model="resolved-medium",
        usage=None,
        raw=raw,
        tool_calls=parse_tool_calls(raw),
        finish_reason=parse_finish_reason(raw),
    )


class _RecordingClient:
    """Minimal stand-in that records the kwargs call_tool sends."""

    def __init__(self, raw):
        self._raw = raw
        self.calls: list[dict] = []

    def chat(self, text_or_messages, **kwargs):
        self.calls.append({"input": text_or_messages, **kwargs})
        return _response(self._raw)


class _AsyncRecordingClient(_RecordingClient):
    async def chat(self, text_or_messages, **kwargs):  # type: ignore[override]
        return super().chat(text_or_messages, **kwargs)


# --------------------------------------------------------------------------- parsing


def test_parse_tool_calls_reads_proxy_dict_shape():
    """REQ-014-02: mapping-shaped proxy payloads yield decoded tool calls."""
    calls = parse_tool_calls(_proxy_raw(tool_calls=[_proxy_call()]))

    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "lookup"
    assert calls[0].arguments == {"query": "iron"}
    assert calls[0].arguments_error is None


def test_parse_tool_calls_reads_litellm_object_shape():
    """REQ-014-02: attribute-shaped LiteLLM payloads yield the same tool calls."""
    calls = parse_tool_calls(_object_raw(tool_calls=[_object_call()]))

    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "lookup"
    assert calls[0].arguments == {"query": "iron"}


def test_parse_tool_calls_accepts_chat_response_or_raw_payload():
    """REQ-014-02: a ChatResponse and its raw payload parse identically."""
    raw = _proxy_raw(tool_calls=[_proxy_call()])

    assert parse_tool_calls(ChatResponse("", "medium", None, None, raw)) == parse_tool_calls(raw)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"role": "assistant", "content": "plain text"}}]},
        {"choices": [{"message": {"role": "assistant", "content": "x", "tool_calls": []}}]},
        SimpleNamespace(choices=[]),
    ],
)
def test_parse_tool_calls_returns_empty_without_tool_calls(raw):
    """REQ-014-02: absent choices, message, or tool calls yield an empty tuple, never a raise."""
    assert parse_tool_calls(raw) == ()


def test_parse_tool_calls_decodes_json_string_and_mapping_arguments():
    """REQ-014-03: arguments may arrive as a JSON string or as an already-decoded mapping."""
    from_string = parse_tool_calls(_proxy_raw(tool_calls=[_proxy_call(arguments='{"a": 1}')]))
    mapping = {"a": 1}
    from_mapping = parse_tool_calls(_proxy_raw(tool_calls=[_proxy_call(arguments=mapping)]))

    assert from_string[0].arguments == {"a": 1}
    assert from_mapping[0].arguments == {"a": 1}
    assert from_mapping[0].arguments is not mapping
    assert from_string[0].arguments_error is None
    assert from_mapping[0].arguments_error is None


def test_parse_tool_calls_records_arguments_error_for_malformed_json():
    """REQ-014-03, BEH-014-02: malformed JSON becomes recorded data, not an exception."""
    calls = parse_tool_calls(_proxy_raw(tool_calls=[_proxy_call(arguments="{not json")]))

    assert calls[0].arguments == {}
    assert calls[0].arguments_error is not None
    assert "not valid JSON" in calls[0].arguments_error


@pytest.mark.parametrize("arguments", ["[1, 2]", "5", '"text"', "null"])
def test_parse_tool_calls_records_arguments_error_for_non_object_json(arguments):
    """REQ-014-03: JSON that is valid but not an object is an error, not a silent empty dict."""
    calls = parse_tool_calls(_proxy_raw(tool_calls=[_proxy_call(arguments=arguments)]))

    assert calls[0].arguments == {}
    assert "JSON object" in (calls[0].arguments_error or "")


def test_parse_tool_calls_treats_absent_arguments_as_empty():
    """REQ-014-03: a no-argument tool call is not an error."""
    for arguments in (None, "", "{}"):
        calls = parse_tool_calls(_proxy_raw(tool_calls=[_proxy_call(arguments=arguments)]))
        assert calls[0].arguments == {}
        assert calls[0].arguments_error is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        (_proxy_raw(tool_calls=[_proxy_call()]), "tool_calls"),
        (_proxy_raw(content="hi", finish_reason="stop"), "stop"),
        (_proxy_raw(content="hi", finish_reason=None), None),
        ({}, None),
        (SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")]), "length"),
    ],
)
def test_parse_finish_reason_reads_both_shapes(raw, expected):
    """REQ-014-04: finish_reason resolves from either shape and defaults to None."""
    assert parse_finish_reason(raw) == expected


# ------------------------------------------------------------------ history replay


def test_assistant_message_preserves_none_content_and_tool_calls():
    """REQ-014-05: no placeholder text is invented for a pure tool-call turn."""
    message = assistant_message(_response(_proxy_raw(tool_calls=[_proxy_call()])))

    assert message["role"] == "assistant"
    assert message["content"] is None
    assert message["tool_calls"] == [_proxy_call()]
    assert "Tool calls requested." not in json.dumps(message, default=str)


def test_assistant_message_preserves_real_content():
    """REQ-014-05: a turn with both text and tool calls keeps its text."""
    raw = _proxy_raw(content="Let me look that up.", tool_calls=[_proxy_call()])

    assert assistant_message(_response(raw))["content"] == "Let me look that up."


def test_assistant_message_normalizes_blank_content_to_none():
    """REQ-014-05: whitespace-only content becomes None rather than an empty string."""
    raw = _proxy_raw(content="   ", tool_calls=[_proxy_call()])

    assert assistant_message(_response(raw))["content"] is None


def test_assistant_message_round_trips_through_normalize_messages():
    """REQ-014-05, REQ-006-15, BEH-014-03: the replayed turn survives input validation."""
    raw = _object_raw(tool_calls=[_object_call()])
    history = [
        {"role": "user", "content": "look up iron"},
        assistant_message(_response(raw)),
        tool_result_message(parse_tool_calls(raw)[0], {"density": 7.87}),
    ]

    normalized = normalize_messages(history)

    assert [message["role"] for message in normalized] == ["user", "assistant", "tool"]
    assert normalized[1]["content"] is None
    assert normalized[1]["tool_calls"]
    assert normalized[2]["tool_call_id"] == "call_1"


def test_assistant_message_raises_without_a_completion_message():
    """REQ-014-05: an empty response cannot produce replayable history."""
    with pytest.raises(LLMToolCallError, match="did not include a completion message"):
        assistant_message(_response({"choices": []}))


def test_tool_result_message_json_encodes_non_string_results():
    """REQ-014-06: non-string results are JSON-encoded with a str fallback."""
    message = tool_result_message(ToolCall("call_9", "lookup", {}), {"density": 7.87})

    assert message == {
        "role": "tool",
        "tool_call_id": "call_9",
        "content": '{"density": 7.87}',
    }
    fallback = tool_result_message("call_9", {"value": SimpleNamespace(a=1)})
    assert fallback["content"] == '{"value": "namespace(a=1)"}'


def test_tool_result_message_accepts_a_call_id_string_and_passes_strings_through():
    """REQ-014-06: a bare call id works and string results are not re-encoded."""
    assert tool_result_message("call_3", "done") == {
        "role": "tool",
        "tool_call_id": "call_3",
        "content": "done",
    }


# ----------------------------------------------------------------- the strict gate


def test_require_tool_calls_returns_calls_when_the_contract_holds():
    """REQ-014-07: a well-formed single call passes the expected-name and count checks."""
    response = _response(_proxy_raw(tool_calls=[_proxy_call()]))

    assert require_tool_calls(response, expected=["lookup"], count=1)[0].name == "lookup"


@pytest.mark.parametrize(
    "response_kwargs, gate_kwargs, message",
    [
        ({"tool_calls": None}, {}, "did not include any tool calls"),
        ({"tool_calls": [_proxy_call(call_id="")]}, {}, "missing an id"),
        ({"tool_calls": [_proxy_call(name="")]}, {}, "missing a function name"),
        ({"tool_calls": [_proxy_call(arguments="{bad")]}, {}, "invalid arguments"),
        ({"tool_calls": [_proxy_call()]}, {"expected": ["other"]}, "not an expected tool"),
        (
            {"tool_calls": [_proxy_call(), _proxy_call(call_id="call_2")]},
            {"count": 1},
            "exactly 1 were required",
        ),
    ],
)
def test_require_tool_calls_raises_on_contract_violations(response_kwargs, gate_kwargs, message):
    """REQ-014-07, BEH-014-04: every contract violation raises LLMToolCallError."""
    response = _response(_proxy_raw(**response_kwargs))

    with pytest.raises(LLMToolCallError, match=message):
        require_tool_calls(response, **gate_kwargs)


def test_tool_exceptions_stay_in_the_llm_client_error_tree():
    """REQ-014-10: tool errors are catchable as LLMClientError, not as ValueError."""
    assert issubclass(LLMToolCallError, LLMClientError)
    assert not issubclass(LLMToolCallError, ValueError)


# ------------------------------------------------------------------- definitions


class _LookupArgs(BaseModel):
    """Look a material up by name."""

    query: str = Field(description="Material name")
    limit: int = 5


def test_tool_definition_as_schema_builds_an_openai_function():
    """REQ-014-08: as_schema produces the OpenAI function envelope."""
    definition = ToolDefinition(name="lookup", description="Look up a material")

    assert definition.as_schema() == {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up a material",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_tool_definition_from_pydantic_builds_parameters_from_the_model_schema():
    """REQ-014-08: parameters come from the model's JSON schema."""
    schema = ToolDefinition.from_pydantic("lookup", _LookupArgs, description="Look up").as_schema()
    parameters = schema["function"]["parameters"]

    assert schema["function"]["name"] == "lookup"
    assert parameters["properties"]["query"]["description"] == "Material name"
    assert parameters["required"] == ["query"]


def test_tool_definition_from_pydantic_rejects_a_model_without_a_schema():
    """REQ-014-08: a non-model type is a clear error rather than an empty schema."""
    with pytest.raises(LLMToolCallError, match="does not expose a JSON schema"):
        ToolDefinition.from_pydantic("lookup", int)


def test_tool_schemas_passes_plain_dicts_through_unchanged():
    """REQ-014-09, BEH-014-05: hand-built schemas keep their exact wire shape."""
    handbuilt = {
        "type": "function",
        "function": {"name": "create_wall", "parameters": {"type": "object"}},
    }

    assert tool_schemas([handbuilt]) == [handbuilt]


def test_tool_schemas_converts_definitions_and_mixes_with_dicts():
    """REQ-014-09: definitions and mappings can be supplied together."""
    handbuilt = {"type": "function", "function": {"name": "raw_tool"}}

    schemas = tool_schemas([ToolDefinition(name="typed_tool"), handbuilt])

    assert [schema["function"]["name"] for schema in schemas] == ["typed_tool", "raw_tool"]


def test_tool_schemas_rejects_unsupported_entries():
    """REQ-014-09: anything that is neither a definition nor a mapping is an error."""
    with pytest.raises(LLMToolCallError, match="ToolDefinition values or OpenAI function"):
        tool_schemas(["lookup"])  # type: ignore[list-item]


# -------------------------------------------------------------- forced single call


def test_call_tool_forces_the_named_tool_and_returns_one_call():
    """REQ-014-13: the tool choice is forced and exactly one call comes back."""
    client = _RecordingClient(_proxy_raw(tool_calls=[_proxy_call()]))
    definition = ToolDefinition.from_pydantic("lookup", _LookupArgs)

    call = call_tool(client, "look up iron", tool=definition, model="medium")

    assert call.name == "lookup"
    assert call.arguments == {"query": "iron"}
    assert client.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "lookup"},
    }
    assert client.calls[0]["model"] == "medium"
    assert client.calls[0]["tools"] == [definition]


def test_call_tool_accepts_a_mapping_schema():
    """REQ-014-13: a hand-built schema can also be forced."""
    client = _RecordingClient(_proxy_raw(tool_calls=[_proxy_call()]))
    schema = {"type": "function", "function": {"name": "lookup", "parameters": {}}}

    assert call_tool(client, "look up iron", tool=schema).name == "lookup"


def test_call_tool_rejects_a_tool_without_a_name():
    """REQ-014-13: forcing a nameless tool is a caller error."""
    client = _RecordingClient(_proxy_raw(tool_calls=[_proxy_call()]))

    with pytest.raises(LLMToolCallError, match="non-empty tool name"):
        call_tool(client, "look up iron", tool={"type": "function", "function": {}})


@pytest.mark.parametrize(
    "tool_calls, message",
    [
        (None, "did not include any tool calls"),
        ([_proxy_call(), _proxy_call(call_id="call_2")], "exactly 1 were required"),
        ([_proxy_call(name="other")], "not an expected tool"),
        ([_proxy_call(arguments="{bad")], "invalid arguments"),
    ],
)
def test_call_tool_raises_for_zero_multiple_or_mismatched_calls(tool_calls, message):
    """REQ-014-13, BEH-014-06: there is no recovery turn, so violations raise."""
    client = _RecordingClient(_proxy_raw(tool_calls=tool_calls))

    with pytest.raises(LLMToolCallError, match=message):
        call_tool(client, "look up iron", tool=ToolDefinition(name="lookup"))


async def test_acall_tool_matches_the_sync_payload_and_result():
    """REQ-014-14: the async helper sends the same payload and returns the same call."""
    raw = _proxy_raw(tool_calls=[_proxy_call()])
    sync_client = _RecordingClient(raw)
    async_client = _AsyncRecordingClient(raw)
    definition = ToolDefinition(name="lookup")

    sync_call = call_tool(sync_client, "look up iron", tool=definition, temperature=0)
    async_call = await acall_tool(async_client, "look up iron", tool=definition, temperature=0)

    assert sync_call == async_call
    assert sync_client.calls == async_client.calls


async def test_acall_tool_raises_like_the_sync_helper():
    """REQ-014-14: error behavior is aligned across sync and async."""
    client = _AsyncRecordingClient(_proxy_raw(tool_calls=None))

    with pytest.raises(LLMToolCallError, match="did not include any tool calls"):
        await acall_tool(client, "look up iron", tool=ToolDefinition(name="lookup"))


def test_tool_call_exposes_the_documented_fields_and_is_frozen():
    """REQ-014-01: ToolCall is a frozen dataclass carrying the raw provider entry."""
    entry = _proxy_call()
    call = parse_tool_calls(_proxy_raw(tool_calls=[entry]))[0]

    assert (call.id, call.name, call.arguments) == ("call_1", "lookup", {"query": "iron"})
    assert call.arguments_error is None
    assert call.raw == entry
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        call.name = "other"  # type: ignore[misc]


def test_tool_calls_are_hashable():
    """REQ-014-01: ToolCall hashes despite its dict-valued arguments field."""
    calls = parse_tool_calls(_proxy_raw(tool_calls=[_proxy_call(), _proxy_call()]))

    assert len(set(calls)) == 1
    assert {calls[0]: "cached"}[calls[1]] == "cached"


@pytest.mark.parametrize("tool_calls", [5, "not-a-list", {"a": 1}, b"bytes"])
def test_parse_tool_calls_ignores_non_list_tool_calls(tool_calls):
    """REQ-014-02: a non-list tool_calls value yields no calls and never raises."""
    assert parse_tool_calls(_proxy_raw(tool_calls=tool_calls)) == ()


@pytest.mark.parametrize("result", ["", "   "])
def test_tool_result_message_substitutes_placeholder_for_blank_results(result):
    """REQ-014-06: a blank result gets placeholder text so replay does not fail."""
    message = tool_result_message("call_1", result)

    assert message["content"] == "(empty result)"
    assert normalize_messages([message]) == [message]


def test_assistant_message_matches_across_proxy_and_object_shapes():
    """REQ-014-05: null fields are stripped from both backend shapes alike."""
    proxy = _proxy_raw(tool_calls=[_proxy_call()])
    proxy["choices"][0]["message"].update({"function_call": None, "refusal": None})
    obj = _object_raw(tool_calls=[_proxy_call()])

    from_proxy = assistant_message(_response(proxy))
    from_object = assistant_message(_response(obj))

    assert from_proxy == from_object
    assert "refusal" not in from_proxy


def test_normalize_messages_accepts_mixed_case_assistant_role():
    """REQ-006-15: the assistant tool-call exemption matches role case-insensitively."""
    message = {"role": "Assistant", "tool_calls": [_proxy_call()]}

    assert normalize_messages([message])[0]["content"] is None


def test_chat_response_still_accepts_the_original_five_arguments():
    """REQ-006-16: appended fields default, so existing downstream construction works."""
    positional = ChatResponse("answer", "medium", "resolved-medium", {"total_tokens": 4}, {})
    keyword = ChatResponse(
        text="answer",
        model_alias="medium",
        provider_model="resolved-medium",
        usage={"total_tokens": 4},
        raw={},
    )

    assert positional == keyword
    assert positional.tool_calls == ()
    assert positional.finish_reason is None
