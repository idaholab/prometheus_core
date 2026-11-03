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

"""specs/004-results-files.md: the files a real pytest run writes, and what speccheck accepts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import speccheck
from tests.requirements.conftest import CONFIG, EXPECTED, OUTCOMES, Project, outcomes

SCHEMA = Path(speccheck.__file__).parent / "schema" / "speccheck-results-1.schema.json"
"""The JSON Schema shipped with the package."""


@pytest.mark.covers(
    "SPC-REQ-004-01",
    "an inner run writes a speccheck-results/1 header and one result line with a covers list of id and how objects",
)
def test_a_run_writes_json_lines_with_a_versioned_header(project: Project):
    """A header, then one line per claiming test."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 10 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl")
    header, result = project.results_lines("r.jsonl")
    assert header["schema"] == "speccheck-results/1"
    assert header["runner"].startswith("pytest ") and header["producer"] == "local"
    assert result == {
        "test": "test_project.py::test_a",
        "file": "test_project.py",
        "line": 2,  # pytest's location of a decorated test: its first decorator, here the claim itself
        "covers": [{"id": "T-REQ-001-01", "how": "inner claim 10 of T-REQ-001-01"}],
        "outcome": "passed",
    }


PRODUCER_TEST = 'import pytest\n@pytest.mark.covers("T-REQ-001-01", "the producer")\ndef test_a():\n    pass\n'
"""A one-claim test file, for runs that only look at the header's producer."""


@pytest.mark.covers(
    "SPC-REQ-004-01",
    "an inner run whose pytest.ini sets speccheck_producer=from-ini writes from-ini as the header's producer, not the default local",
)
def test_the_header_names_the_producer_from_the_ini_option(project: Project):
    """The ini option is the producer a run reports as, when the environment doesn't say."""
    project.ini("speccheck_producer = from-ini\n")
    project.tests(PRODUCER_TEST)
    project.pytest("--speccheck-results=r.jsonl")
    assert project.results_lines("r.jsonl")[0]["producer"] == "from-ini"


@pytest.mark.covers(
    "SPC-REQ-004-01",
    "an inner run with SPECCHECK_PRODUCER=from-env and no ini option writes from-env as the header's producer",
)
def test_the_header_names_the_producer_from_the_environment(project: Project, monkeypatch: pytest.MonkeyPatch):
    """`SPECCHECK_PRODUCER` alone, as a CI job sets it, is the producer the file carries."""
    project.tests(PRODUCER_TEST)
    monkeypatch.setenv("SPECCHECK_PRODUCER", "from-env")
    project.pytest("--speccheck-results=r.jsonl")
    assert project.results_lines("r.jsonl")[0]["producer"] == "from-env"


@pytest.mark.covers(
    "SPC-REQ-004-01",
    "an inner run with both speccheck_producer=from-ini and SPECCHECK_PRODUCER=from-env writes from-env, the precedence the README states",
)
def test_the_environment_producer_wins_over_the_ini_option(project: Project, monkeypatch: pytest.MonkeyPatch):
    """The README says the environment variable wins over the ini option, so the file carries the variable's value."""
    project.ini("speccheck_producer = from-ini\n")
    project.tests(PRODUCER_TEST)
    monkeypatch.setenv("SPECCHECK_PRODUCER", "from-env")
    project.pytest("--speccheck-results=r.jsonl")
    assert project.results_lines("r.jsonl")[0]["producer"] == "from-env"


@pytest.mark.covers(
    "SPC-REQ-004-01",
    "an inner run of two claiming tests, one with two marks, writes a header and exactly two result lines, "
    "each with one covers entry per claimed ID, and a header whose ci is null and root is null",
)
def test_a_run_writes_one_line_per_claiming_test_and_one_claim_per_id(project: Project):
    """The line count, the covers lists, and the header's `ci` and `root`, outside CI and outside a repository."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "inner claim 22 of T-REQ-001-01")
        @pytest.mark.covers("T-REQ-001-02", "inner claim 23 of T-REQ-001-02")
        def test_two_ids():
            pass

        @pytest.mark.covers("T-REQ-001-03", "inner claim 24 of T-REQ-001-03")
        def test_one_id():
            pass

        def test_no_claim():
            pass
        """
    )
    project.pytest("--speccheck-results=r.jsonl")
    header, *lines = project.results_lines("r.jsonl")
    assert header["ci"] is None and header["root"] is None
    assert {line["test"].split("::", 1)[1]: line["covers"] for line in lines} == {
        "test_two_ids": [
            {"id": "T-REQ-001-02", "how": "inner claim 23 of T-REQ-001-02"},
            {"id": "T-REQ-001-01", "how": "inner claim 22 of T-REQ-001-01"},
        ],
        "test_one_id": [{"id": "T-REQ-001-03", "how": "inner claim 24 of T-REQ-001-03"}],
    }


ALL_OUTCOMES = ("passed", "failed", "error", "skipped", "xfailed", "xpassed", "deselected", "collected")
"""Every outcome a result may have; only the first is evidence."""


@pytest.mark.covers(
    "SPC-REQ-004-03",
    "a results file holding one result for each of the eight outcome names is read by verify with no problem, "
    "and of the eight requirements only the one whose result is passed is proven",
)
def test_every_outcome_is_read_and_only_passed_is_evidence(project: Project):
    """Each outcome name is accepted; none but `passed` makes its requirement pass."""
    ids = [f"T-REQ-001-0{n}" for n in range(1, 9)]
    project.spec("\n".join(f"- {id_}: Requirement {n}." for n, id_ in enumerate(ids, 1)))
    project.results("r.jsonl", "unit", [(f"t_{o}", [i], o) for o, i in zip(ALL_OUTCOMES, ids, strict=True)])
    run = project.speccheck("verify", "r.jsonl", "--json")
    statuses = {r["id"]: r["status"] for r in run.json()["requirements"]}
    assert statuses[ids[0]] == "passed"
    assert all(statuses[i] != "passed" for i in ids[1:]), statuses
    assert not [p for p in run.json()["problems"] if p["code"].startswith("results-")], run.json()["problems"]


@pytest.mark.covers(
    "SPC-REQ-004-03",
    "an inner --collect-only run writes every claiming test as collected, a word verify accepts but does not count as a pass",
)
def test_collected_is_written_and_is_not_a_pass(project: Project):
    """Only collected, not run: written under that name, and not evidence."""
    project.spec("- T-REQ-001-01: One.")
    project.ini("speccheck_producer = unit\n")
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 25 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest("--collect-only", "-q", "--speccheck-results=c.jsonl")
    assert outcomes(project, "c.jsonl") == {"test_a": "collected"}
    # `check` accepts the claim (it asks only whether one exists); `verify` wants a pass
    assert project.speccheck("check", "c.jsonl", "--json").json()["requirements"][0]["status"] == "claimed"
    assert project.speccheck("verify", "c.jsonl", "--json").json()["requirements"][0]["status"] != "passed"


