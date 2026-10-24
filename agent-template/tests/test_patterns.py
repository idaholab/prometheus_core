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

"""Tests for the design-pattern catalog, suggestion, and scaffolding."""

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import frameworks  # noqa: E402
import patterns  # noqa: E402
import setup_agent  # noqa: E402

CATALOG = patterns.load_catalog()
ARCH_SLUGS = list(CATALOG.architectures)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_has_nine_families_and_every_architecture_belongs_to_one():
    assert len(CATALOG.families) == 9
    assert len(CATALOG.architectures) == 36
    used = {a.family for a in CATALOG.architectures.values()}
    assert used == set(CATALOG.families), "every family has at least one architecture"


def test_catalog_slugs_are_unique():
    raw = json.loads(patterns.CATALOG_PATH.read_text(encoding="utf-8"))
    for key in ("families", "architectures", "frameworks"):
        slugs = [e["slug"] for e in raw[key]]
        assert len(slugs) == len(set(slugs)), key


def test_every_framework_has_a_fragment_and_known_recommendations():
    assert set(CATALOG.frameworks) == set(frameworks.framework_slugs())
    for fw in CATALOG.frameworks.values():
        assert set(fw.recommended_for) <= set(CATALOG.families), fw.slug


def test_catalog_has_no_internal_names():
    """The catalog ships in a public repo: no internal system or project names."""
    text = patterns.CATALOG_PATH.read_text(encoding="utf-8").lower()
    for term in ("genesis", "discovery engine", "amsc", "xcard", "github.inl.gov"):
        assert term not in text, term


def test_unknown_topology_is_rejected(tmp_path):
    raw = json.loads(patterns.CATALOG_PATH.read_text(encoding="utf-8"))
    raw["architectures"][0]["topology"] = "spiral"
    bad = tmp_path / "patterns.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown topology"):
        patterns.load_catalog.__wrapped__(bad)


# ---------------------------------------------------------------------------
# Suggestion and repair
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "expected_family"),
    [
        ("Answer questions grounded in retrieved documents, re-querying when the retrieval is weak", "retrieval"),
        ("Draft a report, critique it, and revise it until it is good", "reflection_refinement"),
        ("Monte Carlo forward sampling to quantify the uncertainty of a simulator", "sampling_search"),
        ("A supervisor splits the task and delegates sub-tasks to specialist agents", "multi_agent"),
    ],
)
def test_keyword_suggestion_picks_a_matching_family(description, expected_family):
    plan = patterns.suggest(description)
    assert plan.source == "keyword"
    assert CATALOG.architectures[plan.architecture].family == expected_family


def test_suggestion_without_any_match_falls_back_to_the_default():
    plan = patterns.suggest("zzz qqq")
    assert (plan.architecture, plan.source) == (patterns.DEFAULT_ARCHITECTURE, "default")


def test_repair_plan_fixes_slugs_and_drops_unknowns():
    plan = patterns.repair_plan(
        patterns.Plan(
            architecture="Corrective RAG",
            supporting=["react", "nope", "react", "corrective_rag"],
            framework="LangGraph",
        )
    )
    assert plan.architecture == "corrective_rag"
    assert plan.supporting == ["react"]
    assert plan.framework == "langgraph"
    assert any("nope" in r for r in plan.repairs)
    unknown = patterns.repair_plan(patterns.Plan(architecture="wizardry", framework="spaceship"))
    assert (unknown.architecture, unknown.framework) == (patterns.DEFAULT_ARCHITECTURE, patterns.NATIVE_FRAMEWORK)


def test_parse_llm_reply_tolerates_fences_and_prose():
    reply = 'Sure.\n```json\n{"architecture": "react", "supporting": ["tool_use"], "rationale": "x"}\n```'
    assert patterns.parse_llm_reply(reply)["architecture"] == "react"
    assert patterns.parse_llm_reply("no json here") is None
    assert patterns.parse_llm_reply('{"supporting": []}') is None


def test_llm_prompt_lists_every_architecture():
    prompt = patterns.llm_prompt("anything")
    assert all(f"- {slug}:" in prompt for slug in ARCH_SLUGS)


