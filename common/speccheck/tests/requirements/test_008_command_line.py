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

"""specs/008-command-line.md: the installed `speccheck` command, as a separate process."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import speccheck
from tests.requirements.conftest import CONFIG, Project


def command(project: Project, *argv: str) -> subprocess.CompletedProcess:
    """Run the installed `speccheck` console script in the project."""
    script = shutil.which("speccheck", path=str(Path(sys.executable).parent))
    assert script, "the speccheck console script is installed with the package"
    return subprocess.run([script, *argv], cwd=project.root, capture_output=True, text=True)


@pytest.mark.covers(
    "SPC-REQ-008-01",
    "the installed command's --help shows both sections and a description beside lint, check, verify, report and record",
)
def test_help_lists_every_command_by_section(project: Project):
    """Every command is in `--help`, under its section, with a one-line description."""
    done = command(project, "--help")
    assert done.returncode == 0
    assert "Check specs and evidence:" in done.stdout and "In CI:" in done.stdout
    listed = {
        line.split()[0]: line.split(None, 1)[1:]
        for line in done.stdout.splitlines()
        if line.startswith("  ") and not line.startswith("   ") and not line.lstrip().startswith("-")
    }
    assert {"lint", "check", "verify", "report", "record"} <= set(listed)
    assert all(listed[name] for name in ("lint", "check", "verify", "report", "record"))


@pytest.mark.covers(
    "SPC-REQ-008-02",
    "each of --config, --json, --quiet and --verbose gives the same output before lint as after it",
)
def test_global_options_before_or_after(project: Project):
    """Each global option works either side of the command, and --quiet and --verbose change the output."""
    project.write("sub/c.toml", CONFIG.replace('specs = "specs"', 'specs = "../specs"'))
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    for options in (["--config", "sub/c.toml"], ["--json"], ["--quiet"], ["--verbose"]):
        before = command(project, *options, "verify", "r.jsonl")
        after = command(project, "verify", "r.jsonl", *options)
        assert before.returncode == after.returncode == 0, options
        assert (before.stdout, before.stderr) == (after.stdout, after.stderr), options
    assert json.loads(command(project, "verify", "r.jsonl", "--json").stdout)["command"] == "verify"
    plain = command(project, "verify", "r.jsonl").stdout
    assert command(project, "verify", "r.jsonl", "--quiet").stdout == "" != plain
    assert "T-REQ-001-01  passed" in command(project, "verify", "r.jsonl", "--verbose").stdout


@pytest.mark.covers(
    "SPC-REQ-008-11",
    "the installed command's --version prints speccheck and the package version",
)
def test_version_prints_the_version(project: Project):
    """`--version` prints the name and version."""
    assert command(project, "--version").stdout == f"speccheck {speccheck.__version__}\n"


@pytest.mark.covers(
    "SPC-REQ-008-03",
    "the installed command exits 0 on a clean lint, 1 on a malformed bullet, and 2 on an unknown command or missing config",
)
def test_exit_codes(project: Project):
    """0 clean, 1 problems, 2 usage or config error."""
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    assert command(project, "lint").returncode == 0
    project.spec("- T-REQ-1-1: Bad.")
    assert command(project, "lint").returncode == 1
    assert command(project, "nope").returncode == 2
    assert command(project, "lint", "--config", "missing.toml").returncode == 2


@pytest.mark.covers(
    "SPC-REQ-008-04",
    "lint, check, verify, report, an unknown command and no command each print one JSON object, and check lists each requirement",
)
def test_one_json_object_on_every_exit_path(project: Project):
    """Clean, with problems (`verify` with no results is one), and on a usage error: stdout is one object."""
    project.spec("- T-REQ-001-01: One.")
    for argv, code in (
        (["lint", "--json"], 0),
        (["check", "--json"], 1),
        (["verify", "--json"], 1),
        (["report", "--json"], 0),
        (["nope", "--json"], 2),
        (["--json"], 2),
    ):
        done = command(project, *argv)
        body = json.loads(done.stdout)
        assert done.returncode == code, argv
        assert {"schema_version", "command", "ok", "problems"} <= set(body), argv
    check = json.loads(command(project, "check", "--json").stdout)
    # `path` is the spec file from the repository's root; pytester's folder is in none, so null
    assert check["requirements"] == [
        {
            "id": "T-REQ-001-01",
            "spec": "001",
            "status": "unclaimed",
            "text": "One.",
            "path": None,
            "line": 7,
            "evidence": [],
            "waiting_on": [],
        }
    ]


@pytest.mark.covers(
    "SPC-REQ-008-13",
    "check --json at schema_version 1 still has every field that version promised, top level and per requirement",
)
def test_the_json_fields_of_schema_version_1(project: Project):
    """Removing or renaming a field fails here until `SCHEMA_VERSION` is bumped and this list is updated."""
    project.spec("- T-REQ-001-01: One.")
    body = json.loads(command(project, "check", "--json").stdout)
    assert body["schema_version"] == 1
    assert set(body) >= {"schema_version", "command", "ok", "problems", "counts", "requirements", "producers"}
    assert set(body["problems"][0]) == {"path", "line", "message", "code"}
    assert set(body["producers"]) == {"reported", "missing"}
    assert set(body["requirements"][0]) == {"id", "spec", "status", "text", "path", "line", "evidence", "waiting_on"}


@pytest.mark.covers(
    "SPC-REQ-008-04",
    "lint, check and verify problems carry codes bullet-malformed, unclaimed and no-results, with line 0 when there is none",
)
def test_each_problem_has_a_stable_code(project: Project):
    """`code` names the kind of problem, so a reader of `--json` needn't parse the message; `line` 0 means none."""
    project.spec("- T-REQ-001-01: One.\n* T-REQ-001-02: Star.")
    for argv, code in (
        (["lint", "--json"], "bullet-malformed"),
        (["check", "--json"], "unclaimed"),
        (["verify", "--json"], "no-results"),
    ):
        problems = json.loads(command(project, *argv).stdout)["problems"]
        assert code in {p["code"] for p in problems}, argv
        assert all(set(p) == {"path", "line", "message", "code"} for p in problems), argv
    verify = json.loads(command(project, "verify", "--json").stdout)["problems"]
    assert [p["line"] for p in verify if p["code"] == "no-results"] == [0]


