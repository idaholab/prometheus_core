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

"""Evidence weaker than a verified finding, kept apart from findings.

``record_abstract_evidence`` keeps a statement from the abstract of a paper
whose full text could not be read. Code checks it against the abstract the
search returned: the quote must appear in it word for word, and every number
in the statement (with its unit, when it has one) must appear in the quote.

``record_estimate`` keeps a best-effort estimate computed from cited values.
Code checks every input against the verified finding or abstract evidence it
cites, evaluates the formula itself (a small arithmetic evaluator, never
``eval``), and recomputes the low/high bounds; the method and assumptions
must be stated.

These never enter ``RunContext.findings``, synthesis, or fact storage; the
final answer shows them in their own sections, after the verified findings.
"""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from typing import Dict, List, Optional

from langchain_core.tools import BaseTool, tool

from research_agent.tools import progress
from research_agent.tools.context import RunContext

MAX_ABSTRACT_EVIDENCE = 8

_NUMBER = r"[-+−]?\d+(?:[.,]\d+)?(?:[eE][-+−]?\d+)?"
_UNIT = r"(?:°\s*C|°C|MPa|GPa|kPa|ksi|dpa|ppm|wt\s*%|at\s*%|%|K|hr|h|s)"
_NUMBER_RE = re.compile(_NUMBER)
_QUANTITY_RE = re.compile(rf"({_NUMBER})\s*({_UNIT})(?![A-Za-z])")


def normalize(text: str) -> str:
    """Case, whitespace, minus signs and the degree sign, for comparison."""
    text = str(text or "").replace("−", "-").replace("º", "°").lower()
    return " ".join(text.split())


def numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMBER_RE.findall(normalize(text))}


def quantities(text: str) -> set[tuple[str, str]]:
    """``{("15", "mpa"), ("400", "°c")}``: numbers with a unit right after."""
    return {
        (n.replace(",", "."), re.sub(r"\s+", "", unit))
        for n, unit in _QUANTITY_RE.findall(normalize(text))
    }


def supported_by(statement: str, source: str) -> Optional[str]:
    """Why ``statement`` states something ``source`` doesn't, or None."""
    missing_numbers = numbers(statement) - numbers(source)
    if missing_numbers:
        return f"numbers not in the cited text: {', '.join(sorted(missing_numbers))}"
    missing = quantities(statement) - quantities(source)
    if missing:
        shown = ", ".join(f"{n} {u}" for n, u in sorted(missing))
        return f"values with these units are not in the cited text: {shown}"
    return None


MAX_ESTIMATES = 3
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {"exp": math.exp, "log": math.log, "log10": math.log10, "sqrt": math.sqrt}
# Physical constants a creep or diffusion estimate may use without citing.
CONSTANTS = {"R": 8.314462618, "k_B": 8.617333262e-5}


class EstimateError(ValueError):
    """The formula is not plain arithmetic over the declared inputs."""