def test_suggest_with_llm_falls_back_to_keywords_without_an_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "prometheus_api.llm_client", None)
    plan = patterns.suggest_with_llm("Draft, critique and revise an essay")
    assert plan.source in {"keyword", "default"}
    assert any("LLM suggestion unavailable" in r for r in plan.repairs)


def test_suggest_with_llm_uses_and_repairs_the_reply(monkeypatch):
    class Reply:
        text = '{"architecture": "Tree of Thoughts", "supporting": ["bogus"], "rationale": "search"}'

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def small(self, prompt):
            assert "Agent description: solve puzzles" in prompt
            return Reply()

    fake = type(sys)("prometheus_api.llm_client")
    fake.LLMClient = FakeClient
    monkeypatch.setitem(sys.modules, "prometheus_api.llm_client", fake)
    plan = patterns.suggest_with_llm("solve puzzles")
    assert (plan.architecture, plan.source) == ("tree_of_thoughts", "llm")
    assert plan.supporting == [] and any("bogus" in r for r in plan.repairs)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", ARCH_SLUGS)
def test_every_architecture_renders_valid_native_code(slug):
    arch = CATALOG.architectures[slug]
    body = patterns.render_native_pattern(arch)
    module = (
        "import asyncio\nfrom typing import Any\nRequestContext = EventQueue = object\n"
        + patterns.pattern_constants(arch)
        + "\n\nclass A:\n"
        + body
    )
    tree = ast.parse(module)
    methods = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert "_run_pattern" in methods
    assert {f"_step_{n}" for n, _ in arch.steps} <= methods
    # Code lines fit the agent's 100 columns, so ruff format leaves them alone
    # (comments and docstrings may run longer: the agent's ruff ignores E501).
    code = [line for line in body.splitlines() if not line.lstrip().startswith(("#", '"""'))]
    assert all(len(line) <= 100 for line in code), "code fits the agent's line length"


@pytest.mark.parametrize("slug", ARCH_SLUGS)
@pytest.mark.parametrize("framework", frameworks.framework_slugs())
def test_every_framework_variant_parses(slug, framework):
    arch, fw = CATALOG.architectures[slug], CATALOG.frameworks[framework]
    src = frameworks.render_framework_module(arch, fw, "Demo", 'Says "hi"')
    tree = ast.parse(src)
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    assert "run_framework" in names
    ast.parse("class A:\n" + frameworks.render_framework_bridge(arch, fw))


@pytest.mark.parametrize("slug", ["reflection", "react", "self_consistency", "multi_agent"])
def test_mermaid_has_every_step_and_the_topology_edge(slug):
    arch = CATALOG.architectures[slug]
    chart = patterns.render_mermaid(arch)
    assert chart.startswith("flowchart TD")
    assert all(f"{n}[{n}]" in chart for n, _ in arch.steps)
    if arch.topology == "loop":
        assert "not good enough" in chart
    if arch.topology == "cycle":
        assert "continue" in chart


def test_replace_marked_block_requires_the_markers():
    text = "a\n    # >>> design pattern (x)\n    old\n    # <<< design pattern\nb\n"
    assert setup_agent.replace_marked_block(text, "design pattern", "    new\n") == "a\n    new\nb\n"
    with pytest.raises(ValueError, match="not found"):
        setup_agent.replace_marked_block("no markers", "design pattern", "")


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def _replacements(output_dir: Path, **extra: str) -> dict[str, str]:
    return {
        "TEMPLATE_NAME": "Demo Agent",
        "TEMPLATE_DESCRIPTION": "A demo generated agent",
        "TEMPLATE_SLUG": "demo-agent",
        "TEMPLATE_CLASS": "Demo",
        "TEMPLATE_SKILL_ID": "demo_analysis",
        "TEMPLATE_SKILL_NAME": "Demo Analysis",
        "TEMPLATE_SKILL_DESCRIPTION": "Runs demo analysis",
        "OUTPUT_DIR": str(output_dir),
        "TRIM_COMMENTS": "false",
        **extra,
    }


