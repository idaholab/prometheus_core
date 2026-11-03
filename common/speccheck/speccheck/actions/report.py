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

"""`speccheck report`: the markdown report of where and how each requirement is proven.

See plan/design.md, "Report". A table of specs, then per spec its Purpose and a status table, then
a section per requirement and a subsection per claiming test or CI job. It fails only on bad usage
or a bad config; a bad results file shows up as a problem. Everything from a results file, a spec
or `--job-names` is written so it can only be text, and capped. The step summary is not this
report's: `lint`, `check` and `verify` write it with `--summary`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from speccheck import ci, evidence, jsonout
from speccheck.actions import _common
from speccheck.claims import MAX_HOW
from speccheck.context import Context
from speccheck.evidence import Evaluation, Evidence, Status
from speccheck.markdown import anchor, code, prose, safe_url, source_url
from speccheck.specs import UNTESTED, plain

NAME = "report"
"""The command name."""
HELP = "Write the full markdown report (--output FILE) or --json"
"""The one-line help."""
SECTION = "ci"
"""The `--help` section."""
ORDER = 10
"""Its place in the section."""

MAX_EVIDENCE = 50
"""The most results listed for one claim; the rest are counted."""
MAX_PROBLEM = 500
"""The longest Problems line, as long as a summary entry, so a test ID of the longest allowed length keeps its fix."""
ICONS = {
    evidence.PASSED: "✅",
    evidence.FAILED: "❌",
    evidence.UNCLAIMED: "❌",
    evidence.NOT_RUN: "⏸",
    evidence.CLAIMED: "☑",
    evidence.PLANNED: "🗓",
    evidence.UNTESTED_STATUS: "⚠",
    evidence.RETIRED: "—",
}
"""One mark per status, beside its name."""
OUTCOMES = ("failed", "error", "xpassed", "xfailed", "skipped", "deselected", "collected", "passed")
"""Outcomes worst first, the order of a claim's result lines."""
OUTCOME_ICONS = {"passed": "✅", "collected": "☑"}
"""A mark per outcome; any other outcome is a failure, ❌."""


@dataclass(frozen=True)
class Links:
    """Where links may point: this run's repository, and its files at this run's commit."""

    repository: str = ""
    """`<server>/<owner>/<repo>`, for job and run links; "" outside CI."""
    files: str = ""
    """`<server>/<owner>/<repo>/blob/<sha>`, for spec and test lines; "" outside CI."""
    root: Path | None = None
    """The repository's root folder, to give spec files' paths from it."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The results files, the scope, the job names, and where to write."""
    _common.add_inputs(parser)
    _common.add_scope(parser)
    _common.add_job_names(parser)
    parser.add_argument("--output", metavar="FILE", help="Write the full report here (default: stdout)")


def _heading(status: Status) -> str:
    """A requirement's section heading: `SPC-REQ-001-01 ✅ passed`."""
    return f"{status.requirement.id} {ICONS[status.status]} {status.status}"


def _order(status: Status) -> tuple[int, int]:
    """Sort key: statuses that need attention first, then spec order."""
    return (evidence.STATUSES.index(status.status), status.requirement.line)


def _counts(statuses: list[Status]) -> str:
    """ "❌ 1 failed, ✅ 8 passed": each status the list has, worst first."""
    found = {s: sum(x.status == s for x in statuses) for s in evidence.STATUSES}
    return ", ".join(f"{ICONS[s]} {n} {s}" for s, n in found.items() if n)


def _spec_heading(number: str, title: str) -> str:
    """A spec's section heading: `001 Spec format`."""
    return f"{number} {title}".rstrip()


def _specs_table(by_spec: dict[str, list[Status]]) -> list[str]:
    """The table of specs: a link to each, its number of requirements, and its counts."""
    lines = ["## Specs", "", "| Spec | Requirements | Status |", "|---|--:|---|"]
    for number, statuses in by_spec.items():
        heading = _spec_heading(number, statuses[0].requirement.spec.title)
        lines.append(f"| [{prose(heading)}](#{anchor(heading)}) | {len(statuses)} | {_counts(statuses)} |")
    return [*lines, ""]


def _result_line(item: Evidence, links: Links) -> str:
    """One result: its outcome and the job that produced it, linked."""
    data = _common.evidence_json(item)
    url = safe_url(data["url"], links.repository)
    name = prose(item.where)
    mark = OUTCOME_ICONS.get(data["outcome"], "❌")
    return f"- {mark} {prose(data['outcome'])} in {f'[{name}]({url})' if url else name}"


def _claimant_heading(item: Evidence, links: Links) -> str:
    """A claim's heading: the test's name linking to its line, and its file; or the CI job's name."""
    result = item.result
    if result.kind == "ci":
        return f"#### Job {code(result.test, in_table=False)}"
    name = result.test.split("::", 1)[1] if "::" in result.test else result.test
    root = item.source.root
    # `file` is relative to pytest's root; `root` says where that is in the repository (None: unknown)
    path = result.file if root in (None, ".") or not result.file else f"{root}/{result.file}"
    url = source_url(links.files, path, result.line) if root is not None else ""
    shown = f"[{code(name, 150, in_table=False)}]({url})" if url else code(name, 150, in_table=False)
    return f"#### Test {shown}" + (f" in {code(path, 150, in_table=False)}" if path else "")


