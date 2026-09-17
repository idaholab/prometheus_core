"""Provider-agnostic LLM client integration tests for the orchestrator."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from capability_cache import AgentCapability
from orchestrator import runtime
from planner import compile_plan_with_tools


class _FakePlannerLLM:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def medium(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if len(self.calls) == 1:
            tool_calls = [
                {
                    "id": "resolve-1",
                    "type": "function",
                    "function": {
                        "name": "resolve_new_task",
                        "arguments": json.dumps(
                            {
                                "standalone_request": (
                                    "Analyze the thermal behavior of SS316"
                                ),
                            }
                        ),
                    },
                }
            ]
        elif len(self.calls) == 2:
            tool_calls = [
                {
                    "id": "decompose-1",
                    "type": "function",
                    "function": {
                        "name": "decompose_task",
                        "arguments": json.dumps(
                            {
                                "operation_descriptions": [
                                    "Analyze the material's thermal behavior",
                                ],
                            }
                        ),
                    },
                }
            ]
        else:
            tool_calls = [
                {
                    "id": "select-1",
                    "type": "function",
                    "function": {
                        "name": "select_capabilities",
                        "arguments": json.dumps(
                            {
                                "primary_skill": "analyze_thermal",
                                "supporting_skills": [],
                                "workflow_type": "single",
                                "reasoning": "Thermal request",
                                "confidence": 0.9,
                            }
                        ),
                    },
                },
                {
                    "id": "coverage-1",
                    "type": "function",
                    "function": {
                        "name": "set_operation_coverage",
                        "arguments": json.dumps(
                            {
                                "covered": [
                                    {
                                        "operation_id": "op_1",
                                        "skill_id": "analyze_thermal",
                                    }
                                ],
                                "unsupported": [],
                            }
                        ),
                    },
                },
                {
                    "id": "finalize-1",
                    "type": "function",
                    "function": {
                        "name": "finalize_plan",
                        "arguments": "{}",
                    },
                },
            ]
        return SimpleNamespace(
            raw={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": tool_calls,
                        }
                    }
                ]
            }
        )


def test_planner_uses_llm_client_raw_tool_calls(monkeypatch):
    fake_llm = _FakePlannerLLM()
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)
    capability = AgentCapability(
        agent_id="thermal-agent",
        agent_name="Thermal Agent",
        agent_url="http://thermal-agent:8000",
        skill_id="analyze_thermal",
        skill_name="Analyze thermal behavior",
        description="Analyze material thermal behavior.",
    )

    result = asyncio.run(
        compile_plan_with_tools(
            query="Analyze the thermal behavior of SS316",
            capabilities=[capability],
        )
    )

    assert result.outcome == "agent_plan"
    assert result.primary_skill == "analyze_thermal"
    resolution_messages, resolution_kwargs = fake_llm.calls[0]
    assert "Available capabilities" not in resolution_messages[1]["content"]
    assert [tool["function"]["name"] for tool in resolution_kwargs["tools"]] == [
        "resolve_new_task",
        "resolve_prior_result_discussion",
        "resolve_needs_clarification",
    ]
    decomposition_messages, decomposition_kwargs = fake_llm.calls[1]
    assert "Available capabilities" not in decomposition_messages[1]["content"]
    assert [tool["function"]["name"] for tool in decomposition_kwargs["tools"]] == [
        "decompose_task"
    ]
    messages, kwargs = fake_llm.calls[2]
    assert [message["role"] for message in messages[:2]] == ["system", "user"]
    assert "Analyze the thermal behavior of SS316" in messages[1]["content"]
    assert "Required operations (immutable)" in messages[1]["content"]
    assert "Every dynamically selected capability must cover" in messages[0]["content"]
    assert "Remeshing an existing CAD artifact" in messages[0]["content"]
    assert {tool["function"]["name"] for tool in kwargs["tools"]} >= {
        "select_capabilities",
        "set_operation_coverage",
        "finalize_plan",
    }
    assert "fallback_to_chat" not in {
        tool["function"]["name"] for tool in kwargs["tools"]
    }


def test_runtime_client_uses_proxy_configuration(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "proxy-key")

    client = runtime.create_llm()

    assert client.config.proxy_url == "http://litellm:4000"
    assert client.config.api_key == "proxy-key"
    assert client.config.app_name == "Nuclear Analysis Client Agent"


def test_runtime_client_preserves_direct_profile_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "direct.yaml"
    config_path.write_text(
        """
model_list:
  - model_name: medium
    litellm_params:
      model: openai/test-model
      api_key: os.environ/OPENAI_API_KEY
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "proxy-key")

    client = runtime.create_llm()
    medium = client.config.load_fallback_models()["medium"]

    assert client.config.proxy_url is None
    assert client.config.api_key is None
    assert medium.litellm_params["api_key"] == "provider-key"