@pytest.mark.covers(
    "SPC-REQ-008-04",
    "report --json with an output path under a plain file prints one usage-error object and no traceback",
)
def test_an_unwritable_output_is_still_one_json_object(project: Project):
    """A file in the way of the output folder is a usage error (2) as an object, not a traceback."""
    project.spec("- T-REQ-001-01: One.")
    project.write("blocker", "a file, not a folder")
    done = command(project, "report", "--json", "--output", "blocker/report.md")
    body = json.loads(done.stdout)
    assert done.returncode == 2 and body["ok"] is False and body["error"]["code"] == "usage"
    assert "blocker" in body["error"]["message"] and "Traceback" not in done.stderr


@pytest.mark.covers(
    "SPC-REQ-008-05",
    "a failing verify leaves stdout empty, starts stderr with the problem and ends it with the counts and producer unit",
)
def test_problems_on_stderr_and_a_summary_last(project: Project):
    """stdout stays clean on failure; the last line counts statuses and names the producers."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    done = command(project, "verify", "unit.jsonl")
    assert done.returncode == 1 and done.stdout == ""
    assert done.stderr.splitlines()[0].startswith("specs/001-thing.md:8: T-REQ-001-02 is not claimed")
    assert done.stderr.splitlines()[-1] == (
        "speccheck verify: 2 requirements: 1 unclaimed, 1 passed; reported: unit; 1 problem"
    )


@pytest.mark.covers(
    "SPC-REQ-008-06",
    "a malformed bullet prints as specs/001-thing.md:7: message, and a problem with no line as path: message",
)
def test_problems_are_path_line_message(project: Project):
    """A problem with a line prints `path:line: message`; one without prints `path: message`."""
    project.spec("- T-REQ-1-1: Bad.")
    done = command(project, "lint")
    assert "specs/001-thing.md:7: a bullet must read" in done.stderr
    project.spec("- T-REQ-001-01: One.")
    done = command(project, "verify")  # no results given: a problem about the config, with no line
    assert done.returncode == 1
    assert done.stderr.splitlines()[0].startswith("speccheck.toml: no results files were read")


@pytest.mark.covers(
    "SPC-REQ-008-12",
    "a file name and test names with newlines and `::error::`, and forged `::` and `##[` paths, are printed with their control characters written out",
)
def test_nothing_printed_can_start_a_log_command(project: Project):
    """Control characters are written out whether they come from a file name or from a results file."""
    project.spec("- T-REQ-1-1: Bad.")
    project.write("specs/x\n::error::evil.md", "")
    done = command(project, "lint")
    assert done.stderr.splitlines()[:-1] and all(not line.startswith("::") for line in done.stderr.splitlines())
    assert "specs/x\\n::error::evil.md: a spec file must be named" in done.stderr
    (project.root / "specs" / "x\n::error::evil.md").unlink()
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t\n::error::evil", ["T-REQ-001-01"], "failed")])
    done = command(project, "verify", "r.jsonl")
    assert done.returncode == 1 and all(not line.startswith("::") for line in done.stderr.splitlines())
    assert "t\\n::error::evil failed in unit" in done.stderr
    project.results("r.jsonl", "unit", [("::error title=x::FORGED", ["T-REQ-001-01"], "failed")])
    done = command(project, "verify", "r.jsonl")
    assert done.returncode == 1 and all(not line.lstrip().startswith("::") for line in done.stderr.splitlines())
    assert "\\x3a:error title=x::FORGED" not in done.stderr  # mid-line, so left as written
    for forged, written in [("::error::x", "\\x3a:error::x"), ("##[error]x", "##\\x5berror]x")]:
        path = project.results("r.jsonl", "unit", [("t", ["T-REQ-009-09"], "passed")])
        path.write_text(path.read_text().replace('"file": "tests/test_x.py"', f'"file": "{forged}"'))
        done = command(project, "verify", "r.jsonl")
        assert done.stderr.startswith(f"{written}:3: T-REQ-009-09 isn't in any spec") and "##[" not in done.stderr
        assert all(not line.lstrip().startswith("::") for line in done.stderr.splitlines())


SUMMARY_ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""The run the summary is written in: a report link must be under its server and repository."""
REPORT_URL = "https://github.com/o/r/actions/runs/7/artifacts/99"
"""An artifact URL of that run, as `actions/upload-artifact` gives it."""