def evaluate(formula: str, values: Dict[str, float]) -> float:
    """Arithmetic over ``values`` and CONSTANTS: + - * / **, parentheses,
    exp/log/log10/sqrt. Anything else (attributes, other calls, subscripts,
    comparisons) is refused, so a formula can't run code."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise EstimateError(f"formula does not parse: {e.msg}") from e
    names = {**CONSTANTS, **values}

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                raise EstimateError("booleans are not numbers")
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise EstimateError(f"unknown name {node.id!r}: declare it as an input")
            return float(names[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](walk(node.operand))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS
            and len(node.args) == 1
            and not node.keywords
        ):
            return _FUNCTIONS[node.func.id](walk(node.args[0]))
        raise EstimateError(f"not allowed in a formula: {type(node).__name__}")

    try:
        result = walk(tree)
    except (ArithmeticError, ValueError) as e:
        if isinstance(e, EstimateError):
            raise
        raise EstimateError(f"formula cannot be evaluated: {e}") from e
    if not math.isfinite(result):
        raise EstimateError("formula result is not a finite number")
    return result


def _parse_number(text: str) -> Optional[float]:
    try:
        return float(str(text).replace("−", "-").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _cited_text(ctx: RunContext, source_id: str) -> Optional[str]:
    """The verified finding's or abstract evidence's text for ``source_id``:
    what an estimate input may be taken from."""
    for finding in ctx.findings:
        if finding.source_id == source_id:
            return " ".join(
                str(part or "") for part in (finding.answer, finding.evidence, finding.excerpt)
            )
    texts = [e["quote"] for e in ctx.abstract_evidence if e["source_id"] == source_id]
    return " ".join(texts) if texts else None


def _check_input(ctx: RunContext, item: dict) -> tuple[str, float, dict]:
    name = str(item.get("name") or "").strip()
    if not _NAME_RE.match(name) or name in _FUNCTIONS or name in CONSTANTS:
        raise EstimateError(f"input name {name!r} must be a short identifier")
    raw = str(item.get("value") or "").strip()
    value = _parse_number(raw)
    if value is None or not math.isfinite(value):
        raise EstimateError(f"input {name}: value {raw!r} is not a number")
    source_id = str(item.get("source_id") or "")
    cited = _cited_text(ctx, source_id)
    if cited is None:
        raise EstimateError(
            f"input {name}: source {source_id!r} has no verified finding or "
            "abstract evidence to cite"
        )
    if normalize(raw).replace(",", ".") not in numbers(cited):
        raise EstimateError(
            f"input {name}: value {raw} does not appear in the cited evidence "
            f"of {source_id}"
        )
    unit = str(item.get("unit") or "").strip()
    return name, value, {
        "name": name, "value": raw, "unit": unit, "source_id": source_id,
        "quantity": str(item.get("quantity") or "").strip(),
    }


def check_estimate(ctx: RunContext, args: dict) -> dict:
    """Validate and evaluate an estimate; returns the stored record."""
    quantity = str(args.get("quantity") or "").strip()
    unit = str(args.get("unit") or "").strip()
    method = str(args.get("method") or "").strip()
    assumptions = [str(a).strip() for a in args.get("assumptions") or [] if str(a).strip()]
    if not quantity or not method:
        raise EstimateError("quantity and method are required")
    if not assumptions:
        raise EstimateError("state at least one assumption")
    inputs = args.get("inputs") or []
    if not inputs:
        raise EstimateError("an estimate needs cited inputs")
    values, cited = {}, []
    for item in inputs:
        name, value, record = _check_input(ctx, dict(item or {}))
        if name in values:
            raise EstimateError(f"input {name} is declared twice")
        values[name] = value
        cited.append(record)

    formulas = {
        key: str(args.get(key) or "").strip()
        for key in ("formula", "low_formula", "high_formula")
    }
    if not all(formulas.values()):
        raise EstimateError("formula, low_formula and high_formula are all required")
    results = {key: evaluate(f, values) for key, f in formulas.items()}
    low, value, high = results["low_formula"], results["formula"], results["high_formula"]
    if not low <= value <= high:
        raise EstimateError(
            f"the range must contain the estimate: low {low:.4g}, estimate "
            f"{value:.4g}, high {high:.4g}"
        )
    used = {n.id for f in formulas.values() for n in ast.walk(ast.parse(f, mode="eval"))
            if isinstance(n, ast.Name)} - set(CONSTANTS) - set(_FUNCTIONS)
    unused = sorted(set(values) - used)
    if unused:
        raise EstimateError(f"inputs not used by any formula: {', '.join(unused)}")
    return {
        "quantity": quantity, "unit": unit, "method": method,
        "assumptions": assumptions, "inputs": cited, "formulas": formulas,
        "value": value, "low": low, "high": high,
    }


def _full_text_unavailable(ctx: RunContext, source_id: str, hit: dict) -> bool:
    if source_id in ctx.download_failures or source_id in ctx.parse_failures:
        return True
    is_osti = source_id.isdigit() or str(hit.get("origin") or "osti") == "osti"
    return not is_osti and not hit.get("oa_pdf_url")


def _abstract_of(hit: dict) -> str:
    # OSTI hits keep the raw API record, whose abstract is "description".
    return str(hit.get("abstract") or hit.get("description") or "")


def build_evidence_tools(ctx: RunContext) -> List[BaseTool]:
    @tool
    async def record_abstract_evidence(source_id: str, statement: str, quote: str) -> str:
        """Keep a statement from the ABSTRACT of a search result whose full text
        could not be read (its download or parse failed, or it has no
        downloadable PDF). ``quote`` must be copied word for word from that
        result's abstract, and every number in ``statement`` must appear in
        ``quote``. This is weaker than a finding from analyze_paper: use it only
        for papers you could not read, never instead of reading one."""
        source_id = str(source_id)
        hit = ctx.search_hits.get(source_id)

        def refuse(reason: str) -> str:
            return json.dumps({"ok": False, "source_id": source_id, "error": reason})

        if hit is None:
            return refuse("unknown source_id: use an id a search tool returned")
        abstract = _abstract_of(hit)
        if not abstract.strip():
            return refuse("this search result has no abstract")
        if any(f.source_id == source_id for f in ctx.findings):
            return refuse("this paper already has a verified finding; use that")
        if not _full_text_unavailable(ctx, source_id, hit):
            return refuse(
                "this paper's full text may be readable: download, parse and "
                "analyze it first; abstract evidence is only for papers that "
                "could not be read"
            )
        if not statement.strip() or not quote.strip():
            return refuse("statement and quote are both required")
        if normalize(quote) not in normalize(abstract):
            return refuse("the quote is not word for word in this paper's abstract")
        unsupported = supported_by(statement, quote)
        if unsupported:
            return refuse(f"the statement says more than the quote ({unsupported})")
        if len(ctx.abstract_evidence) >= MAX_ABSTRACT_EVIDENCE:
            return refuse(f"abstract evidence limit reached ({MAX_ABSTRACT_EVIDENCE})")

        ctx.abstract_evidence.append(
            {
                "source_id": source_id,
                "statement": " ".join(statement.split()),
                "quote": " ".join(quote.split()),
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
            }
        )
        progress.emit(
            f"Kept abstract evidence from {source_id} (full text unavailable)",
            {"source_id": source_id},
        )
        return json.dumps({"ok": True, "source_id": source_id})

    @tool
    async def record_estimate(
        quantity: str,
        unit: str,
        method: str,
        assumptions: List[str],
        inputs: List[dict],
        formula: str,
        low_formula: str,
        high_formula: str,
    ) -> str:
        """Record a best-effort ESTIMATE of the asked quantity, only when no
        source reports it at the asked conditions. Every input is a value
        copied from a verified finding or abstract evidence:
        ``{"name": "n", "value": "5.2", "unit": "", "quantity": "stress exponent",
        "source_id": "<id of that finding>"}``. ``formula`` computes the estimate
        from the input names (+ - * / **, exp, log, log10, sqrt; R and k_B are
        available as constants); ``low_formula`` and ``high_formula`` compute the
        bounds of a plausible range. State the method (e.g. "Norton power law
        with Arrhenius temperature dependence, scaled from the 550 C datum") and
        every assumption (e.g. "the stress exponent holds down to 15 MPa").
        The code checks every input against its citation and computes the
        numbers itself; the answer labels the result as an estimate."""
        args = {
            "quantity": quantity, "unit": unit, "method": method,
            "assumptions": assumptions, "inputs": inputs, "formula": formula,
            "low_formula": low_formula, "high_formula": high_formula,
        }
        try:
            if len(ctx.estimates) >= MAX_ESTIMATES:
                raise EstimateError(f"estimate limit reached ({MAX_ESTIMATES})")
            record = check_estimate(ctx, args)
        except EstimateError as e:
            return json.dumps({"ok": False, "error": str(e)})
        ctx.estimates.append(record)
        progress.emit(
            f"Recorded estimate of {quantity}: {record['value']:.3g} {unit} "
            f"(range {record['low']:.3g}-{record['high']:.3g})",
        )
        return json.dumps(
            {"ok": True, "value": record["value"], "low": record["low"], "high": record["high"]}
        )

    return [record_abstract_evidence, record_estimate]