@pytest.mark.covers(
    "SPC-REQ-004-11",
    "the JSON Schema in the installed package is itself valid, accepts the header and result line an inner run "
    "wrote, and rejects the same result line with its outcome removed",
)
def test_the_package_ships_a_schema_the_plugin_matches(project: Project):
    """The schema file is in the installed package, and each line the plugin writes validates against it."""
    assert SCHEMA.is_file()
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 19 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl")
    header, result = project.results_lines("r.jsonl")
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(header)
    validator.validate(result)
    # The negative control: the schema isn't empty, so a line that breaks it is refused
    assert not validator.is_valid({k: v for k, v in result.items() if k != "outcome"})


@pytest.mark.covers(
    "SPC-REQ-004-11",
    "every line of inner runs in a fake GitHub job with SPECCHECK_ROOT set, over passed, failed, skipped, xfailed, xpassed, error, deselected, collected and a test claiming two IDs, validates against the shipped schema",
)
def test_every_line_a_run_writes_matches_the_schema(project: Project, monkeypatch: pytest.MonkeyPatch):
    """The header with a CI block and a root, and results of every outcome including a multi-ID claim."""
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_WORKFLOW": "ci",
        "GITHUB_JOB": "unit",
        "GITHUB_RUN_ID": "9",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_SHA": "c" * 40,
        "GITHUB_REF": "refs/heads/devel",
        "GITHUB_EVENT_NAME": "push",
        "SPECCHECK_JOB_ID": "77",
        "SPECCHECK_ROOT": "sdk",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    project.tests(
        OUTCOMES
        + """
@pytest.mark.covers("T-REQ-001-02", "inner claim 26 of T-REQ-001-02")
@pytest.mark.covers("T-REQ-001-03", "inner claim 27 of T-REQ-001-03")
def test_two_ids():
    pass
"""
    )
    project.pytest("--speccheck-results=r.jsonl", "-k", "not test_deselected and not claims_nothing")
    lines = project.results_lines("r.jsonl")
    validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
    for line in lines:
        validator.validate(line)
    header, results = lines[0], lines[1:]
    assert header["ci"]["job_id"] == 77 and header["root"] == "sdk"
    assert {r["outcome"] for r in results} >= {"passed", "failed", "skipped", "xfailed", "xpassed", "error"}
    assert any(len(r["covers"]) == 2 for r in results)
    project.pytest("--speccheck-results=d.jsonl", "-k", "test_passes")
    deselected = [r for r in project.results_lines("d.jsonl")[1:] if r["outcome"] == "deselected"]
    assert deselected, "a claiming test left out with -k is written as deselected"
    for line in project.results_lines("d.jsonl"):
        validator.validate(line)
    project.pytest("--speccheck-results=c.jsonl", "--collect-only", "-q")
    collected = project.results_lines("c.jsonl")
    assert {r["outcome"] for r in collected[1:]} == {"collected"}
    for line in collected:
        validator.validate(line)


