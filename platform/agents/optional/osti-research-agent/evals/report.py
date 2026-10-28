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

"""Human-readable views of an evaluation report: a terminal summary and a
Markdown file. Pure functions over the ``report.json`` dict that ``run.py``
writes, so they're unit-tested offline and can re-render an old report
(``python -m evals report evals/report.json``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# A question is a failure when any of these is false or under 1.0, or when a
# judge score is under JUDGE_PASS_SCORE. Kept equal to evals.judge.PASS_SCORE;
# not imported so this module stays standard-library only (osti-eval-report
# runs it with a bare python3).
_RATE_CHECKS = ("citation_link_rate", "source_hit_rate", "fact_match")
JUDGE_PASS_SCORE = 4
_JUDGE_SCORES = (
    ("judge_groundedness", "groundedness"),
    ("judge_completeness", "completeness"),
    ("judge_reference_agreement", "reference agreement"),
)


def failures(record: Dict[str, Any]) -> List[str]:
    """Why one question failed, as short phrases; empty when it passed."""
    reasons = []
    if not record.get("status_match"):
        reasons.append(f"status {record.get('status')!r} not the expected one")
    if not record.get("provenance_ok"):
        reasons.append("completed with no sources")
    for key in _RATE_CHECKS:
        value = record.get(key)
        if isinstance(value, (int, float)) and value < 1.0:
            reasons.append(f"{key} {value:.2f}")
    for key, label in _JUDGE_SCORES:
        value = record.get(key)
        if isinstance(value, int) and value < JUDGE_PASS_SCORE:
            reasons.append(f"judge {label} {value}/5")
    # An answer the judge could not score has not passed the judge.
    if record.get("judge_error"):
        reasons.append("not judged")
    return reasons


def _quoted(values: List[Any]) -> str:
    return ", ".join(f'"{v}"' for v in values)


def explained_failures(record: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Each failure as ``(short reason, what it means for this question)``.

    The explanation uses what the record knows: the expected status, the
    facts or sources missing from the answer, and the judge's own rationale
    for a low judge score."""
    reasons = []
    for reason in failures(record):
        if reason.startswith("status "):
            expected = record.get("expect_status")
            detail = (
                f"expected {expected!r}, the agent returned {record.get('status')!r}"
                if expected
                else "the status did not match the question's expectation"
            )
            if record.get("status") == "no_results":
                detail += "; it found no verified evidence"
        elif reason == "completed with no sources":
            detail = "the answer reports results but cites no source"
        elif reason.startswith("citation_link_rate"):
            detail = "some \"Paper N\" citations in the answer are not links to a source"
        elif reason.startswith("source_hit_rate"):
            missing = record.get("missing_sources") or []
            detail = (
                f"expected sources not cited: {_quoted(missing)}"
                if missing
                else "some expected sources are not in the answer's provenance"
            )
        elif reason.startswith("fact_match"):
            missing = record.get("missing_facts") or []
            detail = (
                f"expected text not in the answer: {_quoted(missing)}"
                if missing
                else "some expected facts are not in the answer"
            )
        elif reason == "not judged":
            detail = (
                "the judge's reply could not be scored "
                f"({record.get('judge_error')}); rerun this question with --id"
            )
        elif reason.startswith("judge "):
            detail = str(record.get("judge_rationale") or "").strip() or (
                "the judge gave no rationale"
            )
        else:
            detail = ""
        reasons.append((reason, detail))
    return reasons


def _explanation_text(record: Dict[str, Any]) -> str:
    """One cell: each reason with its explanation; the judge's rationale is
    shown once even when several judge scores failed."""
    parts, judge_shown = [], False
    for reason, detail in explained_failures(record):
        if reason.startswith("judge "):
            if judge_shown:
                parts.append(f"{reason}")
                continue
            judge_shown = True
        parts.append(f"{reason}: {detail}" if detail else reason)
    return "; ".join(parts)