def test_scaffold_writes_the_chosen_native_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing.env")
    out = tmp_path / "agent"
    setup_agent.create_agent(_replacements(out, PATTERN="reflection"))

    agent_py = (out / "agent.py").read_text(encoding="utf-8")
    ast.parse(agent_py)
    assert ">>>" not in agent_py and "<<<" not in agent_py
    for step in ("draft", "critique", "revise"):
        assert f"async def _step_{step}(" in agent_py
    assert "MAX_ITERATIONS = 3" in agent_py
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "## Design pattern: Reflection" in readme and "```mermaid" in readme


def test_scaffold_framework_variant_writes_module_and_dependency(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing.env")
    out = tmp_path / "agent"
    setup_agent.create_agent(_replacements(out, PATTERN="corrective_rag", FRAMEWORK="langgraph"))

    assert (out / "pattern_langgraph.py").is_file()
    ast.parse((out / "pattern_langgraph.py").read_text(encoding="utf-8"))
    agent_py = (out / "agent.py").read_text(encoding="utf-8")
    assert "from pattern_langgraph import run_framework" in agent_py
    assert '"langgraph",' in (out / "pyproject.toml").read_text(encoding="utf-8")


def test_scaffold_without_pattern_keys_uses_the_default(tmp_path, monkeypatch):
    """Old callers that pass no PATTERN still get a valid agent (the default pattern)."""
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing.env")
    out = tmp_path / "agent"
    setup_agent.create_agent(_replacements(out))
    assert "_step_decide_tool" in (out / "agent.py").read_text(encoding="utf-8")


def test_yes_with_pattern_and_framework_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("--yes must not prompt"))
    out = tmp_path / "doc-qa"
    setup_agent.main(["--yes", "--pattern", "self_rag", "--framework", "strands", "Doc QA", str(out)])
    assert (out / "pattern_strands.py").is_file()
    assert "Self-RAG" in (out / "README.md").read_text(encoding="utf-8")


def test_unknown_pattern_or_framework_flag_is_an_error():
    with pytest.raises(SystemExit):
        setup_agent.parse_args(["--pattern", "wizardry", "Demo"])
    with pytest.raises(SystemExit):
        setup_agent.parse_args(["--framework", "spaceship", "Demo"])


def test_list_patterns_prints_every_family(capsys):
    setup_agent.main(["--list-patterns"])
    out = capsys.readouterr().out
    assert all(f.name in out for f in CATALOG.families.values())
    assert "corrective_rag" in out


def test_declining_the_suggestion_lets_the_user_pick(monkeypatch):
    answers = iter(["no", "debate", "native"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    plan = setup_agent.choose_pattern("Draft and revise an essay")
    assert (plan.architecture, plan.source, plan.framework) == ("debate", "user", "native")


def test_scaffold_records_the_pattern_on_the_agent_card(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing.env")
    out = tmp_path / "agent"
    setup_agent.create_agent(_replacements(out, PATTERN="react", PATTERN_SUPPORTING="tool_use", FRAMEWORK="langgraph"))
    card = json.loads((out / "agent_card.json").read_text(encoding="utf-8"))
    assert card["designPattern"] == {
        "architecture": "react",
        "family": "tool_use_actions",
        "topology": "cycle",
        "supporting": ["tool_use"],
        "framework": "langgraph",
    }
    assert card["skills"][0]["id"] == "demo_analysis"  # the rest of the card is untouched


def test_card_with_pattern_loads_through_the_sdk(tmp_path, monkeypatch):
    """The SDK parses the card with ignore_unknown_fields and keeps the raw extension."""
    agent_mod = pytest.importorskip("prometheus_api.agent")
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing.env")
    out = tmp_path / "agent"
    setup_agent.create_agent(_replacements(out, PATTERN="reflection"))

    class Probe(agent_mod.PrometheusAgent):
        async def _execute(self, params, context, event_queue):
            return {}

    probe = Probe(agent_name="Demo Agent", agent_card_path=str(out / "agent_card.json"))
    card = probe.load_agent_card()
    assert card.name and card.skills[0].id == "demo_analysis"
    assert probe.get_raw_agent_card()["designPattern"]["architecture"] == "reflection"
