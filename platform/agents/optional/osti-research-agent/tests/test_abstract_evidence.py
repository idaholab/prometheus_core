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

"""Abstract evidence: code-checked statements from the abstracts of papers
whose full text could not be read, kept apart from verified findings."""

import asyncio
import json

import pytest

from research_agent import llm_steps
from research_agent.core import deep_runner
from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding
from research_agent.tools import RunContext, build_tools
from research_agent.tools import evidence

ABSTRACT = (
    "Thermal creep of type 316 stainless steel was measured at 550 °C under "
    "120 MPa; the minimum creep rate was 3.2e-9 /s, and creep was negligible "
    "below 450 °C."
)


def _ctx():
    ctx = RunContext(config=AgentConfig(litellm_base_url="http://unused"), complete=None)
    ctx.search_hits["3729583"] = {
        "title": "Creep of 316 SS", "url": "https://www.osti.gov/biblio/3729583",
        "description": ABSTRACT,
    }
    ctx.download_failures["3729583"] = "PDF not available for download"
    return ctx


def _record(ctx, **args):
    values = {"source_id": "3729583", "statement": "", "quote": ""}
    values.update(args)
    tool = next(t for t in build_tools(ctx) if t.name == "record_abstract_evidence")
    return json.loads(asyncio.run(tool.ainvoke(values)))


QUOTE = "the minimum creep rate was 3.2e-9 /s"


def test_a_supported_statement_is_kept():
    ctx = _ctx()
    out = _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    assert out["ok"] is True
    assert ctx.abstract_evidence[0]["quote"] == QUOTE
    assert ctx.findings == []  # never a finding


@pytest.mark.parametrize(
    "statement, quote, error",
    [
        # Even a material grade counts: every number must be in the quote.
        ("Rate of 3.2e-9 /s for 316 SS", QUOTE, "numbers not in the cited text: 316"),
        ("Rate of 3.2e-9 /s", "the minimum creep rate is 3.2e-9 /s", "not word for word"),
        ("Rate of 4.0e-9 /s", QUOTE, "numbers not in the cited text: 4.0e-9"),
        ("At 400 °C the rate was 3.2e-9 /s", QUOTE, "400"),
        ("", QUOTE, "both required"),
    ],
)
def test_unsupported_statements_are_refused(statement, quote, error):
    ctx = _ctx()
    out = _record(ctx, statement=statement, quote=quote)

    assert out["ok"] is False and error in out["error"]
    assert ctx.abstract_evidence == []


def test_a_number_with_a_changed_unit_is_refused():
    quote = "measured at 550 °C under 120 MPa"
    assert evidence.supported_by("550 °C and 120 MPa", quote) is None
    assert "120 ksi" in evidence.supported_by("550 °C and 120 ksi", quote)


def test_only_for_papers_whose_full_text_could_not_be_read():
    ctx = _ctx()
    del ctx.download_failures["3729583"]  # not tried yet: could be readable

    out = _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    assert out["ok"] is False and "may be readable" in out["error"]


def test_not_for_a_paper_that_already_has_a_finding():
    ctx = _ctx()
    ctx.findings.append(Finding(source_id="3729583", answer="a"))

    out = _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    assert out["ok"] is False and "verified finding" in out["error"]


def test_a_scholarly_result_without_a_pdf_counts_as_unreadable():
    ctx = _ctx()
    ctx.search_hits["10.1_x"] = {"origin": "openalex", "oa_pdf_url": None, "abstract": ABSTRACT}

    out = _record(ctx, source_id="10.1_x", statement="Rate of 3.2e-9 /s", quote=QUOTE)

    assert out["ok"] is True


def test_unknown_source_is_refused():
    out = _record(_ctx(), source_id="999", statement="x", quote="x")

    assert out["ok"] is False and "unknown source_id" in out["error"]


def _final(ctx, monkeypatch):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    return asyncio.run(
        deep_runner.build_final_result("q", json.dumps({"findings": []}), ctx)
    )


