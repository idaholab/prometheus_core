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
"""Evidence tool refusals: malformed formulas, inputs and evidence limits."""

import asyncio
import json

import pytest
from test_abstract_evidence import QUOTE, _ctx, _estimate, _estimate_ctx, _record

from research_agent.tools import evidence


@pytest.mark.parametrize(
    "formula, error",
    [
        ("rate0 *", "formula does not parse"),
        ("rate0 * True", "booleans are not numbers"),
        ("1e308 * 10", "not a finite number"),
    ],
)
def test_evaluate_refuses_bad_formulas(formula, error):
    with pytest.raises(evidence.EstimateError, match=error):
        evidence.evaluate(formula, {"rate0": 1.0})


def test_parse_number_handles_commas_minus_signs_and_garbage():
    assert evidence._parse_number("−3,5") == -3.5
    assert evidence._parse_number("about five") is None
    assert evidence._parse_number(None) is None


def _one_input(**item):
    base = {"name": "rate0", "value": "3.2e-9", "source_id": "706175"}
    base.update(item)
    return {"inputs": [base], "formula": "rate0", "low_formula": "rate0",
            "high_formula": "rate0"}


@pytest.mark.parametrize(
    "overrides, error",
    [
        (_one_input(name="exp"), "must be a short identifier"),
        (_one_input(name="1bad"), "must be a short identifier"),
        (_one_input(value="lots"), "is not a number"),
        (_one_input(value="inf"), "is not a number"),
        ({"inputs": [{"name": "n", "value": "5.2", "source_id": "706175"},
                     {"name": "n", "value": "5.2", "source_id": "706175"}],
          "formula": "n", "low_formula": "n", "high_formula": "n"},
         "input n is declared twice"),
        ({**_one_input(), "high_formula": " "}, "are all required"),
    ],
)
def test_bad_estimate_inputs_are_refused(overrides, error):
    ctx = _estimate_ctx()

    out = _estimate(ctx, **overrides)

    assert out["ok"] is False and error in out["error"]
    assert ctx.estimates == []


def test_estimates_stop_at_the_limit():
    ctx = _estimate_ctx()
    for _ in range(evidence.MAX_ESTIMATES):
        assert _estimate(ctx)["ok"] is True

    out = _estimate(ctx)

    assert out == {"ok": False, "error": f"estimate limit reached ({evidence.MAX_ESTIMATES})"}
    assert len(ctx.estimates) == evidence.MAX_ESTIMATES


def test_a_search_result_without_an_abstract_is_refused():
    ctx = _ctx()
    ctx.search_hits["3729583"]["description"] = "  "

    out = _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    assert out["ok"] is False and "has no abstract" in out["error"]


def test_abstract_evidence_stops_at_the_limit():
    ctx = _ctx()
    ctx.abstract_evidence.extend(
        {"source_id": "x", "statement": "s", "quote": "q", "title": "", "url": ""}
        for _ in range(evidence.MAX_ABSTRACT_EVIDENCE)
    )

    out = _record(ctx, statement="Minimum creep rate of 3.2e-9 /s", quote=QUOTE)

    assert out["ok"] is False and "abstract evidence limit reached" in out["error"]
    assert len(ctx.abstract_evidence) == evidence.MAX_ABSTRACT_EVIDENCE


def test_record_tools_return_json_strings():
    tools = evidence.build_evidence_tools(_ctx())
    assert [t.name for t in tools] == ["record_abstract_evidence", "record_estimate"]
    out = asyncio.run(tools[0].ainvoke({"source_id": "nope", "statement": "s", "quote": "q"}))
    assert json.loads(out)["error"].startswith("unknown source_id")