@pytest.mark.covers(
    "SPC-REQ-004-11",
    "the schema is built into a wheel from this source and the wheel's copy equals the source file, so the package ships the schema a writer in another language would use",
)
def test_the_built_wheel_contains_the_schema(tmp_path: Path):
    """The test above finds the schema through the source tree; this one builds the package and looks inside it."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is needed to build the wheel")
    project_dir = SCHEMA.parents[2]
    # Build from a clean copy: the source folder's own `build/` and egg-info (both ignored by git) list the
    # schema from an earlier build, so a build there would include it even with the package-data entry gone
    source = tmp_path / "source"
    source.mkdir()
    shutil.copy(project_dir / "pyproject.toml", source)
    shutil.copy(project_dir / "README.md", source)
    shutil.copytree(project_dir / "speccheck", source / "speccheck", ignore=shutil.ignore_patterns("__pycache__"))
    out = tmp_path / "dist"
    build = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(out), str(source)], capture_output=True, text=True, check=False
    )
    assert build.returncode == 0, build.stderr
    [wheel] = out.glob("prometheus_speccheck-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        inside = archive.read("speccheck/schema/speccheck-results-1.schema.json")
    assert inside == SCHEMA.read_bytes()


GOOD_LINE = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
"""A valid result line, which a test then breaks one field of."""


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(
            {"schema": "speccheck-results/2"},
            "this speccheck reads only 'speccheck-results/1'",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02",
                "a header with schema speccheck-results/2 rejects the file, so its passing result doesn't count",
            ),
            id="other-schema",
        ),
        pytest.param(
            {"producer": 3},
            "`producer` must be a string",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose producer is a number rejects the file and its passing result"
            ),
            id="wrong-type",
        ),
        pytest.param(
            {"schema": None},
            "`schema` is None; this speccheck reads only 'speccheck-results/1'",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose schema is null rejects the file and its passing result"
            ),
            id="schema-null",
        ),
        pytest.param(
            {"schema": 1},
            "`schema` is 1; this speccheck reads only 'speccheck-results/1'",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose schema is the number 1 rejects the file and its passing result"
            ),
            id="schema-number",
        ),
        pytest.param(
            {"ci": "github"},
            "`ci` must be an object or null",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose ci is a string, not an object, rejects the file and its pass"
            ),
            id="ci-string",
        ),
        pytest.param(
            {"root": 5},
            "`root` must be a string",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose root is a number rejects the file and its passing result"
            ),
            id="root-number",
        ),
        pytest.param(
            {"runner": 3},
            "`runner` must be a string",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose runner is a number, not a string, rejects the file and its pass"
            ),
            id="runner-number",
        ),
        pytest.param(
            {"started": 20261102},
            "`started` must be a string",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose started is a number, not a timestamp string, rejects the file"
            ),
            id="started-number",
        ),
        pytest.param(
            {"producer": "p" * 201},
            "`producer` is longer than 200 characters",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a header whose producer is 201 characters rejects the file and its passing result"
            ),
            id="producer-over-200",
        ),
    ],
)
def test_a_bad_header_rejects_the_whole_file(project: Project, change: dict, message: str):
    """Its passing results don't count: the requirement stays unproven."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", **change}
    line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
    project.write("r.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    assert run.code == 1
    assert any(message in p["message"] and p["path"] == "r.jsonl" and p["line"] == 1 for p in run.json()["problems"]), (
        run.json()["problems"]
    )
    assert run.json()["requirements"][0]["status"] != "passed"


@pytest.mark.covers(
    "SPC-REQ-004-02",
    "a file with a 200-character producer, a 250-character test node ID and a 200-character CI job name is read with no length problem",
)
def test_names_at_their_limits_are_read_whole(project: Project):
    """The other side of the limits: exactly at them is fine."""
    project.write("speccheck.toml", CONFIG.replace("[producers.unit]", f"[producers.{'p' * 200}]"))
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    header = {"schema": "speccheck-results/1", "producer": "p" * 200}
    lines = [
        {**GOOD_LINE, "test": "t" * 250},
        {**GOOD_LINE, "test": "j" * 200, "kind": "ci", "covers": [{"id": "T-REQ-001-02", "how": "h2"}]},
    ]
    project.write("r.jsonl", "\n".join(json.dumps(x) for x in (header, *lines)) + "\n")
    run = project.speccheck("check", "r.jsonl", "--json")
    assert not [p for p in run.json()["problems"] if p["code"] == "results-invalid"], run.json()["problems"]
    assert {r["id"]: r["status"] for r in run.json()["requirements"]} == {
        "T-REQ-001-01": "claimed",
        "T-REQ-001-02": "claimed",
    }


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(
            "[]",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a first line that is an empty JSON list, not an object, rejects the file"
            ),
            id="list",
        ),
        pytest.param(
            '"speccheck-results/1"',
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a first line that is the schema name as a bare JSON string rejects the file"
            ),
            id="string",
        ),
        pytest.param(
            "null",
            marks=pytest.mark.covers("SPC-REQ-004-02", "a first line of JSON null rejects the file"),
            id="null",
        ),
    ],
)
def test_a_header_that_is_not_an_object_rejects_the_whole_file(project: Project, header: str):
    """The first line must be the header object; the result line after it doesn't count."""
    project.spec("- T-REQ-001-01: One.")
    project.write("r.jsonl", header + "\n" + json.dumps(GOOD_LINE) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    assert run.code == 1
    assert any(
        p["path"] == "r.jsonl"
        and p["line"] == 1
        and p["message"].startswith("not a valid speccheck-results/1 line: the first line must be the header object")
        for p in run.json()["problems"]
    ), run.json()["problems"]
    assert run.json()["requirements"][0]["status"] != "passed"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        pytest.param(
            {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "ok"},
            "`outcome` is 'ok'",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a third line with outcome ok rejects the file, though its second line passed"
            ),
            id="unknown-outcome",
        ),
        pytest.param(
            {"test": "t", "covers": "T-REQ-001-01", "outcome": "passed"},
            "`covers` must be a list",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a third line whose covers is a string, not a list, rejects the whole file"
            ),
            id="covers-not-a-list",
        ),
        *(
            pytest.param(
                {**GOOD_LINE, key: value},
                message,
                marks=pytest.mark.covers(
                    "SPC-REQ-004-02", f"a third line whose {key} is {value!r} rejects the file and its good second line"
                ),
                id=f"{key}-{type(value).__name__}",
            )
            for key, value, message in [
                ("test", 3, "`test` must be a string"),
                ("test", None, "`test` must be a string"),
                ("file", 3, "`file` must be a string"),
                ("line", "3", "`line` must be a whole number"),
                ("line", 1.5, "`line` must be a whole number"),
                ("line", True, "`line` must be a whole number"),
                ("line", -1, "`line` must be a whole number"),
                ("kind", "other", "`kind` must be one of test, ci"),
                ("outcome", None, "`outcome` is None"),
                ("outcome", 1, "`outcome` is 1"),
            ]
        ),
        *(
            pytest.param(
                {**GOOD_LINE, "covers": [{"id": value, "how": "h"}]},
                "`covers[].id` must be a string",
                marks=pytest.mark.covers(
                    "SPC-REQ-004-02", f"a third line whose only covers entry has the id {value!r} rejects the file"
                ),
                id=f"covers-id-{type(value).__name__}",
            )
            for value in (3, None, ["T-REQ-001-01"])
        ),
        pytest.param(
            {**GOOD_LINE, "covers": []},
            "`covers` must be a list of 1 to 200 claims",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02",
                "a third line whose covers is an empty list, claiming nothing, rejects the file: a result must claim at least one ID",
            ),
            id="covers-empty",
        ),
        pytest.param(
            {k: v for k, v in GOOD_LINE.items() if k != "outcome"},
            "`outcome` is None",
            marks=pytest.mark.covers("SPC-REQ-004-02", "a third line with no outcome rejects the whole file"),
            id="outcome-missing",
        ),
        pytest.param(
            [1, 2],
            "a result must be an object",
            marks=pytest.mark.covers("SPC-REQ-004-02", "a third line that is a JSON list rejects the whole file"),
            id="line-is-a-list",
        ),
        pytest.param(
            {**GOOD_LINE, "test": "t" * 251},
            "`test` is longer than 250 characters",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a third line whose test node ID is 251 characters rejects the whole file"
            ),
            id="test-over-250",
        ),
        pytest.param(
            {**GOOD_LINE, "test": "j" * 201, "kind": "ci"},
            "`test` is longer than 200 characters",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a third line for a CI job whose name is 201 characters rejects the whole file"
            ),
            id="job-over-200",
        ),
    ],
)
def test_a_bad_result_line_rejects_the_whole_file(project: Project, line: dict, message: str):
    """One bad line, even after a good one, and nothing in the file counts."""
    project.spec("- T-REQ-001-01: One.")
    good = {"test": "good", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
    header = {"schema": "speccheck-results/1", "producer": "unit"}
    project.write("r.jsonl", "\n".join(json.dumps(x) for x in (header, good, line)) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    assert run.code == 1
    assert any(
        p["path"] == "r.jsonl"
        and p["line"] == 3
        and p["message"].startswith(f"not a valid speccheck-results/1 line: {message}")
        for p in run.json()["problems"]
    ), run.json()["problems"]
    # The good second line is dropped with the rest of the file
    assert run.json()["requirements"][0]["status"] != "passed"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        # "nested too deeply" before Python 3.14, "Expecting value" on 3.14: either way, "not JSON"
        pytest.param(
            "[" * 30000,
            "not JSON",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02",
                "30,000 nested brackets reject the file as not JSON, and verify and report still print one object and report writes r.md",
            ),
            id="deep-nesting",
        ),
        pytest.param(
            '{"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed", "line": '
            + "9" * 5000
            + "}",
            "digits",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02",
                "a 5000-digit line number rejects the file instead of crashing the integer parser, and report still writes r.md",
            ),
            id="huge-number",
        ),
        pytest.param(
            '{"test": "t\\ud800", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}',
            "lone surrogate",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02",
                "a test name with a lone surrogate escape rejects the file, and verify and report still print one object and report writes r.md",
            ),
            id="lone-surrogate",
        ),
    ],
)
def test_a_hostile_line_is_a_problem_not_a_crash(project: Project, line: str, message: str):
    """Deep nesting, a huge number and a lone surrogate reject the file, and `--json` still gives one object."""
    project.spec("- T-REQ-001-01: One.")
    good = {"test": "good", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
    header = {"schema": "speccheck-results/1", "producer": "unit"}
    project.write("r.jsonl", "\n".join([json.dumps(header), json.dumps(good), line]) + "\n")
    for command in ("verify", "report"):
        run = project.speccheck(command, "r.jsonl", "--json")
        assert run.code == (1 if command == "verify" else 0)
        problems = run.json()["problems"]
        assert any(p["path"] == "r.jsonl" and p["line"] == 3 and message in p["message"] for p in problems)
        assert run.json()["requirements"][0]["status"] != "passed"
    assert project.speccheck("report", "r.jsonl", "--output", "r.md").code == 0
    assert (project.root / "r.md").is_file()


@pytest.mark.covers(
    "SPC-REQ-004-02",
    "extra keys in the header, its ci block and a result line still let verify count the pass",
)
def test_unknown_keys_are_ignored(project: Project):
    """A newer writer's extra fields, in the header, its `ci` block and a result, don't stop the file counting."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", "extra": 1, "ci": {"leg": "3.12", "new": "x"}}
    line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h", "new": 2}], "outcome": "passed", "x": 1}
    project.write("r.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    assert run.code == 0 and run.json()["problems"] == []
    assert run.json()["requirements"][0]["status"] == "passed"


@pytest.mark.parametrize(
    ("covers", "message"),
    [
        pytest.param(
            [{"id": "T-REQ-001-01", "how": "a"}, {"id": "T-REQ-001-01", "how": "b"}],
            "`covers` claims T-REQ-001-01 more than once",
            marks=pytest.mark.covers(
                "SPC-REQ-004-09", "a result claiming T-REQ-001-01 twice with two explanations rejects the file"
            ),
            id="id-twice",
        ),
        pytest.param(
            [{"id": "T-REQ-001-01", "how": ""}],
            "`covers[].how` must not be empty",
            marks=pytest.mark.covers("SPC-REQ-004-09", "a result with an empty how rejects the file"),
            id="empty-how",
        ),
        pytest.param(
            [{"id": "T-REQ-001-01", "how": "x" * 1001}],
            "`covers[].how` is longer than 1000 characters",
            marks=pytest.mark.covers("SPC-REQ-004-09", "a result with a 1001-character how rejects the file"),
            id="long-how",
        ),
        pytest.param(
            [{"id": "T-REQ-001-01", "how": "line one line two"}],
            "`covers[].how` for T-REQ-001-01 has a line break",
            marks=pytest.mark.covers(
                "SPC-REQ-004-09",
                "a how holding a Unicode line separator, which another writer might leave in, rejects the file",
            ),
            id="line-break",
        ),
        *(
            pytest.param(
                [{"id": "T-REQ-001-01", "how": f"one{char}two"}],
                "`covers[].how` for T-REQ-001-01 has a line break",
                marks=pytest.mark.covers(
                    "SPC-REQ-004-09", f"a how holding the character {char!r} between two words rejects the file"
                ),
                id=f"break-{ord(char):#04x}",
            )
            for char in ("\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ")
        ),
        pytest.param(
            [{"id": "T-REQ-001-01", "how": " \t "}],
            "the explanation for T-REQ-001-01 is empty",
            marks=pytest.mark.covers(
                "SPC-REQ-004-09", "a how of only spaces and a tab collapses to empty and rejects the file"
            ),
            id="blank-how",
        ),
        *(
            pytest.param(
                [{"id": "T-REQ-001-01", "how": how}],
                f"the explanation for T-REQ-001-01 is a placeholder ({how!r})",
                marks=pytest.mark.covers(
                    "SPC-REQ-004-09", f"a result whose how is the placeholder {how!r} rejects the file"
                ),
                id=f"placeholder-{how.lower()}",
            )
            for how in ("TODO", "fixme", "...", "-")
        ),
        pytest.param(
            [{"id": "T-REQ-001-01", "how": "  tbd  "}],
            "the explanation for T-REQ-001-01 is a placeholder ('tbd')",
            marks=pytest.mark.covers(
                "SPC-REQ-004-09", "a how of tbd padded with spaces collapses to the placeholder and rejects the file"
            ),
            id="placeholder-padded",
        ),
        pytest.param(
            [{"id": "T-REQ-001-01", "how": "TBD"}],
            "the explanation for T-REQ-001-01 is a placeholder ('TBD')",
            marks=pytest.mark.covers(
                "SPC-REQ-004-09", "a result whose how is TBD, written by another writer, rejects the file"
            ),
            id="placeholder",
        ),
        pytest.param(
            [{"id": "T-REQ-001-01", "how": "t-req-001-01"}],
            "the explanation for T-REQ-001-01 is just the ID",
            marks=pytest.mark.covers(
                "SPC-REQ-004-09", "a result whose how is its own claimed ID in lower case rejects the file"
            ),
            id="the-id",
        ),
        pytest.param(
            ["T-REQ-001-01"],
            'each `covers` entry must be an object, {"id": ..., "how": ...}',
            marks=pytest.mark.covers(
                "SPC-REQ-004-01", "a covers list of bare IDs, the old form, rejects the file and shows the object form"
            ),
            id="bare-id",
        ),
    ],
)
def test_a_bad_claim_in_a_result_rejects_the_file(project: Project, covers: list, message: str):
    """Written by another writer, which may not have collapsed or checked its explanations; nothing in it counts."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit"}
    line = {"test": "t", "covers": covers, "outcome": "passed"}
    project.write("r.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    assert run.code == 1
    assert any(message in p["message"] for p in run.json()["problems"]), run.json()["problems"]
    assert run.json()["requirements"][0]["status"] != "passed"


@pytest.mark.covers("SPC-REQ-004-09", "a result whose how is exactly 1000 characters is accepted and its pass counts")
def test_a_how_of_exactly_1000_characters_is_accepted(project: Project):
    """The limit is 1000, so 1000 passes; the over-limit case is the 1001 above."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit"}
    line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "x" * 1000}], "outcome": "passed"}
    project.write("r.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    assert run.code == 0 and run.json()["problems"] == []
    assert run.json()["requirements"][0]["status"] == "passed"


@pytest.mark.covers(
    "SPC-REQ-004-03",
    "the inner run's results file uses the outcome names failed, error, skipped, xfailed, xpassed and passed for those tests",
)
@pytest.mark.covers(
    "SPC-REQ-004-04",
    "a claiming test left out with -k is written as deselected and a skipped one as skipped, while a test with no claim isn't written",
)
def test_every_outcome_and_deselected_tests_are_written(project: Project):
    """Setup, call and teardown merged into one outcome; skipped and deselected claims are written; unclaimed tests aren't."""
    project.tests(OUTCOMES)
    project.pytest("--speccheck-results=r.jsonl", "-k", "not test_deselected and not claims_nothing")
    assert outcomes(project, "r.jsonl") == EXPECTED


@pytest.mark.covers(
    "SPC-REQ-004-01",
    "a result whose test ID holds U+2028 and U+0085 is still one JSON line, so verify reads the file back and exits 0",
)
def test_a_test_id_with_a_unicode_line_separator_still_reads(project: Project):
    """U+2028 and U+0085 in a test ID are written as they are, and must not split the line on read."""
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t.py::test[a\u2028b\u0085c]", ["T-REQ-001-01"], "passed")])
    done = project.speccheck("verify", "unit.jsonl")
    assert done.code == 0


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "a plain inner run writes no .jsonl, and SPECCHECK_RESULTS=out/env.jsonl writes out/env.jsonl under the project folder",
)
def test_a_file_only_when_asked(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Nothing by default; the option or SPECCHECK_RESULTS (a path under the project folder) asks for one."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 11 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest()
    assert not list(project.root.rglob("*.jsonl"))
    monkeypatch.setenv("SPECCHECK_RESULTS", "out/env.jsonl")
    project.pytest()
    assert (project.root / "out" / "env.jsonl").is_file()


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "a results path under a plain file ends the inner run as a usage error with a message and no traceback",
)
def test_an_unwritable_results_path_is_a_usage_error(project: Project):
    """A file where the folder should be: pytest says why and exits as a usage error, with no traceback."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 12 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    (project.root / "blocker").write_text("a file, not a folder")
    run = project.pytest("--speccheck-results=blocker/r.jsonl")
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    assert "speccheck: can't write the results file" in "\n".join(run.stderr.lines + run.stdout.lines)
    # A raw OSError would print a traceback on either stream, or in pytest's own report
    assert "Traceback" not in run.stdout.str()
    assert "Traceback" not in run.stderr.str()


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "SPECCHECK_RESULTS set to the empty string, and then --speccheck-results given empty, run clean and leave no results file or temporary file",
)
def test_an_empty_request_for_a_file_writes_nothing(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Set but empty is not a request: no results file, no temporary file, and no error."""
    project.tests(PRODUCER_TEST)
    monkeypatch.setenv("SPECCHECK_RESULTS", "")
    run = project.pytest()
    assert run.ret == pytest.ExitCode.OK
    assert not list(project.root.rglob("*.jsonl"))
    run = project.pytest("--speccheck-results=")
    assert run.ret == pytest.ExitCode.OK
    assert not list(project.root.rglob("*.jsonl"))
    assert not [p for p in project.root.iterdir() if "jsonl" in p.name]


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "a results path that is an existing folder ends the inner run as a usage error giving the system's error, with no traceback, and leaves the folder empty and no temporary file",
)
def test_a_results_path_that_is_a_folder_is_a_usage_error(project: Project):
    """The target exists but is a folder, so nothing can be renamed over it: the run says why and leaves no litter."""
    project.tests(PRODUCER_TEST)
    (project.root / "taken").mkdir()
    run = project.pytest("--speccheck-results=taken")
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    message = "\n".join(run.stderr.lines + run.stdout.lines)
    assert re.search(r"speccheck: can't write the results file: \[Errno \d+\] .+: '.*taken", message), message
    assert "Traceback" not in message
    assert (project.root / "taken").is_dir()
    assert list((project.root / "taken").iterdir()) == []
    assert not [p for p in project.root.iterdir() if p.name.startswith(".taken")]


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "a KeyboardInterrupt in a subprocess run leaves neither the results file nor its temporary file",
)
def test_an_interrupted_session_leaves_no_file(project: Project):
    """A KeyboardInterrupt mid-run (in a separate process, as a real one would be) writes nothing."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 13 of T-REQ-001-01")\ndef test_a():\n    raise KeyboardInterrupt\n'
    )
    run = project.pytest("--speccheck-results=r.jsonl", subprocess=True)
    assert run.ret == pytest.ExitCode.INTERRUPTED
    assert not (project.root / "r.jsonl").exists()
    assert not [p for p in project.root.iterdir() if p.name.startswith(".r.jsonl")]


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "from inside the last of three inner tests neither r.jsonl nor a temporary file exists yet, and after the session r.jsonl does, so the file is written when the session ends",
)
def test_the_file_is_written_when_the_session_ends(project: Project):
    """Checked from inside the run, so a file written per test, or at the start, would be seen."""
    project.tests(
        """\
        import pathlib
        import pytest

        def written():
            return [p.name for p in pathlib.Path(".").iterdir() if p.name.startswith(("r.jsonl", ".r.jsonl"))]

        @pytest.mark.covers("T-REQ-001-01", "inner claim 30 of T-REQ-001-01")
        def test_first():
            assert written() == []

        @pytest.mark.covers("T-REQ-001-02", "inner claim 31 of T-REQ-001-02")
        def test_second():
            assert written() == []

        @pytest.mark.covers("T-REQ-001-03", "inner claim 32 of T-REQ-001-03")
        def test_last():
            assert written() == []
        """
    )
    run = project.pytest("--speccheck-results=r.jsonl", subprocess=True)
    run.assert_outcomes(passed=3)
    assert (project.root / "r.jsonl").is_file()
    assert [p.name for p in project.root.iterdir() if p.name.startswith(".r.jsonl")] == []


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "a results path under a plain file ends the inner run as a usage error whose message gives the operating system's own error, with its errno and the path",
)
def test_an_unwritable_path_says_why(project: Project):
    """The message carries the system's own error, whatever its wording on this system, not only that the write failed."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 33 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    (project.root / "blocker").write_text("a file, not a folder")
    run = project.pytest("--speccheck-results=blocker/r.jsonl")
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    message = "\n".join(run.stderr.lines + run.stdout.lines)
    # The wording is the system's (`File exists` where mkdir fails, `Not a directory` elsewhere), so check its shape
    assert re.search(r"speccheck: can't write the results file: \[Errno \d+\] .+: '.*blocker", message), message


