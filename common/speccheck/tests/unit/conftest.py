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

"""Builders for the unit tests: specs, a config, results and a Context, all in memory.

A unit test builds what the module under test takes and calls it. Nothing here reads a spec
folder or a config file, so a bug in `specs.py` or `config.py` fails only their own tests.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
from typing import Any

from speccheck import config, results, specs
from speccheck.claims import Claim
from speccheck.context import Context
from speccheck.output import Output

ROOT = Path("/repo")
"""Where the in-memory specs and config pretend to live; paths in messages are relative to it."""


def make_spec(number: str = "001", *, title: str = "Thing") -> specs.Spec:
    """A spec with no requirements yet, at `specs/<number>-thing.md` under ROOT."""
    return specs.Spec(path=ROOT / "specs" / f"{number}-thing.md", number=number, title=title)


def make_requirement(
    spec: specs.Spec, text: str = "It.", *, index: int | None = None, line: int = 0
) -> specs.Requirement:
    """A requirement `T-REQ-<number>-<index>` added to `spec`; an `(unimplemented: ...)` suffix on `text` gives its reason."""
    index = len(spec.requirements) + 1 if index is None else index
    text, reason = specs.split_suffix(text)
    requirement = specs.Requirement(
        id=f"T-REQ-{spec.number}-{index:02}", spec=spec, line=line or 6 + index, text=text, reason=reason
    )
    spec.requirements.append(requirement)
    return requirement


def make_specs(*texts: str, prefix: str = "T", spec: specs.Spec | None = None) -> specs.SpecSet:
    """A spec set of one spec (`spec`, or a fresh 001) with one requirement per text."""
    spec = spec or make_spec()
    for text in texts:
        make_requirement(spec, text)
    return spec_set(spec, prefix=prefix)


def spec_set(*all_specs: specs.Spec, prefix: str = "T", problems: list[specs.Problem] | None = None) -> specs.SpecSet:
    """A spec set of the given specs, their requirements by ID."""
    requirements = {r.id: r for s in all_specs for r in s.requirements}
    return specs.SpecSet(
        specs=list(all_specs), requirements=requirements, problems=list(problems or []), syntax=specs.Syntax(prefix)
    )


def producer(
    name: str = "unit", *, may_claim: tuple[str, ...] | None = None, workflows: tuple[str, ...] = ("ci",)
) -> config.Producer:
    """A test producer; `may_claim` limits the specs it may claim (None: all)."""
    return config.Producer(name=name, specs=may_claim, workflows=workflows)


def how(test: str, id_: str) -> str:
    """The explanation a helper gives a claim: unique to its test (or job) and ID."""
    return f"{test} proves {id_}"


def ci_job(name: str, *covers: str, workflows: tuple[str, ...] = ("ci",)) -> config.Producer:
    """A `[ci.<name>]` job claiming `covers`, each with its own explanation."""
    claims = tuple(Claim(id_, how(name, id_)) for id_ in covers)
    return config.Producer(name=name, specs=None, workflows=workflows, claims=claims, ci_job=True)


def make_config(*producers: config.Producer, prefix: str = "T", title: str = "speccheck requirements") -> config.Config:
    """A config at ROOT/speccheck.toml with the given producers."""
    return config.Config(
        path=ROOT / "speccheck.toml",
        specs_dir=ROOT / "specs",
        prefix=prefix,
        producers={p.name: p for p in producers},
        title=title,
    )


def results_file(
    producer_name: str, *claims: tuple[str, str], ci: dict[str, Any] | None = None, kind: str = "test"
) -> results.ResultsFile:
    """A results file of `(id, outcome)` claims, one test `tests/test_x.py::test_<n>` each, on line n."""
    return results.ResultsFile(
        producer=producer_name,
        ci=ci,
        source=f"{producer_name}.jsonl",
        results=[
            results.Result(
                test=f"tests/test_x.py::test_{n}" if kind == "test" else producer_name,
                covers=[Claim(id_, how(f"tests/test_x.py::test_{n}" if kind == "test" else producer_name, id_))],
                outcome=outcome,
                file="tests/test_x.py" if kind == "test" else "",
                line=n if kind == "test" else 0,
                kind=kind,
            )
            for n, (id_, outcome) in enumerate(claims, 1)
        ],
    )


def make_ctx(
    cwd: Path = ROOT,
    *,
    loaded: config.Config | None = None,
    specs_set: specs.SpecSet | None = None,
    env: dict[str, str] | None = None,
    **output: bool,
) -> Context:
    """A Context on string streams, with its config and spec set already in hand (nothing is read from disk).

    `output` sets the Output's `json_mode`, `quiet` and `verbose`.
    """
    ctx = Context(cwd=cwd, output=Output(out=io.StringIO(), err=io.StringIO(), **output), env=env or {})
    ctx._config = loaded or make_config(producer())
    if specs_set is not None:
        ctx.specs = lambda: specs_set  # type: ignore[method-assign]
    return ctx


def out(ctx: Context) -> str:
    """What the action printed on stdout."""
    return ctx.output.out.getvalue()


def err(ctx: Context) -> str:
    """What the action printed on stderr."""
    return ctx.output.err.getvalue()


def namespace(**values: Any) -> argparse.Namespace:
    """Parsed arguments for an action, with the defaults its parser would give."""
    defaults: dict[str, Any] = {
        "inputs": [],
        "complete": False,
        "workflow": None,
        "output": None,
        "summary": None,
        "report_url": None,
        "job_names": None,
    }
    return argparse.Namespace(**{**defaults, **values})