@pytest.mark.covers(
    "SPC-REQ-008-07",
    "a passing verify appends to an earlier step's summary exactly one line of counts linking the report, and no list",
)
def test_a_passing_summary_is_one_line(project: Project):
    """On a pass the summary is the counts and the link, with nothing listed."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two. ⚠ untested")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    project.write("s.md", "an earlier step's summary\n")
    run = project.run("verify", "r.jsonl", "--summary", "s.md", "--report-url", REPORT_URL, env=SUMMARY_ENV)
    assert run.code == 0
    assert (project.root / "s.md").read_text() == (
        "an earlier step's summary\n"
        f"**speccheck:** 2 requirements: 1 passed, 1 untested. Full report: [speccheck-report]({REPORT_URL})\n\n"
    )


@pytest.mark.covers(
    "SPC-REQ-008-07",
    "a failing verify's summary gives the problem count and counts, then one entry per problem, and no table or passed rows",
)
def test_a_failing_summary_lists_only_the_problems(project: Project):
    """The problems, as the terminal prints them, after the line; nothing about what passed."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.\n- T-REQ-001-03: Three.")
    project.results(
        "r.jsonl",
        "unit",
        [("tests/t.py::test_ok", ["T-REQ-001-01"], "passed"), ("tests/t.py::test_bad", ["T-REQ-001-02"], "failed")],
    )
    run = project.run("verify", "r.jsonl", "--summary", "s.md")
    assert run.code == 1
    text = (project.root / "s.md").read_text()
    assert text.endswith("`\n\n")  # a blank line after, so a later step's summary starts its own block
    lines = text.rstrip("\n").splitlines()
    assert lines[0] == "**speccheck:** 2 problems. 3 requirements: 1 failed, 1 unclaimed, 1 passed"
    assert lines[1] == "" and len(lines) == 4
    assert lines[2].startswith(
        "- `specs/001-thing.md:8: T-REQ-001-02 has no passing result: tests/t.py::test_bad failed"
    )
    assert lines[3].startswith("- `specs/001-thing.md:9: T-REQ-001-03 is not claimed")
    assert "test_ok" not in "\n".join(lines) and "|" not in "\n".join(lines)


