"""Tests for the code render debug agent: deterministic samples, `lines`, and routing."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

AGENT_DIR = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location("code_render_debug_agent_module", AGENT_DIR / "agent.py")
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
CodeRenderDebugAgent = _MODULE.CodeRenderDebugAgent
SAMPLES = _MODULE.SAMPLES
MAX_LINES = _MODULE.MAX_LINES
NEUTRAL_NAME = _MODULE.NEUTRAL_NAME
build_body = _MODULE.build_body
parse_lines = _MODULE.parse_lines

ALL_SKILLS = sorted(SAMPLES)


class _Run:
    """Result of one skill invocation, with the artifact the agent registered and sent."""

    def __init__(self, result, agent, queue):
        self.result = result
        self.agent = agent
        self.queue = queue

    @property
    def registered(self):
        """The ArtifactReference passed to register_artifact_reference."""
        return self.agent.register_artifact_reference.call_args.args[1]

    @property
    def sent(self):
        """Keyword/positional args of send_text_artifact."""
        call = self.agent.send_text_artifact.call_args
        return call.args, call.kwargs


def _run(skill_id: str, **params) -> _Run:
    agent = CodeRenderDebugAgent(agent_name="Code Render Debug Agent")
    # Registry and event emission need Valkey / a live A2A stack; the agent logic does not.
    agent.register_artifact_reference = MagicMock(side_effect=lambda _ctx, ref: ref)
    agent.send_text_artifact = AsyncMock()
    agent.send_status_update = AsyncMock()
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-1"
    context.context_id = "ctx-1"
    context.message = MagicMock(parts=[])
    queue = AsyncMock(spec=EventQueue)
    result = asyncio.run(agent._execute({"skill_id": skill_id, **params}, context, queue))
    return _Run(result, agent, queue)


def test_card_skills_match_samples():
    card = json.loads((AGENT_DIR / "agent_card.json").read_text(encoding="utf-8"))
    assert sorted(skill["id"] for skill in card["skills"]) == ALL_SKILLS
    for skill in card["skills"]:
        props = skill["inputSchema"]["properties"]
        assert set(props) == {"lines", "routing"}
        assert props["lines"]["maximum"] == MAX_LINES


@pytest.mark.parametrize("skill_id", ALL_SKILLS)
def test_sample_file_exists_and_is_non_empty(skill_id):
    path = SAMPLES[skill_id].sample_path
    assert path.is_file(), path
    assert path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("skill_id", ALL_SKILLS)
def test_same_input_gives_identical_bytes(skill_id):
    first, second = _run(skill_id), _run(skill_id)
    assert first.result["status"] == "created"
    assert first.registered.text_body == second.registered.text_body
    assert first.result["sha256"] == second.result["sha256"]
    assert first.result["artifact_id"] != second.result["artifact_id"]  # ids are random


@pytest.mark.parametrize("skill_id", ALL_SKILLS)
def test_registered_and_sent_artifact_agree(skill_id):
    run = _run(skill_id)
    spec = SAMPLES[skill_id]
    ref = run.registered
    assert ref.name == spec.filename and ref.mime_type == spec.mime_type
    assert ref.tags == ["debug", "code", spec.language]
    assert ref.artifact_id == run.result["artifact_id"]
    args, kwargs = run.sent
    assert kwargs["text"] == ref.text_body
    assert kwargs["name"] == ref.name
    assert kwargs["artifact_id"] == ref.artifact_id


@pytest.mark.parametrize("skill_id", ALL_SKILLS)
@pytest.mark.parametrize("lines", [0, 1, 2, 3, 5, 12, 100])
def test_lines_gives_exactly_n_lines(skill_id, lines):
    run = _run(skill_id, lines=lines)
    body = run.registered.text_body
    assert run.result["line_count"] == lines
    assert len(body.splitlines()) == lines
    assert (body == "") == (lines == 0)


@pytest.mark.parametrize("lines", [1, 2, 3, 4, 5, 50, 1000])
def test_json_stays_valid_json_for_any_nonzero_line_count(lines):
    body = _run("render_json_sample", lines=lines).registered.text_body
    json.loads(body)


def test_json_natural_sample_is_valid_json():
    json.loads(_run("render_json_sample").registered.text_body)


@pytest.mark.parametrize("skill_id", ALL_SKILLS)
def test_zero_lines_is_an_empty_file_with_the_same_name_and_mime(skill_id):
    run = _run(skill_id, lines=0)
    spec = SAMPLES[skill_id]
    ref = run.registered
    assert ref.text_body == "" and ref.size_bytes == 0
    assert ref.name == spec.filename and ref.mime_type == spec.mime_type
    assert run.result["line_count"] == 0
    # The empty body is still emitted (an empty string, not skipped).
    assert run.sent[1]["text"] == ""


def test_padding_is_deterministic_and_prefix_stable():
    short = build_body(SAMPLES["render_python_sample"], 5)
    long = build_body(SAMPLES["render_python_sample"], 500)
    assert long.startswith(short)
    assert build_body(SAMPLES["render_python_sample"], 500) == long


def test_cutting_keeps_the_start_of_the_sample():
    spec = SAMPLES["render_python_sample"]
    assert build_body(spec, 3) == "\n".join(spec.sample_path.read_text(encoding="utf-8").splitlines()[:3]) + "\n"


def test_max_lines_is_accepted_and_past_the_highlight_cutoff():
    body = _run("render_python_sample", lines=MAX_LINES).registered.text_body
    assert len(body.splitlines()) == MAX_LINES
    assert len(body) > 200_000  # the viewer's MAX_HIGHLIGHT_BYTES


@pytest.mark.parametrize("skill_id", ALL_SKILLS)
def test_routing_both_is_the_default(skill_id):
    assert _run(skill_id, routing="both").registered.name == _run(skill_id).registered.name


@pytest.mark.parametrize("skill_id", ALL_SKILLS)
def test_routing_extension_drops_the_mime_type(skill_id):
    ref = _run(skill_id, routing="extension").registered
    assert ref.name == SAMPLES[skill_id].filename and ref.mime_type is None


@pytest.mark.parametrize("skill_id", [s for s in ALL_SKILLS if SAMPLES[s].mime_type])
def test_routing_mime_uses_a_neutral_name(skill_id):
    ref = _run(skill_id, routing="mime").registered
    assert ref.name == NEUTRAL_NAME and ref.mime_type == SAMPLES[skill_id].mime_type


@pytest.mark.parametrize("skill_id", [s for s in ALL_SKILLS if not SAMPLES[s].mime_type])
def test_routing_mime_errors_when_no_mime_routes_to_code(skill_id):
    run = _run(skill_id, routing="mime")
    assert run.result["status"] == "error"
    run.agent.register_artifact_reference.assert_not_called()


@pytest.mark.parametrize("bad", [-1, MAX_LINES + 1, "abc", 1.5, True])
def test_invalid_lines_is_an_error_and_emits_nothing(bad):
    run = _run("render_python_sample", lines=bad)
    assert run.result["status"] == "error"
    run.agent.register_artifact_reference.assert_not_called()
    run.agent.send_text_artifact.assert_not_called()


def test_invalid_routing_is_an_error():
    assert _run("render_python_sample", routing="nope").result["status"] == "error"


def test_unknown_skill_is_an_error_listing_the_available_ones():
    run = _run("render_cobol_sample")
    assert run.result["status"] == "error"
    assert run.result["available_skills"] == ALL_SKILLS


def test_parse_lines():
    assert parse_lines(None) is None
    assert parse_lines("") is None
    assert parse_lines(0) == 0
    assert parse_lines("12") == 12
    assert parse_lines(12.0) == 12