def _claims(status: Status, links: Links) -> list[str]:
    """One subsection per claiming test or job: its heading, how it proves the requirement, its results."""
    by_claimant: dict[tuple[str, str, str], list[Evidence]] = {}
    for item in status.evidence:
        by_claimant.setdefault((item.result.kind, item.result.test, item.how), []).append(item)
    lines: list[str] = []
    for (_, _, how), items in by_claimant.items():
        lines += [_claimant_heading(items[0], links), ""]
        if how:
            lines += [f"**How:** {prose(how, MAX_HOW)}", ""]
        ordered = sorted(items, key=lambda i: (OUTCOMES.index(i.result.outcome), i.where))
        lines += [_result_line(item, links) for item in ordered[:MAX_EVIDENCE]]
        if len(ordered) > MAX_EVIDENCE:
            lines.append(f"- and {len(ordered) - MAX_EVIDENCE} more")
        lines.append("")
    return lines


def _requirement(status: Status, links: Links) -> list[str]:
    """One requirement's section: heading, full text, its spec line, then its claims or what it lacks."""
    requirement = status.requirement
    lines = [f"### {_heading(status)}", "", f"> {prose(requirement.text, None, line_start=True)}", ""]
    path = ci.from_root(requirement.spec.path, links.root)
    url = source_url(links.files, path, requirement.line)
    if url:
        lines += [f"In [{code(f'{path}:{requirement.line}', in_table=False)}]({url})", ""]
    if status.evidence:
        lines += _claims(status, links)
    elif status.waiting_on:
        lines += [f"Waiting on: {', '.join(prose(name) for name in status.waiting_on)}", ""]
    elif status.status == evidence.UNCLAIMED:
        marker = f'@pytest.mark.covers("{requirement.id}", "<how it proves it>")'
        lines += [f"Not claimed: add `{marker}` to a test that proves it, or mark it `{UNTESTED}`.", ""]
    return lines


def _spec(number: str, statuses: list[Status], links: Links) -> list[str]:
    """One spec's section: its title, Purpose and status table, then a section per requirement."""
    spec = statuses[0].requirement.spec
    lines = [f"## {prose(_spec_heading(number, spec.title))}", ""]
    if spec.purpose:
        lines += [prose(spec.purpose, 2000, line_start=True), ""]
    lines += ["| Requirement | Status |", "|---|---|"]
    for status in sorted(statuses, key=_order):
        heading = _heading(status)
        lines.append(f"| [{status.requirement.id}](#{anchor(heading)}) | {ICONS[status.status]} {status.status} |")
    lines.append("")
    for status in statuses:
        lines += _requirement(status, links)
    return lines


def _inputs(evaluation: Evaluation, base: str) -> list[str]:
    """The lines saying what the report was built from: commits, runs and producers."""
    commits = sorted({(f.ci or {}).get("sha") or "" for f in evaluation.files} - {""})
    runs = sorted({safe_url((f.ci or {}).get("run_url"), base, job=False) for f in evaluation.files} - {""})
    run_links = [f"[{prose(run.rsplit('/runs/', 1)[1])}]({run})" for run in runs]
    lines = [
        f"- Commit: {', '.join(prose(c[:12]) for c in commits) or 'unknown (not run in CI)'}",
        f"- Runs: {', '.join(run_links) or 'none'}",
        f"- Producers reported: {', '.join(prose(p) for p in evaluation.reported) or 'none'}",
    ]
    if evaluation.missing:
        lines.append(f"- Producers missing: {', '.join(prose(p) for p in evaluation.missing)}")
    return lines


def full(title: str, evaluation: Evaluation, links: Links | None = None) -> str:
    """The whole report: counts, problems, the specs table, a section per spec, and the inputs."""
    links = links or Links()
    counts = evaluation.counts()
    lines = [f"# {prose(title)}", "", evidence.summary_line(counts), ""]
    lines += [" · ".join(f"{ICONS[s]} {s}: {n}" for s, n in counts.items() if n), ""]
    if evaluation.problems:
        lines += [f"## Problems ({len(evaluation.problems)})", ""]
        lines += [f"- {code(str(p), MAX_PROBLEM, in_table=False)}" for p in evaluation.problems]
        lines.append("")
    by_spec: dict[str, list[Status]] = {}
    for status in evaluation.statuses:
        by_spec.setdefault(status.requirement.spec.number, []).append(status)
    lines += _specs_table(by_spec)
    for number, statuses in by_spec.items():
        lines += _spec(number, statuses, links)
    lines += ["## Inputs", "", *_inputs(evaluation, links.repository), ""]
    return "\n".join(lines)


def links_for(ctx: Context) -> Links:
    """The links this run allows: none outside CI."""
    return Links(
        repository=ci.repository_url(ctx.env),
        files=ci.commit_url(ctx.env),
        root=ci.repository_root(ctx.cwd, ctx.env),
    )


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Write the report; exit 0 unless the usage or config is bad."""
    evaluation = _common.evaluate(ctx, args, runtime=True)
    title = ctx.config().title
    links = links_for(ctx)
    if args.output:
        _write(ctx, args.output, full(title, evaluation, links))
    if ctx.output.json_mode:
        body = jsonout.envelope(
            NAME,
            True,
            evaluation.problems,
            title=title,
            counts=evaluation.counts(),
            requirements=_common.statuses_json(evaluation, links.root),
            producers={"reported": evaluation.reported, "missing": evaluation.missing},
        )
        jsonout.emit(body, ctx.output.out)
    elif not args.output:
        # Unlike the file, stdout may be a CI log, where code spans keep a test name as written
        ctx.output.out.write("".join(plain(line) + "\n" for line in full(title, evaluation, links).splitlines()))
    else:
        ctx.output.summary(NAME, evidence.summary_line(evaluation.counts()), 0)
    return jsonout.EXIT_OK


def _write(ctx: Context, name: str, text: str) -> None:
    """Write a file named on the command line, making its folder."""
    path = Path(name) if Path(name).is_absolute() else ctx.cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # The reader refuses lone surrogates; `replace` keeps any that slip past from losing the report
    with path.open("w", encoding="utf-8", errors="replace") as stream:
        stream.write(text)