def _median(values: List[Any]) -> Optional[float]:
    clean = sorted(v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not clean:
        return None
    middle = len(clean) // 2
    return float(clean[middle]) if len(clean) % 2 else (clean[middle - 1] + clean[middle]) / 2


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _duration(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return "-"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def _summary_rows(report: Dict[str, Any]) -> List[List[str]]:
    rows = []
    for engine, agg in report.get("aggregate", {}).items():
        n = agg.get("n", 0)
        records = [r for r in report.get("records", []) if r.get("engine") == engine]
        passed = sum(1 for r in records if not failures(r))
        rows.append(
            [
                engine,
                f"{passed}/{n}",
                f"{agg.get('status_match', 0)}/{n}",
                f"{agg.get('provenance_ok', 0)}/{n}",
                _fmt(agg.get("median_citation_link_rate")),
                _fmt(agg.get("median_source_hit_rate")),
                _fmt(agg.get("median_fact_match")),
                *[_fmt(_median([r.get(key) for r in records])) for key, _ in _JUDGE_SCORES],
                _duration(agg.get("median_wall_s")),
                _duration(agg.get("p90_wall_s")),
            ]
        )
    return rows


_SUMMARY_HEADER = [
    "engine",
    "passed",
    "status",
    "sources",
    "cite links",
    "source hit",
    "fact match",
    "ground",
    "complete",
    "ref agree",
    "median time",
    "p90 time",
]


def _table(header: List[str], rows: List[List[str]]) -> str:
    widths = [max(len(str(c)) for c in col) for col in zip(header, *rows)]
    line = "  ".join(h.ljust(w) for h, w in zip(header, widths))
    rule = "  ".join("-" * w for w in widths)
    body = ["  ".join(str(c).ljust(w) for c, w in zip(row, widths)) for row in rows]
    return "\n".join([line, rule, *body])


def _failed_records(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [r for r in report.get("records", []) if failures(r)]


def terminal_summary(report: Dict[str, Any], *, max_failures: int = 20) -> str:
    """A compact plain-text summary for the end of a run."""
    lines = [
        f"OSTI evaluation: {report.get('questions', 0)} question(s), "
        f"engines: {', '.join(report.get('engines', []))}",
        "",
        _table(_SUMMARY_HEADER, _summary_rows(report)),
    ]
    failed = _failed_records(report)
    if failed:
        lines.extend(["", f"Failed ({len(failed)}):"])
        for record in failed[:max_failures]:
            lines.append(
                f"  [{record.get('engine')}] {record.get('id')}: "
                + "; ".join(failures(record))
            )
        if len(failed) > max_failures:
            lines.append(f"  ... and {len(failed) - max_failures} more (see report.md)")
    else:
        lines.extend(["", "Every question passed."])
    judge_errors = [r for r in report.get("records", []) if r.get("judge_error")]
    if judge_errors:
        lines.extend(
            ["", f"Judge errors ({len(judge_errors)}): those questions are unjudged "
             "and count as failed."]
        )
    lines.extend(["", _CAVEAT])
    return "\n".join(lines)


_CAVEAT = (
    "Judge scores are 1-5 from a model on the verifier route (pass is "
    f"{JUDGE_PASS_SCORE}+); still read 5 transcripts by hand (evals/README.md)."
)


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(header: List[str], rows: List[List[Any]]) -> str:
    out = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    out.extend("| " + " | ".join(_md_cell(c) for c in row) + " |" for row in rows)
    return "\n".join(out)


def markdown_report(
    report: Dict[str, Any],
    *,
    transcripts_dir: Optional[str] = None,
    questions: Optional[Dict[str, str]] = None,
) -> str:
    """The full report as Markdown: summary, failures, and every question.

    ``transcripts_dir`` (relative to where report.md is written) turns each
    question id into a link to its ``result.json``; ``questions`` maps ids to
    question text for the per-question table."""
    questions = questions or {}
    sections = [
        "# OSTI research agent evaluation",
        "",
        f"- Questions: {report.get('questions', 0)}",
        f"- Engines: {', '.join(report.get('engines', []))}",
    ]
    if report.get("started_at"):
        sections.append(f"- Started: {report['started_at']}")
    if report.get("redis_db_base") is not None:
        sections.append(f"- Redis databases from: {report['redis_db_base']}")
    sections.extend(["", "## Summary", "", _md_table(_SUMMARY_HEADER, _summary_rows(report))])

    def qid_cell(record: Dict[str, Any]) -> str:
        qid = str(record.get("id"))
        if transcripts_dir:
            return f"[{qid}]({transcripts_dir}/{record.get('engine')}/{qid}/result.json)"
        return qid

    failed = _failed_records(report)
    sections.extend(["", f"## Failures ({len(failed)})", ""])
    if failed:
        sections.append(
            _md_table(
                ["engine", "question", "why"],
                [[r.get("engine"), qid_cell(r), _explanation_text(r)] for r in failed],
            )
        )
    else:
        sections.append("Every question passed the automatic checks.")

    sections.extend(["", "## All questions", ""])
    sections.append(
        _md_table(
            [
                "engine",
                "question",
                "status",
                "pass",
                "cite links",
                "source hit",
                "fact match",
                "ground",
                "complete",
                "ref agree",
                "papers",
                "time",
                "text",
            ],
            [
                [
                    r.get("engine"),
                    qid_cell(r),
                    r.get("status"),
                    "yes" if not failures(r) else "no",
                    _fmt(r.get("citation_link_rate")),
                    _fmt(r.get("source_hit_rate")),
                    _fmt(r.get("fact_match")),
                    *[_fmt(r.get(key)) for key, _ in _JUDGE_SCORES],
                    r.get("papers_analyzed", 0),
                    _duration(r.get("wall_s")),
                    questions.get(str(r.get("id")), ""),
                ]
                for r in report.get("records", [])
            ],
        )
    )
    judged = [
        r
        for r in report.get("records", [])
        if r.get("judge_rationale") or r.get("judge_error")
    ]
    if judged:
        sections.extend(["", "## Judge notes", ""])
        sections.append(
            _md_table(
                ["engine", "question", "judge says"],
                [
                    [
                        r.get("engine"),
                        qid_cell(r),
                        r.get("judge_rationale") or f"judge error: {r.get('judge_error')}",
                    ]
                    for r in judged
                ],
            )
        )
    sections.extend(
        [
            "",
            "## Not covered here",
            "",
            "Judge scores (ground = groundedness, complete = completeness, ref agree = "
            "agreement with the question's reviewer notes) are 1-5 from a model on "
            f"the verifier route; a question needs {JUDGE_PASS_SCORE}+ on each to "
            "pass. A model can misjudge, so still read 5 transcripts by hand; cost "
            "comes from LiteLLM's spend logs. See `evals/README.md`.",
        ]
    )
    return "\n".join(sections) + "\n"