@pytest.mark.covers(
    "SPC-REQ-004-06",
    "an inner run with -n 2 writes a single x.jsonl holding every claiming test's real outcome",
)
def test_xdist_writes_one_file_with_every_workers_results(project: Project):
    """Two workers: one file, with each test's real outcome."""
    project.tests(OUTCOMES)
    project.pytest(
        "-p",
        "xdist",
        "-n",
        "2",
        "--speccheck-results=x.jsonl",
        "-k",
        "not test_deselected and not claims_nothing",
        subprocess=True,
    )
    assert outcomes(project, "x.jsonl") == EXPECTED
    assert [p.name for p in project.root.glob("*.jsonl")] == ["x.jsonl"]


@pytest.mark.covers(
    "SPC-REQ-004-06",
    "two inner tests that each wait for the other's file run on two different workers, and the one x.jsonl holds both, passed",
)
def test_xdist_file_holds_what_each_worker_ran(project: Project):
    """Each test needs the other to be running, so the two workers must both run one; the file has both."""
    project.tests(
        """\
        import os
        import time
        import pytest

        def meet(mine, theirs):
            with open(mine, "w") as flag:
                flag.write(os.environ["PYTEST_XDIST_WORKER"])
            deadline = time.time() + 30
            while not os.path.exists(theirs):
                assert time.time() < deadline, "the other worker never ran its test"
                time.sleep(0.05)

        @pytest.mark.covers("T-REQ-001-01", "inner claim run by the first worker")
        def test_first():
            meet("first.worker", "second.worker")

        @pytest.mark.covers("T-REQ-001-02", "inner claim run by the second worker")
        def test_second():
            meet("second.worker", "first.worker")
        """
    )
    project.pytest("-p", "xdist", "-n", "2", "--speccheck-results=x.jsonl", subprocess=True)
    assert outcomes(project, "x.jsonl") == {"test_first": "passed", "test_second": "passed"}
    workers = {(project.root / name).read_text() for name in ("first.worker", "second.worker")}
    assert len(workers) == 2, workers