@pytest.mark.covers(
    "SPC-REQ-008-07",
    "lint and check take --summary too: lint lists a bad bullet, check counts a collect-only run as claimed",
)
def test_lint_and_check_write_the_same_summary(project: Project):
    """The same format from every command that decides failure."""
    project.spec("- T-REQ-001-01: One.\n* T-REQ-001-02: bad bullet")
    assert project.run("lint", "--summary", "lint.md").code == 1
    lint = (project.root / "lint.md").read_text().splitlines()
    assert lint[0] == "**speccheck:** 1 problem. 1 specs, 1 requirement"
    assert lint[2].startswith("- `specs/001-thing.md:8: a bullet must read")
    project.spec("- T-REQ-001-01: One.")
    project.results("c.jsonl", "unit", [("t", ["T-REQ-001-01"], "collected")])
    assert project.run("check", "c.jsonl", "--summary", "check.md").code == 0
    assert (project.root / "check.md").read_text() == "**speccheck:** 1 requirement: 1 claimed\n\n"


@pytest.mark.covers(
    "SPC-REQ-008-08",
    "a test name holding a link, an img tag and a backtick sits inert in one code span in the summary",
)
def test_the_summary_is_escaped(project: Project):
    """Text from a results file can't add a link or HTML to the step summary."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t[x](https://evil)<img src=x>`", ["T-REQ-001-01"], "failed")])
    project.run("verify", "r.jsonl", "--summary", "s.md")
    entry = (project.root / "s.md").read_text().splitlines()[2]
    assert entry.startswith("- `") and entry.endswith("`") and entry.count("`") == 2
    assert "t[x](https://evil)<img src=x> failed in unit" in entry


@pytest.mark.covers(
    "SPC-REQ-008-08",
    "3000 missing inputs with 420-character paths give a summary under 1 MiB, cut after a whole entry with a note",
)
def test_the_summary_stays_under_the_limit(project: Project):
    """Thousands of problems still fit GitHub's step summary limit, and the cut says so."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    # Long paths made of short parts: one part over 255 bytes is an OS error, not a missing file
    missing = [f"missing/{'y' * 200}/{'z' * 200}/{n}.jsonl" for n in range(3000)]
    assert project.run("verify", "r.jsonl", *missing, "--summary", "s.md").code == 1
    data = (project.root / "s.md").read_bytes()
    assert len(data) <= 1024 * 1024
    lines = data.decode().rstrip("\n").splitlines()
    assert lines[-1] == "- … cut to fit the step summary; the full report has every problem"
    assert 100 < len(lines) < 3000  # cut: 3000 entries of about 460 bytes are well over the limit
    assert all(line.startswith("- `") and line.endswith("`") for line in lines[2:-1])


