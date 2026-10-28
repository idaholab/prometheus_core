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

import asyncio
import json

import pytest
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from research_agent.core.config import AgentConfig
from research_agent.core.deep_agent import (
    VerificationResult,
    _analyze_paper,
    _parsed_paper_directory,
    build_paper_analyzer,
    build_paper_verifier,
    build_research_agent,
)
from research_agent.core.deep_runner import build_final_result
from research_agent.core.events import Finding
from research_agent.tools import RunContext


async def _fake_complete(prompt, *, max_tokens, temperature=0):
    return "stub"


class _FakeRunnable:
    def __init__(self, result=None, error=None, delay=0):
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = 0
        self.inputs = []

    async def ainvoke(self, _input, config=None):
        self.calls += 1
        self.inputs.append(_input)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


class _HangingRunnable:
    async def ainvoke(self, _input, config=None):
        await asyncio.sleep(3600)


class _ToolBindingFakeChatModel(BaseChatModel):
    responses: list[AIMessage]
    seen: list[list] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "tool-binding-fake"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class _FakeKnowledgeStore:
    async def search_facts(self, query, k=8):
        return []

    async def get_cached_answer(self, question):
        return None

    async def store_fact(self, **kwargs):
        return "fact-1"

    async def cache_answer(self, question, answer, sources):
        return None


def _verification(**overrides):
    values = {
        "verdict": "supported",
        "source_id": "123",
        "answer": "Titanium creeps above 800 C.",
        "evidence": "Table 1 reports the measured creep rate.",
        "excerpt": "Measured creep begins above 800 C.",
        "artifacts": ["/papers/123/paper.md"],
        "reason": "The paper directly supports the claim.",
    }
    values.update(overrides)
    return VerificationResult(**values)


def _verification_result(*, read_path=None, **overrides):
    verification = _verification(**overrides)
    if read_path is None:
        read_path = next(
            (
                artifact
                for artifact in verification.artifacts
                if artifact.endswith("/paper.md")
            ),
            "/papers/123/paper.md",
        )
    return {
        "structured_response": verification,
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": read_path},
                        "id": "verify-read",
                        "type": "tool_call",
                    }
                ],
            )
        ],
    }


def _verification_text_result(**overrides):
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/papers/123/paper.md"},
                        "id": "verify-read",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=_verification(**overrides).model_dump_json()),
        ],
    }


def _verification_context(tmp_path, source_id="123"):
    paper = tmp_path / "papers" / source_id
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "paper.md").write_text("Measured creep begins above 800 C.")
    (paper / "meta.json").write_text(json.dumps({"source_id": source_id}))
    context = RunContext(
        config=AgentConfig(litellm_base_url="http://unused", workdir=tmp_path),
        complete=_fake_complete,
        run_workdir=tmp_path,
    )
    context.parsed_papers[source_id] = {
        "source_id": source_id,
        "dir": f"/papers/{source_id}",
    }
    return context


def _analysis_result(source_id="123"):
    return {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "source_id": source_id,
                        "answer": "Titanium creeps above 800 C.",
                        "evidence": "Table 1 reports creep.",
                        "excerpt": "creep begins above 800 C",
                        "artifacts": [f"/papers/{source_id}/paper.md"],
                    }
                )
            )
        ]
    }


def test_real_graph_exposes_structured_paper_analysis_tool(tmp_path):
    config = AgentConfig(
        litellm_base_url="http://unused",
        litellm_api_key="dummy",
        workdir=tmp_path,
    )
    context = RunContext(
        config=config,
        complete=_fake_complete,
        run_workdir=tmp_path,
    )

    graph = build_research_agent(config, context)
    tools = graph.nodes["tools"].bound._tools_by_name

    assert "analyze_paper" in tools
    assert "task" not in tools
    assert set(tools["analyze_paper"].args) == {"source_id", "question"}


def test_paper_analyzer_has_bounded_model_and_tool_calls():
    config = AgentConfig(
        litellm_base_url="http://unused",
        litellm_api_key="dummy",
        analyzer_model_call_limit=6,
        analyzer_tool_call_limit=10,
    )

    spec = build_paper_analyzer(config)
    middleware = spec["middleware"]

    tool_limit = next(m for m in middleware if isinstance(m, ToolCallLimitMiddleware))
    model_limit = next(m for m in middleware if isinstance(m, ModelCallLimitMiddleware))
    assert tool_limit.run_limit == 10
    assert tool_limit.exit_behavior == "continue"
    assert model_limit.run_limit == 6
    assert model_limit.exit_behavior == "end"
    normalized_prompt = " ".join(spec["system_prompt"].split())
    assert "at most 6 model turns and 10 filesystem calls" in normalized_prompt
    assert spec["permissions"][0].operations == ["read"]
    assert spec["permissions"][-1].operations == ["write"]
    assert spec["permissions"][-1].mode == "deny"