def test_abstract_evidence_gets_its_own_labelled_section(monkeypatch):
    ctx = _ctx()
    ctx.findings.append(Finding(source_id="111", answer="a", evidence="Table 1"))
    _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    final = _final(ctx, monkeypatch)

    head, abstract_part = final.answer.split("## From abstracts (full text not available)")
    assert "Table 1" in head and QUOTE not in head
    assert f'"{QUOTE}"' in abstract_part
    assert "[Creep of 316 SS](https://www.osti.gov/biblio/3729583)" in abstract_part
    assert any(p.get("evidence") == "abstract" for p in final.provenance)
    assert final.status == "completed"


def test_abstract_evidence_alone_stays_no_results_but_is_shown(monkeypatch):
    ctx = _ctx()
    _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    final = _final(ctx, monkeypatch)

    assert final.status == "no_results"
    assert "## From abstracts" in final.answer and QUOTE in final.answer


def test_abstract_evidence_is_not_cached_as_an_answer(monkeypatch):
    cached = []

    class Knowledge:
        async def cache_answer(self, question, answer, sources):
            cached.append(answer)

    ctx = _ctx()
    ctx.knowledge = Knowledge()
    ctx.findings.append(Finding(source_id="111", answer="a", evidence="Table 1"))
    _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    _final(ctx, monkeypatch)

    assert cached and "From abstracts" not in cached[0]


def test_the_orchestrator_is_told_how_to_use_it():
    from research_agent.core import prompts

    prompt = prompts.render_orchestrator_prompt(AgentConfig(litellm_base_url="http://u"))

    assert "record_abstract_evidence(source_id, statement, quote)" in prompt
    assert "never put it in `findings`" in prompt


# --- best-effort estimates ---------------------------------------------------


def _estimate_ctx():
    ctx = _ctx()
    ctx.findings.append(
        Finding(
            source_id="706175",
            match="nearest",
            answer="At 550 °C and 120 MPa the minimum creep rate was 3.2e-9 /s.",
            evidence="Table 4: stress exponent n = 5.2, activation energy Q = 280 kJ/mol.",
        )
    )
    return ctx


def _estimate_args(**overrides):
    values = {
        "quantity": "minimum creep rate of 316 SS at 400 °C and 15 MPa",
        "unit": "/s",
        "method": "Norton power law with Arrhenius temperature dependence, scaled "
        "from the 550 °C datum",
        "assumptions": ["the stress exponent holds down to 15 MPa"],
        "inputs": [
            {"name": "rate0", "value": "3.2e-9", "unit": "/s", "source_id": "706175"},
            {"name": "s0", "value": "120", "unit": "MPa", "source_id": "706175"},
            {"name": "n", "value": "5.2", "source_id": "706175"},
            {"name": "Q", "value": "280", "unit": "kJ/mol", "source_id": "706175"},
        ],
        "formula": "rate0 * (15 / s0) ** n * exp(-Q * 1000 / R * (1 / 673.15 - 1 / 823.15))",
        "low_formula": "rate0 * (15 / s0) ** (n + 1) * exp(-Q * 1000 / R * (1 / 673.15 - 1 / 823.15))",
        "high_formula": "rate0 * (15 / s0) ** (n - 1) * exp(-Q * 1000 / R * (1 / 673.15 - 1 / 823.15))",
    }
    values.update(overrides)
    return values


def _estimate(ctx, **overrides):
    tool = next(t for t in build_tools(ctx) if t.name == "record_estimate")
    return json.loads(asyncio.run(tool.ainvoke(_estimate_args(**overrides))))


