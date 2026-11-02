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

"""`speccheck record`: a CI job's results file, from its `[ci.<job>]` entry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from speccheck import __version__, results
from speccheck.actions import record
from speccheck.config import ConfigError
from tests.unit.conftest import ci_job, make_config, make_ctx, namespace, out, producer

FAKE_CI = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "o/r",
    "GITHUB_JOB": "publish",
    "GITHUB_RUN_ID": "11",
    "GITHUB_RUN_ATTEMPT": "1",
    "SPECCHECK_JOB_ID": "22",
}
"""A fake GitHub Actions job named `publish`."""
CONFIG = make_config(producer("unit"), ci_job("publish", "T-REQ-001-01", "T-REQ-001-02"))
"""A config with one test producer and one CI job."""


def run(tmp_path: Path, env: dict[str, str] | None = None, **args) -> tuple[int, str]:
    """Run `record` in `tmp_path`; the exit code and stdout."""
    ctx = make_ctx(tmp_path, loaded=CONFIG, env=env, json_mode=args.pop("json_mode", False))
    code = record.run(ctx, namespace(job=args.pop("job", None), **args))
    return code, out(ctx)


def test_the_arguments():
    """`--job` and `--output`, both optional."""
    parser = argparse.ArgumentParser()
    record.add_arguments(parser)
    assert vars(parser.parse_args([])) == {"job": None, "output": None}


def test_in_a_ci_job(tmp_path: Path):
    """One passed `ci` result for the job's IDs, with the CI context and the version."""
    code, text = run(tmp_path, FAKE_CI)
    assert code == 0
    assert text == "speccheck record: publish recorded T-REQ-001-01, T-REQ-001-02 in .speccheck/publish.jsonl\n"
    parsed, problems = results.read(tmp_path / ".speccheck" / "publish.jsonl")
    assert problems == []
    assert (parsed.producer, parsed.runner) == ("publish", f"speccheck record {__version__}")
    assert parsed.ci["job_url"] == "https://github.com/o/r/actions/runs/11/job/22"
    assert parsed.started.endswith("Z")
    assert [r.to_json() for r in parsed.results] == [
        {
            "test": "publish",
            "covers": [
                {"id": "T-REQ-001-01", "how": "publish proves T-REQ-001-01"},
                {"id": "T-REQ-001-02", "how": "publish proves T-REQ-001-02"},
            ],
            "outcome": "passed",
            "kind": "ci",
        }
    ]


def test_outside_ci(tmp_path: Path):
    """`--job` names the entry, and the header has no CI block."""
    assert run(tmp_path, job="publish")[0] == 0
    assert results.read(tmp_path / ".speccheck" / "publish.jsonl")[0].ci is None


@pytest.mark.parametrize(
    ("args", "env", "written"),
    [
        ({"output": "a.jsonl"}, {"SPECCHECK_RESULTS": "b.jsonl"}, "a.jsonl"),
        ({}, {"SPECCHECK_RESULTS": "b.jsonl"}, "b.jsonl"),
        ({"output": "ABS"}, {}, "abs/c.jsonl"),
    ],
)
def test_where_it_writes(tmp_path: Path, args, env, written):
    """`--output`, else SPECCHECK_RESULTS, else .speccheck/<job>.jsonl; an absolute path as given."""
    if args.get("output") == "ABS":
        args["output"] = str(tmp_path / "abs" / "c.jsonl")
    assert run(tmp_path, env, job="publish", **args)[0] == 0
    assert (tmp_path / written).is_file()


def test_json(tmp_path: Path):
    """The job, its IDs and the file written."""
    code, text = run(tmp_path, FAKE_CI, json_mode=True)
    body = json.loads(text)
    assert (code, body["command"], body["job"]) == (0, "record", "publish")
    assert body["covers"] == [
        {"id": "T-REQ-001-01", "how": "publish proves T-REQ-001-01"},
        {"id": "T-REQ-001-02", "how": "publish proves T-REQ-001-02"},
    ]
    assert body["path"] == str(tmp_path / ".speccheck" / "publish.jsonl")


@pytest.mark.parametrize(
    ("job", "message"),
    [
        (None, "no job name: pass --job NAME"),
        ("unit", "no [ci.unit] entry for this job (CI jobs: publish)"),
        ("other", "no [ci.other] entry"),
    ],
)
def test_no_entry_is_a_config_error(tmp_path: Path, job, message):
    """No job name, a test producer, or an unknown name: nothing is written."""
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace("(", r"\(").replace(")", r"\)")):
        run(tmp_path, job=job)
    assert not (tmp_path / ".speccheck").exists()


def test_no_ci_jobs_at_all(tmp_path: Path):
    """The message says there are none."""
    ctx = make_ctx(tmp_path, loaded=make_config(producer("unit")))
    with pytest.raises(ConfigError, match=r"\(CI jobs: none\)"):
        record.run(ctx, namespace(job="x"))