@pytest.mark.covers(
    "SPC-REQ-004-06",
    "an inner run with -n 1 whose worker dies mid-run still writes the claim that passed before the crash as passed",
)
def test_xdist_keeps_what_a_crashed_worker_ran(project: Project):
    """The crashed worker sends no claims; the controller's relayed reports keep the pass."""
    project.tests(
        """\
        import os
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "inner claim that passes before the crash")
        def test_a():
            pass

        def test_b():
            os._exit(1)

        @pytest.mark.covers("T-REQ-001-01", "inner claim that runs on the replacement worker")
        def test_c():
            pass
        """
    )
    project.pytest("-p", "xdist", "-n", "1", "--speccheck-results=x.jsonl", subprocess=True)
    assert outcomes(project, "x.jsonl") == {"test_a": "passed", "test_c": "passed"}


@pytest.mark.covers(
    "SPC-REQ-004-07",
    "verify refuses a results file of 16 MiB plus one byte, naming the limit, and reports nothing from it",
)
def test_a_file_over_16_mib_is_refused(project: Project):
    """The size is checked before the file is read."""
    project.spec("- T-REQ-001-01: One.")
    with (project.root / "big.jsonl").open("wb") as out:
        out.truncate(16 * 1024 * 1024 + 1)
    run = project.speccheck("verify", "big.jsonl", "--json")
    assert run.code == 1
    assert any(
        p["path"] == "big.jsonl" and "results file is 16777217 bytes; the limit is 16777216" in p["message"]
        for p in run.json()["problems"]
    ), run.json()["problems"]
    assert run.json()["producers"]["reported"] == []