def test_a_cited_estimate_is_computed_by_the_code():
    ctx = _estimate_ctx()

    out = _estimate(ctx)

    assert out["ok"] is True
    assert out["low"] <= out["value"] <= out["high"]
    import math

    expected = 3.2e-9 * (15 / 120) ** 5.2 * math.exp(
        -280e3 / 8.314462618 * (1 / 673.15 - 1 / 823.15)
    )
    assert out["value"] == pytest.approx(expected)
    assert ctx.estimates and ctx.findings[0].source_id == "706175"  # findings unchanged


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"inputs": [{"name": "rate0", "value": "9.9e-9", "source_id": "706175"}],
          "formula": "rate0", "low_formula": "rate0", "high_formula": "rate0"},
         "does not appear in the cited evidence"),
        ({"inputs": [{"name": "rate0", "value": "3.2e-9", "source_id": "999"}],
          "formula": "rate0", "low_formula": "rate0", "high_formula": "rate0"},
         "no verified finding or abstract evidence"),
        ({"assumptions": []}, "state at least one assumption"),
        ({"method": ""}, "quantity and method are required"),
        ({"inputs": []}, "needs cited inputs"),
        ({"low_formula": "rate0 * 10"}, "range must contain the estimate"),
        ({"formula": "__import__('os').system('ls')"}, "not allowed in a formula"),
        ({"formula": "rate0.real"}, "not allowed in a formula"),
        ({"formula": "rate0 * T"}, "unknown name 'T'"),
        ({"formula": "rate0 / 0"}, "cannot be evaluated"),
        ({"formula": "rate0 * (15 / s0) ** n", "low_formula": "rate0 * 0.1 * (15 / s0) ** n",
          "high_formula": "rate0 * 10 * (15 / s0) ** n"}, "inputs not used by any formula: Q"),
    ],
)
def test_bad_estimates_are_refused(overrides, error):
    ctx = _estimate_ctx()

    out = _estimate(ctx, **overrides)

    assert out["ok"] is False and error in out["error"]
    assert ctx.estimates == []


def test_estimate_inputs_may_come_from_abstract_evidence():
    ctx = _ctx()
    _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    out = _estimate(
        ctx,
        inputs=[{"name": "rate0", "value": "3.2e-9", "unit": "/s", "source_id": "3729583"}],
        formula="rate0 * 0.01", low_formula="rate0 * 0.001", high_formula="rate0 * 0.1",
    )

    assert out["ok"] is True


def test_estimate_section_is_labelled_and_lists_every_input(monkeypatch):
    ctx = _estimate_ctx()
    _estimate(ctx)

    final = _final(ctx, monkeypatch)

    section = final.answer.split("## Best-effort estimate (not reported by any source)")[1]
    assert "not a measured or reported value" in section
    assert "Norton power law" in section and "the stress exponent holds down to 15 MPa" in section
    for name in ("rate0", "s0", "n", "Q"):
        assert f"`{name}` =" in section
    assert "plausible range" in section


def test_an_estimate_alone_does_not_make_a_run_completed(monkeypatch):
    ctx = _ctx()
    _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)
    _estimate(
        ctx,
        inputs=[{"name": "rate0", "value": "3.2e-9", "source_id": "3729583"}],
        formula="rate0 * 0.01", low_formula="rate0 * 0.001", high_formula="rate0 * 0.1",
    )

    final = _final(ctx, monkeypatch)

    assert final.status == "no_results" and "Best-effort estimate" in final.answer


def test_estimates_are_not_cached_as_an_answer(monkeypatch):
    cached = []

    class Knowledge:
        async def cache_answer(self, question, answer, sources):
            cached.append(answer)

    ctx = _estimate_ctx()
    ctx.knowledge = Knowledge()
    _estimate(ctx)

    _final(ctx, monkeypatch)

    assert cached and "Best-effort estimate" not in cached[0]


def test_the_judge_is_told_how_to_score_labelled_estimates():
    from pathlib import Path

    judge_prompt = Path(__file__).resolve().parents[1].joinpath("evals", "judge_prompt.md")
    text = " ".join(judge_prompt.read_text().split())

    assert "An estimate presented as a reported or measured value is unsupported" in text
    assert "4 = no exact finding, but a clearly labelled best-effort estimate" in text


def test_orchestrator_allows_estimates_only_through_the_tool():
    from research_agent.core import prompts

    prompt = " ".join(
        prompts.render_orchestrator_prompt(AgentConfig(litellm_base_url="http://u")).split()
    )

    assert "anywhere except through `record_estimate` below" in prompt
    assert "If the inputs are not available, do not estimate" in prompt