@pytest.mark.parametrize(
    ("url", "env"),
    [
        pytest.param(
            "https://evil.example/o/r/actions/runs/7/artifacts/99",
            SUMMARY_ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-008-09", "a report URL on another server leaves the summary line without a link"
            ),
            id="other-server",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/7/job/8",
            SUMMARY_ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-008-09", "a job URL of this run, not an artifact URL, is not linked as the report"
            ),
            id="not-an-artifact",
        ),
        pytest.param(
            REPORT_URL + ")[x](https://evil",
            SUMMARY_ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-008-09", "an artifact URL with a markdown link appended is refused whole"
            ),
            id="trailing-markdown",
        ),
        pytest.param(
            REPORT_URL,
            {},
            marks=pytest.mark.covers(
                "SPC-REQ-008-09",
                "outside CI there is no run to compare with, so even a well-formed report URL isn't linked",
            ),
            id="outside-ci",
        ),
    ],
)
def test_only_this_runs_report_is_linked(project: Project, url: str, env: dict):
    """The line is written either way, without a link."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    assert project.run("verify", "r.jsonl", "--summary", "s.md", "--report-url", url, env=env).code == 0
    assert (project.root / "s.md").read_text() == "**speccheck:** 1 requirement: 1 passed\n\n"


JOB_CI = {"job": "unit", "job_id": 41, "run_url": "https://github.com/o/r/actions/runs/7"}
"""A results file's CI block from job 41."""


@pytest.mark.covers(
    "SPC-REQ-008-10",
    "verify --job-names names job 41 by its display name in the problem, the summary and --json, and without the option names its producer",
)
def test_verify_names_jobs_by_the_map(project: Project):
    """The same map as the report's, so the summary and the report name jobs alike; it is optional."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "failed")], ci=JOB_CI)
    project.write("names.json", json.dumps({"41": "unit python 3.12"}))
    named = project.run("verify", "r.jsonl", "--job-names", "names.json", "--summary", "s.md")
    assert named.code == 1 and "t failed in unit python 3.12" in named.err
    assert "t failed in unit python 3.12" in (project.root / "s.md").read_text()
    body = project.run("verify", "r.jsonl", "--job-names", "names.json", "--json").json()
    assert body["requirements"][0]["evidence"][0]["job_name"] == "unit python 3.12"
    plain = project.run("verify", "r.jsonl")
    assert "t failed in unit;" in plain.err


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(
            None,
            "--job-names names.json: can't read",
            marks=pytest.mark.covers(
                "SPC-REQ-008-10", "a --job-names file that doesn't exist exits 2 saying it can't be read"
            ),
            id="missing",
        ),
        pytest.param(
            "{not json",
            "--job-names names.json: not JSON",
            marks=pytest.mark.covers("SPC-REQ-008-10", "a --job-names file that isn't JSON exits 2"),
            id="not-json",
        ),
        pytest.param(
            '["unit"]',
            "--job-names names.json: must be a JSON object from job ID to name",
            marks=pytest.mark.covers(
                "SPC-REQ-008-10", "a --job-names list instead of an object exits 2, showing the object form"
            ),
            id="a-list",
        ),
        pytest.param(
            '{"41": 3}',
            "--job-names names.json: must be a JSON object from job ID to name",
            marks=pytest.mark.covers("SPC-REQ-008-10", "a --job-names object with a number for a name exits 2"),
            id="not-a-string",
        ),
    ],
)
def test_a_bad_job_names_file_is_a_usage_error(project: Project, content: str | None, message: str):
    """For report and verify alike: exit 2 and the message, not a traceback."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=JOB_CI)
    if content is not None:
        project.write("names.json", content)
    for command_name in ("report", "verify"):
        run = project.run(command_name, "r.jsonl", "--job-names", "names.json")
        assert run.code == 2 and message in run.err and "Traceback" not in run.err, command_name