@pytest.mark.covers(
    "SPC-REQ-004-07",
    "verify on a results file of exactly 16 MiB gives a problem other than results-too-large, so it was read",
)
def test_a_file_of_exactly_16_mib_is_read(project: Project):
    """The limit is on bytes over 16 MiB: a file of exactly 16 MiB is read, and fails as something else."""
    project.spec("- T-REQ-001-01: One.")
    with (project.root / "edge.jsonl").open("wb") as out:
        out.truncate(16 * 1024 * 1024)
    run = project.speccheck("verify", "edge.jsonl", "--json")
    codes = {p["code"] for p in run.json()["problems"] if p["path"] == "edge.jsonl"}
    assert codes and "results-too-large" not in codes, run.json()["problems"]


@pytest.mark.covers(
    "SPC-REQ-004-07", "verify refuses a 16 MiB plus one byte file found by searching a folder, and reads no results"
)
def test_a_big_file_in_a_folder_is_refused(project: Project):
    """The size check applies to a file found in a folder, not only to one named on the command line."""
    project.spec("- T-REQ-001-01: One.")
    (project.root / "r").mkdir()
    with (project.root / "r" / "big.jsonl").open("wb") as out:
        out.truncate(16 * 1024 * 1024 + 1)
    run = project.speccheck("verify", "r", "--json")
    assert any(p["path"] == "r/big.jsonl" and p["code"] == "results-too-large" for p in run.json()["problems"])
    assert run.json()["producers"]["reported"] == []


def _line_of_bytes(size: int, pad: str) -> str:
    """A valid result line of exactly `size` bytes, padded with an unknown key that the reader ignores."""
    base = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed", "pad": ""}
    empty = len(json.dumps(base, ensure_ascii=False).encode())
    count, rest = divmod(size - empty, len(pad.encode()))
    # The remainder (when `pad` is wider than a byte) is filled with ASCII
    base["pad"] = pad * count + "x" * rest
    line = json.dumps(base, ensure_ascii=False)
    assert len(line.encode()) == size
    return line