def test_verification_schema_avoids_union_and_enum_keywords():
    schema_text = json.dumps(VerificationResult.model_json_schema())

    for forbidden in ("oneOf", "anyOf", "allOf", "enum", "const", "not"):
        assert f'"{forbidden}"' not in schema_text
    assert "confidence" not in VerificationResult.model_fields


def test_paper_verifier_uses_the_configured_call_limits(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        "deepagents.create_deep_agent", lambda **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr(
        "research_agent.core.deep_agent.chat_model", lambda config, role: object()
    )
    config = AgentConfig(
        litellm_base_url="http://unused",
        workdir=tmp_path,
        verifier_model_call_limit=14,
        verifier_tool_call_limit=20,
    )

    build_paper_verifier(config, backend=object())

    middleware = captured["middleware"]
    tool_limit = next(m for m in middleware if isinstance(m, ToolCallLimitMiddleware))
    model_limit = next(m for m in middleware if isinstance(m, ModelCallLimitMiddleware))
    assert (model_limit.run_limit, tool_limit.run_limit) == (14, 20)
    prompt = " ".join(captured["system_prompt"].split())
    assert "14" in prompt and "20" in prompt


def test_verifier_limits_default_higher_than_before():
    config = AgentConfig(litellm_base_url="http://unused")

    assert (config.verifier_model_call_limit, config.verifier_tool_call_limit) == (10, 12)


def test_paper_verifier_does_not_force_structured_output_tool(monkeypatch, tmp_path):
    captured = {}
    sentinel = object()

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(
        "research_agent.core.deep_agent.chat_model",
        lambda config, role: object(),
    )

    config = AgentConfig(litellm_base_url="http://unused", workdir=tmp_path)

    assert build_paper_verifier(config, backend=object()) is sentinel
    assert "response_format" not in captured


def test_supported_candidate_enters_run_context(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(result=_verification_result())

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["source_id"] == "123"
    assert len(context.findings) == 1
    assert context.findings[0].evidence == "Table 1 reports the measured creep rate."
    assert context.verification_errors == []
    analyzer_prompt = analyzer.inputs[0]["messages"][0]["content"]
    assert "Does titanium creep?" in analyzer_prompt
    assert "Parsed paper directory: /papers/123" in analyzer_prompt


def test_verifier_accepts_valid_json_text_fallback(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(result=_verification_text_result())

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["source_id"] == "123"
    assert context.findings == [
        Finding(
            source_id="123",
            answer="Titanium creeps above 800 C.",
            evidence="Table 1 reports the measured creep rate.",
            excerpt="Measured creep begins above 800 C.",
            artifacts=["/papers/123/paper.md"],
        )
    ]
    assert context.verification_errors == []


def test_missing_verifier_result_is_a_protocol_failure(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result={"messages": [AIMessage(content="Verification complete.")]}
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result == {
        "answered": False,
        "reason": "verifier protocol failure; do not retry source 123",
    }
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def test_malformed_verifier_json_is_a_protocol_failure(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result={"messages": [AIMessage(content='{"verdict": "supported"}')]}
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def test_verifier_model_limit_is_classified(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result={
            "messages": [
                AIMessage(content="Model call limits exceeded: run limit (6/6)")
            ]
        }
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result == {
        "answered": False,
        "reason": "verifier model limit; do not retry source 123",
    }
    assert context.verification_errors == ["123: verifier_model_limit"]


def test_verifier_model_limit_logs_one_line_without_a_traceback(tmp_path, caplog):
    limit = {"messages": [AIMessage(content="Model call limits exceeded: run limit (6/6)")]}
    with caplog.at_level("WARNING", logger="research_agent.core.deep_agent"):
        asyncio.run(
            _analyze_paper(
                "123",
                "Does titanium creep?",
                analyzer=_FakeRunnable(result=_analysis_result()),
                verifier=_FakeRunnable(result=limit),
                ctx=_verification_context(tmp_path),
            )
        )

    (record,) = [r for r in caplog.records if "Paper analysis failed" in r.getMessage()]
    assert "verifier_model_limit" in record.getMessage()
    assert not record.exc_info  # logged without a traceback


def test_other_verifier_failures_keep_their_traceback(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="research_agent.core.deep_agent"):
        asyncio.run(
            _analyze_paper(
                "123",
                "Does titanium creep?",
                analyzer=_FakeRunnable(result=_analysis_result()),
                verifier=_FakeRunnable(error=RuntimeError("provider down")),
                ctx=_verification_context(tmp_path),
            )
        )

    (record,) = [r for r in caplog.records if "Paper analysis failed" in r.getMessage()]
    assert "verifier_provider_failure" in record.getMessage()
    assert record.exc_info is not None


def test_json_fallback_still_requires_read_and_cited_paper_markdown(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result=_verification_text_result(
            artifacts=["/papers/123/meta.json"],
        )
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def test_parsed_paper_directory_is_resolved_from_run_context(tmp_path):
    context = _verification_context(tmp_path)

    assert _parsed_paper_directory("123", context) == "/papers/123"


def test_osti_id_alias_resolves_to_parsed_doi_source(tmp_path):
    source_id = "10.2172_7338208"
    paper_path = f"/papers/{source_id}/paper.md"
    context = _verification_context(tmp_path, source_id)
    analyzer = _FakeRunnable(result=_analysis_result(source_id))
    verifier = _FakeRunnable(
        result=_verification_result(
            source_id=source_id,
            artifacts=[paper_path],
            read_path=paper_path,
        )
    )

    async def run_with_both_identifiers():
        first = await _analyze_paper(
            source_id,
            "Does graphite irradiation cause dimensional change?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        second = await _analyze_paper(
            "7338208",
            "Does graphite irradiation cause dimensional change?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        return first, second

    first, second = asyncio.run(run_with_both_identifiers())

    assert first == second
    assert first["source_id"] == source_id
    assert analyzer.calls == 1
    assert verifier.calls == 1
    assert context.verification_errors == []


def test_unparsed_source_can_be_retried_after_parsing(tmp_path):
    context = _verification_context(tmp_path)
    context.parsed_papers.clear()
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(result=_verification_result())

    async def run_twice():
        first = await _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        second = await _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        return first, second

    first, second = asyncio.run(run_twice())

    assert first == second
    assert first["answered"] is False
    assert first["terminal"] is False
    assert first["required_action"].startswith("Call download_paper and parse_paper")
    assert analyzer.calls == 0
    assert verifier.calls == 0
    assert context.verification_errors == []

    paper = tmp_path / "papers" / "123"
    context.parsed_papers["123"] = {
        "source_id": "123",
        "dir": "/papers/123",
    }
    assert paper.is_dir()

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["source_id"] == "123"
    assert analyzer.calls == 1
    assert verifier.calls == 1


def test_analyzer_source_must_match_requested_paper(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result(source_id="999"))
    verifier = _FakeRunnable(result=_verification_result())

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result == {
        "answered": False,
        "reason": "task source mismatch; do not retry source 123",
    }
    assert analyzer.calls == 1
    assert verifier.calls == 0
    assert context.verification_errors == ["123: task_source_mismatch"]


def test_corrected_candidate_replaces_analyzer_claim(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result=_verification_result(
            verdict="corrected",
            answer="Titanium creeps at 825 C in the reported test.",
            evidence="The paper reports 825 C, not 800 C.",
        )
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answer"] == "Titanium creeps at 825 C in the reported test."
    assert context.findings[0].evidence == "The paper reports 825 C, not 800 C."


def test_rejected_candidate_never_enters_run_context(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result=_verification_result(
            verdict="rejected",
            answer="",
            evidence="",
            excerpt="",
            artifacts=[],
            reason="The paper does not report this temperature.",
        )
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result == {
        "answered": False,
        "reason": "The paper does not report this temperature.",
    }
    assert context.findings == []
    assert context.verification_errors == []


def test_duplicate_supported_source_runs_models_once(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result(), delay=0.01)
    verifier = _FakeRunnable(result=_verification_result(), delay=0.01)

    async def run_concurrently():
        return await asyncio.gather(
            _analyze_paper(
                "123",
                "Does titanium creep?",
                analyzer=analyzer,
                verifier=verifier,
                ctx=context,
            ),
            _analyze_paper(
                "123",
                "Does titanium creep?",
                analyzer=analyzer,
                verifier=verifier,
                ctx=context,
            ),
        )

    first, second = asyncio.run(run_concurrently())

    assert first == second
    assert first["source_id"] == "123"
    assert analyzer.calls == 1
    assert verifier.calls == 1
    assert len(context.findings) == 1


def test_duplicate_rejected_source_runs_models_once(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result=_verification_result(
            verdict="rejected",
            answer="",
            evidence="",
            excerpt="",
            artifacts=[],
            reason="The paper does not answer the question.",
        )
    )

    async def run_twice():
        first = await _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        second = await _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        return first, second

    first, second = asyncio.run(run_twice())

    assert first == second
    assert first["answered"] is False
    assert analyzer.calls == 1
    assert verifier.calls == 1
    assert context.verification_errors == []


def test_verifier_failure_is_recorded_without_exposing_candidate(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(error=RuntimeError("provider unavailable"))

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert result["reason"] == ("verifier provider failure; do not retry source 123")
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_provider_failure"]


def test_duplicate_failed_source_runs_models_once(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(error=RuntimeError("provider unavailable"))

    async def run_twice():
        first = await _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        second = await _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
        return first, second

    first, second = asyncio.run(run_twice())

    assert first == second
    assert analyzer.calls == 1
    assert verifier.calls == 1
    assert context.verification_errors == ["123: verifier_provider_failure"]


def test_verifier_rejects_artifact_outside_source_directory(tmp_path):
    context = _verification_context(tmp_path)
    other = tmp_path / "papers" / "other"
    other.mkdir()
    (other / "paper.md").write_text("unrelated")
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result=_verification_result(
            artifacts=["/papers/other/paper.md"],
        )
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def test_verifier_rejects_source_id_changes(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(result=_verification_result(source_id="999"))

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def test_verifier_must_read_accepted_artifacts(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result={
            "structured_response": _verification(),
            "messages": [],
        }
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def test_verifier_must_cite_paper_markdown(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(
        result={
            "structured_response": _verification(
                artifacts=["/papers/123/meta.json"],
            ),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_file",
                            "args": {"file_path": "/papers/123/meta.json"},
                            "id": "verify-meta",
                            "type": "tool_call",
                        },
                        {
                            "name": "read_file",
                            "args": {"file_path": "/papers/123/paper.md"},
                            "id": "verify-paper",
                            "type": "tool_call",
                        },
                    ],
                )
            ],
        }
    )

    result = asyncio.run(
        _analyze_paper(
            "123",
            "Does titanium creep?",
            analyzer=analyzer,
            verifier=verifier,
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert context.findings == []
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def test_timeout_during_verification_never_exposes_candidate(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())

    async def run():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                _analyze_paper(
                    "123",
                    "Does titanium creep?",
                    analyzer=analyzer,
                    verifier=_HangingRunnable(),
                    ctx=context,
                ),
                timeout=0.01,
            )

    asyncio.run(run())

    assert context.findings == []
    assert context.verification_errors == []


def test_real_compiled_task_reads_artifacts_and_returns_verified_finding(
    tmp_path,
    monkeypatch,
):
    paper = tmp_path / "papers" / "123"
    paper.mkdir(parents=True)
    (paper / "meta.json").write_text(
        json.dumps({"source_id": "123", "tables": [], "figures": []})
    )
    (paper / "paper.md").write_text(
        "# Results\nTitanium creeps above 800 C.",
    )
    analyzer = _ToolBindingFakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/papers/123/paper.md"},
                        "id": "analysis-read",
                        "type": "tool_call",
                    }
                ],
            ),
            _analysis_result()["messages"][0],
        ]
    )
    verifier = _ToolBindingFakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/papers/123/paper.md"},
                        "id": "verify-read",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=_verification().model_dump_json()),
        ]
    )
    orchestrator = _ToolBindingFakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_paper",
                        "args": {
                            "source_id": "123",
                            "question": "Does titanium creep?",
                        },
                        "id": "analysis-task",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content=json.dumps(
                    {
                        "answer": "Titanium creeps above 800 C.",
                        "findings": [
                            {
                                "source_id": "123",
                                "answer": "unverified orchestrator copy",
                            }
                        ],
                    }
                )
            ),
        ]
    )
    monkeypatch.setattr(
        "research_agent.core.deep_agent.chat_model",
        lambda config, role: {
            "orchestrator": orchestrator,
            "analyzer": analyzer,
            "verifier": verifier,
        }[role],
    )
    context = _verification_context(tmp_path)
    context.knowledge = _FakeKnowledgeStore()
    graph = build_research_agent(context.config, context)
    graph_result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="Does titanium creep?")]},
            config={"recursion_limit": 80},
        )
    )

    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(
        "research_agent.llm_steps.suggest_followup_from_findings",
        no_followups,
    )
    final = asyncio.run(
        build_final_result(
            "Does titanium creep?",
            graph_result["messages"][-1].content,
            context,
        )
    )

    assert final.status == "completed"
    assert final.findings[0].answer == "Titanium creeps above 800 C."
    assert "unverified orchestrator copy" not in final.answer
    assert "confidence" not in context.findings[0].model_dump()
    assert any(message.type == "tool" for message in analyzer.seen[-1])
    assert any(message.type == "tool" for message in verifier.seen[-1])
    assert any(message.type == "tool" for message in orchestrator.seen[-1])