@pytest.mark.parametrize(
    ("size", "pad", "accepted"),
    [
        pytest.param(
            65536,
            "x",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-004-07", "a result line of exactly 65536 ASCII bytes is read and its pass counts"
            ),
            id="at-the-limit",
        ),
        pytest.param(
            65537,
            "x",
            False,
            marks=pytest.mark.covers(
                "SPC-REQ-004-07", "a result line of 65537 ASCII bytes is refused as a line too long"
            ),
            id="one-over",
        ),
        pytest.param(
            65538,
            "é",
            False,
            marks=pytest.mark.covers(
                "SPC-REQ-004-07",
                "a result line of 65538 bytes but only about 32,800 characters, in two-byte letters, is refused",
            ),
            id="bytes-not-characters",
        ),
        pytest.param(
            65536,
            "é",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-004-07",
                "a result line of exactly 65536 bytes in two-byte letters is read, so bytes are counted",
            ),
            id="multibyte-at-the-limit",
        ),
    ],
)
def test_the_line_limit_is_in_bytes(project: Project, size: int, pad: str, accepted: bool):
    """64 KiB of bytes, not of characters: the boundary is exact either side."""
    project.spec("- T-REQ-001-01: One.")
    header = json.dumps({"schema": "speccheck-results/1", "producer": "unit"})
    project.write("r.jsonl", header + "\n" + _line_of_bytes(size, pad) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    codes = {p["code"] for p in run.json()["problems"]}
    if accepted:
        assert run.code == 0 and run.json()["problems"] == []
        assert run.json()["requirements"][0]["status"] == "passed"
    else:
        assert "results-line-too-long" in codes
        assert run.json()["requirements"][0]["status"] != "passed"


@pytest.mark.covers(
    "SPC-REQ-004-07",
    "verify refuses a results line of 70,000 characters, over 64 KiB, and ignores a symlinked file and folder in the results folder, so nothing is reported",
)
def test_limits_and_symlinks(project: Project, tmp_path_factory: pytest.TempPathFactory):
    """An over-long line is refused, and a symlink in a results folder is not followed."""
    project.spec("- T-REQ-001-01: One.")
    header = json.dumps({"schema": "speccheck-results/1", "producer": "unit"})
    project.write(
        "r/long.jsonl",
        header
        + "\n"
        + json.dumps({"test": "x" * 70_000, "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"})
        + "\n",
    )
    outside = tmp_path_factory.mktemp("outside")
    (outside / "good.jsonl").write_text(
        header
        + "\n"
        + json.dumps({"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"})
        + "\n"
    )
    (project.root / "r" / "link.jsonl").symlink_to(outside / "good.jsonl")
    (project.root / "r" / "dir").symlink_to(outside, target_is_directory=True)
    run = project.speccheck("verify", "r", "--json")
    assert any(
        "r/long.jsonl:2: line longer than 65536 bytes" == f"{p['path']}:{p['line']}: {p['message']}"
        for p in run.json()["problems"]
    )
    assert run.json()["producers"]["reported"] == []
    assert run.json()["requirements"][0]["status"] == "not run"


@pytest.mark.covers(
    "SPC-REQ-004-08",
    "an inner run outside CI writes `ci: null`, and with GitHub variables set writes the provider, server, repository, workflow, job, run, attempt and sha, all keys the shipped schema lists",
)
def test_the_ci_context(project: Project, monkeypatch: pytest.MonkeyPatch):
    """In CI the header says which provider and where the run was; outside it, `ci` is null."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 14 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=local.jsonl")
    assert project.results_lines("local.jsonl")[0]["ci"] is None
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_WORKFLOW": "test",
        "GITHUB_JOB": "unit",
        "GITHUB_RUN_ID": "9",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_SHA": "c" * 40,
        "SPECCHECK_JOB_ID": "77",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    project.pytest("--speccheck-results=ci.jsonl")
    ci = project.results_lines("ci.jsonl")[0]["ci"]
    assert (ci["server"], ci["repository"], ci["workflow"], ci["job"], ci["job_id"]) == (
        "https://github.com",
        "o/r",
        "test",
        "unit",
        77,
    )
    assert (ci["run_id"], ci["run_attempt"], ci["sha"]) == (9, 2, "c" * 40)
    assert ci["provider"] == "github" and "leg" not in ci
    assert set(ci) <= set(json.loads(SCHEMA.read_text())["$defs"]["ci"]["properties"])


@pytest.mark.parametrize(
    "flag",
    [
        pytest.param(
            "false",
            marks=pytest.mark.covers(
                "SPC-REQ-004-08", "an inner run with GITHUB_ACTIONS=false and other GITHUB_* set writes ci null"
            ),
            id="false",
        ),
        pytest.param(
            "",
            marks=pytest.mark.covers(
                "SPC-REQ-004-08", "an inner run with GITHUB_ACTIONS empty and other GITHUB_* set writes ci null"
            ),
            id="empty",
        ),
        pytest.param(
            "True",
            marks=pytest.mark.covers(
                "SPC-REQ-004-08", "an inner run with GITHUB_ACTIONS=True, not the exact word true, writes ci null"
            ),
            id="wrong-case",
        ),
    ],
)
def test_ci_is_null_unless_github_actions_is_true(project: Project, monkeypatch: pytest.MonkeyPatch, flag: str):
    """Other GITHUB_* variables alone (as in a developer's shell) don't make a run a CI run."""
    for name, value in {
        "GITHUB_ACTIONS": flag,
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "9",
    }.items():
        monkeypatch.setenv(name, value)
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 28 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl")
    assert project.results_lines("r.jsonl")[0]["ci"] is None


@pytest.mark.covers(
    "SPC-REQ-004-08",
    "an inner run in a fake GitHub job writes a header whose ci block has the server, repository, workflow, job, run, attempt, job ID and commit it was given, and validates against the shipped schema",
)
def test_the_ci_values_are_the_ones_given(project: Project, monkeypatch: pytest.MonkeyPatch):
    """The values, not only the key names, and the header validates against the schema."""
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://ghe.example.com",
        "GITHUB_REPOSITORY": "acme/widgets",
        "GITHUB_WORKFLOW": "release",
        "GITHUB_JOB": "package",
        "GITHUB_RUN_ID": "123456",
        "GITHUB_RUN_ATTEMPT": "4",
        "GITHUB_SHA": "f" * 40,
        "SPECCHECK_JOB_ID": "987",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 29 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl")
    header = project.results_lines("r.jsonl")[0]
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(header)
    ci = header["ci"]
    assert (ci["provider"], ci["server"], ci["repository"], ci["workflow"], ci["job"]) == (
        "github",
        "https://ghe.example.com",
        "acme/widgets",
        "release",
        "package",
    )
    assert (ci["run_id"], ci["run_attempt"], ci["job_id"], ci["sha"]) == (123456, 4, 987, "f" * 40)


@pytest.mark.covers(
    "SPC-REQ-004-10",
    "an inner run in a sub folder of a GITHUB_WORKSPACE writes that folder as root, a run at the workspace writes `.`, and one in no repository writes null",
)
def test_the_header_says_where_file_paths_start(project: Project, monkeypatch: pytest.MonkeyPatch):
    """`root` is pytest's root as a path from the repository's root, so `root/file` is a repository path."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "the root")\ndef test_a():\n    pass\n')
    monkeypatch.setenv("GITHUB_WORKSPACE", str(project.root.parent))
    project.pytest("--speccheck-results=sub.jsonl")
    header, result = project.results_lines("sub.jsonl")
    assert (header["root"], result["file"]) == (project.root.name, "test_project.py")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(project.root))
    project.pytest("--speccheck-results=top.jsonl")
    assert project.results_lines("top.jsonl")[0]["root"] == "."
    monkeypatch.delenv("GITHUB_WORKSPACE")
    if any((folder / ".git").exists() for folder in [project.root, *project.root.parents]):
        pytest.skip("the temp folder is inside a repository, so there is no folder without one to test")
    # pytester's folder is under the system temp folder, which isn't in any repository
    project.pytest("--speccheck-results=none.jsonl")
    assert project.results_lines("none.jsonl")[0]["root"] is None


@pytest.mark.covers(
    "SPC-REQ-004-10",
    "with no GITHUB_WORKSPACE, an inner run in a folder under one holding a .git writes the path down from that folder as root",
)
def test_root_is_found_by_walking_up_to_a_git_folder(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Locally there is no workspace variable, so the repository's root is the nearest folder above with a `.git`."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    nested = project.root / "pkg" / "inner"
    nested.mkdir(parents=True)
    (project.root / ".git").mkdir()
    (nested / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n")
    (nested / "test_inner.py").write_text(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "the walk up")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl", str(nested))
    header, result = project.results_lines("r.jsonl")
    assert (header["root"], result["file"]) == ("pkg/inner", "test_inner.py")


@pytest.mark.covers(
    "SPC-REQ-004-10",
    "an inner run two folders below a GITHUB_WORKSPACE writes the two-part path a/b as root, and the repository's .git file counts as well as a .git folder",
)
def test_root_can_be_nested(project: Project, monkeypatch: pytest.MonkeyPatch):
    """A root of more than one folder, and a `.git` that is a file (as in a worktree or submodule)."""
    nested = project.root / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n")
    (nested / "test_nested.py").write_text(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "the nested root")\ndef test_a():\n    pass\n'
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(project.root))
    project.pytest("--speccheck-results=with-workspace.jsonl", str(nested))
    assert project.results_lines("with-workspace.jsonl")[0]["root"] == "a/b"
    monkeypatch.delenv("GITHUB_WORKSPACE")
    (project.root / ".git").write_text("gitdir: /elsewhere\n")
    project.pytest("--speccheck-results=with-git-file.jsonl", str(nested))
    assert project.results_lines("with-git-file.jsonl")[0]["root"] == "a/b"


@pytest.mark.covers(
    "SPC-REQ-004-10",
    "an inner run with no GITHUB_WORKSPACE and no .git above it writes a null root",
)
def test_root_is_null_when_no_repository_is_found(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Planted so it doesn't depend on where the system's temp folder is: no `.git` anywhere above, or the test skips."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    above = [project.root, *project.root.parents]
    if any((folder / ".git").exists() for folder in above):
        pytest.skip("the temp folder is inside a repository, so there is no folder without one to test")
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "no repository")\ndef test_a():\n    pass\n')
    project.pytest("--speccheck-results=r.jsonl")
    assert project.results_lines("r.jsonl")[0]["root"] is None


@pytest.mark.covers(
    "SPC-REQ-004-12",
    "an inner run whose GITHUB_WORKSPACE doesn't hold pytest's root, as in a container, writes the SPECCHECK_ROOT it was given as root",
)
def test_an_override_gives_root_when_it_cant_be_found(project: Project, monkeypatch: pytest.MonkeyPatch):
    """In a container the host's workspace path isn't where pytest runs; `SPECCHECK_ROOT` says where it is."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "the override")\ndef test_a():\n    pass\n')
    monkeypatch.setenv("GITHUB_WORKSPACE", "/home/runner/work/r/r")
    project.pytest("--speccheck-results=lost.jsonl")
    assert project.results_lines("lost.jsonl")[0]["root"] is None
    monkeypatch.setenv("SPECCHECK_ROOT", "sdk")
    project.pytest("--speccheck-results=given.jsonl")
    assert project.results_lines("given.jsonl")[0]["root"] == "sdk"


@pytest.mark.parametrize(
    ("given", "root"),
    [
        pytest.param(
            "sdk/",
            "sdk",
            marks=pytest.mark.covers("SPC-REQ-004-12", "SPECCHECK_ROOT=`sdk/` is written as root `sdk`"),
            id="trailing-slash",
        ),
        pytest.param(
            "/sdk",
            "sdk",
            marks=pytest.mark.covers("SPC-REQ-004-12", "SPECCHECK_ROOT=`/sdk` is written as root `sdk`"),
            id="leading-slash",
        ),
        pytest.param(
            "  sdk\n",
            "sdk",
            marks=pytest.mark.covers(
                "SPC-REQ-004-12", "SPECCHECK_ROOT padded with spaces and a newline is written as `sdk`"
            ),
            id="whitespace",
        ),
        pytest.param(
            " /a/b/ ",
            "a/b",
            marks=pytest.mark.covers(
                "SPC-REQ-004-12",
                "SPECCHECK_ROOT=` /a/b/ ` loses the whitespace, then the slashes, and keeps the inner one",
            ),
            id="nested",
        ),
        pytest.param(
            "/",
            None,
            marks=pytest.mark.covers(
                "SPC-REQ-004-12", "SPECCHECK_ROOT=`/` is empty after trimming, so it counts as not set and root is null"
            ),
            id="only-a-slash",
        ),
        pytest.param(
            "   ",
            None,
            marks=pytest.mark.covers(
                "SPC-REQ-004-12", "SPECCHECK_ROOT of only spaces counts as not set and root is null"
            ),
            id="only-spaces",
        ),
    ],
)
def test_the_override_is_trimmed(project: Project, monkeypatch: pytest.MonkeyPatch, given: str, root: str | None):
    """With the workspace somewhere else, nothing but the override can give `root`, so null means it was ignored."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "the trim")\ndef test_a():\n    pass\n')
    monkeypatch.setenv("GITHUB_WORKSPACE", "/home/runner/work/r/r")
    monkeypatch.setenv("SPECCHECK_ROOT", given)
    project.pytest("--speccheck-results=r.jsonl")
    assert project.results_lines("r.jsonl")[0]["root"] == root


@pytest.mark.parametrize(
    "given",
    [
        pytest.param(
            given,
            marks=pytest.mark.covers(
                "SPC-REQ-004-12",
                f"SPECCHECK_ROOT={given!r} is empty after trimming, so it counts as not set and root is the project's folder name from GITHUB_WORKSPACE",
            ),
            id=label,
        )
        for label, given in [("empty", ""), ("spaces", "   "), ("slash", "/"), ("slashes", "///"), ("padded", " / \n")]
    ],
)
def test_an_override_that_trims_to_nothing_falls_back_to_the_found_root(
    project: Project, monkeypatch: pytest.MonkeyPatch, given: str
):
    """Not set means not set: the root that can be worked out is used, not null and not the empty string."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "the fallback")\ndef test_a():\n    pass\n')
    monkeypatch.setenv("GITHUB_WORKSPACE", str(project.root.parent))
    monkeypatch.setenv("SPECCHECK_ROOT", given)
    project.pytest("--speccheck-results=r.jsonl")
    assert project.results_lines("r.jsonl")[0]["root"] == project.root.name


@pytest.mark.covers(
    "SPC-REQ-004-12",
    "SPECCHECK_ROOT=`//sdk//` is written as root `sdk`, and `a//b` loses nothing but its outer slashes",
)
def test_every_outer_slash_is_removed_and_inner_ones_stay(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Only the ends are trimmed, however many slashes there are."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "the slashes")\ndef test_a():\n    pass\n')
    monkeypatch.setenv("GITHUB_WORKSPACE", "/home/runner/work/r/r")
    for given, root in (("//sdk//", "sdk"), ("//a//b//", "a//b")):
        monkeypatch.setenv("SPECCHECK_ROOT", given)
        project.pytest("--speccheck-results=r.jsonl")
        assert project.results_lines("r.jsonl")[0]["root"] == root, given


@pytest.mark.covers(
    "SPC-REQ-004-12",
    "with GITHUB_WORKSPACE holding the project's parent, so the root could be worked out as the project's folder name, SPECCHECK_ROOT=sdk still wins",
)
def test_the_override_wins_over_a_root_that_can_be_found(project: Project, monkeypatch: pytest.MonkeyPatch):
    """The override is not only a fallback."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "the winner")\ndef test_a():\n    pass\n')
    monkeypatch.setenv("GITHUB_WORKSPACE", str(project.root.parent))
    project.pytest("--speccheck-results=found.jsonl")
    assert project.results_lines("found.jsonl")[0]["root"] == project.root.name
    monkeypatch.setenv("SPECCHECK_ROOT", "sdk")
    project.pytest("--speccheck-results=won.jsonl")
    assert project.results_lines("won.jsonl")[0]["root"] == "sdk"
