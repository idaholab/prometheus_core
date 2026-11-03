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
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import speccheck
from tests.requirements.conftest import CI, CONFIG, ENV, JOB, Project

CONTROLS = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f  ‪-‮⁦-⁩]")
"""Raw characters that end a line or drive a terminal, which nothing printed may hold (the final newline is fine)."""


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
    "SPC-REQ-008-01",
    "parsing --help into its sections puts lint, check and verify under Check specs and evidence and report and record under In CI, each with a one-line description",
)
def test_help_puts_each_command_under_its_section(project: Project):
    """Which section each command is under, and a description of one line, from the printed help itself."""
    sections: dict[str, dict[str, str]] = {}
    current = ""
    lines = command(project, "--help").stdout.splitlines()
    for position, line in enumerate(lines):
        if line and not line.startswith(" ") and line.endswith(":"):
            current = line[:-1]
            sections[current] = {}
        elif line.startswith("  ") and not line.startswith("   ") and current and line.split()[0][0].isalpha():
            name, _, description = line.strip().partition("  ")
            sections[current][name] = description.strip()
            # A description wrapped onto the next line would be a second line
            following = lines[position + 1] if position + 1 < len(lines) else ""
            assert not following.startswith("   "), f"{name}'s description runs over a line: {following!r}"
    assert set(sections["Check specs and evidence"]) == {"lint", "check", "verify"}
    assert set(sections["In CI"]) == {"report", "record"}
    commands = {name: text for group in ("Check specs and evidence", "In CI") for name, text in sections[group].items()}
    assert all(text and "\n" not in text for text in commands.values()), commands


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
    "SPC-REQ-008-02",
    "with no default config at all, lint, check and report succeed only when --config alt.toml is given, before or after the command, and a missing --config path exits 2 in both places",
)
def test_config_option_is_what_finds_the_config(project: Project):
    """Nothing but `alt.toml` can configure the run, so a `--config` that was ignored would exit 2."""
    (project.root / "speccheck.toml").unlink()
    project.write("alt.toml", CONFIG)
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    for argv in (["lint"], ["check", "r.jsonl"], ["report", "--output", "out.md", "r.jsonl"]):
        assert command(project, *argv).returncode == 2, argv  # no config to find
        before = command(project, "--config", "alt.toml", *argv)
        after = command(project, *argv, "--config", "alt.toml")
        assert before.returncode == after.returncode == 0, (argv, before.stderr, after.stderr)
        assert (before.stdout, before.stderr) == (after.stdout, after.stderr), argv
    for argv in (["--config", "nope.toml", "lint"], ["lint", "--config", "nope.toml"]):
        assert command(project, *argv).returncode == 2, argv


@pytest.mark.covers(
    "SPC-REQ-008-11",
    "the installed command's --version prints speccheck and the package version",
)
def test_version_prints_the_version(project: Project):
    """`--version` prints the name and version."""
    done = command(project, "--version")
    assert done.returncode == 0 and done.stdout == f"speccheck {speccheck.__version__}\n"


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
    "SPC-REQ-008-03",
    "check and verify exit 0 when every requirement is claimed and passed, and 1 when one is not, and report writes its file and exits 0 on the same inputs that make verify exit 1",
)
def test_exit_codes_of_check_verify_and_report(project: Project):
    """0 without problems and 1 with, for each command that decides; `report` is 0 either way."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("good.jsonl", "unit", [("t1", ["T-REQ-001-01"], "passed"), ("t2", ["T-REQ-001-02"], "passed")])
    project.results("bad.jsonl", "unit", [("t1", ["T-REQ-001-01"], "passed"), ("t2", ["T-REQ-001-02"], "failed")])
    for name in ("check", "verify"):
        assert command(project, name, "good.jsonl").returncode == 0, name
        assert command(project, name, "nope.jsonl").returncode == 1, name
    assert command(project, "verify", "bad.jsonl").returncode == 1
    done = command(project, "report", "bad.jsonl", "--output", "r.md")
    assert done.returncode == 0 and (project.root / "r.md").is_file()


@pytest.mark.covers(
    "SPC-REQ-008-03",
    "an unknown option, a malformed config and a --job-names file that is not JSON each exit 2",
)
def test_exit_2_for_a_usage_or_config_error(project: Project):
    """A usage error, a config error and a bad option value all exit 2, not 1."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    assert command(project, "lint", "--bogus").returncode == 2
    project.write("broken.toml", "specs = \n")
    assert command(project, "lint", "--config", "broken.toml").returncode == 2
    project.write("names.json", "not json")
    for name in ("verify", "report"):
        assert command(project, name, "r.jsonl", "--job-names", "names.json").returncode == 2, name


@pytest.mark.covers(
    "SPC-REQ-008-04",
    "verify and report --json of a passing result give ok true and one requirement with its ID, status passed and one evidence entry",
)
def test_verify_and_report_json_carry_the_evidence(project: Project):
    """`ok` is true when nothing is wrong, and each requirement lists what proves it."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], "passed")])
    for name in ("verify", "report"):
        body = json.loads(command(project, name, "r.jsonl", "--json").stdout)
        assert body["ok"] is True and body["problems"] == [], name
        [requirement] = body["requirements"]
        assert (requirement["id"], requirement["status"]) == ("T-REQ-001-01", "passed"), name
        [evidence] = requirement["evidence"]
        assert (evidence["test"], evidence["outcome"], evidence["producer"]) == (
            "tests/t.py::test_a",
            "passed",
            "unit",
        ), name


@pytest.mark.covers(
    "SPC-REQ-008-04",
    "a missing config and an unknown option, each with --json, print one object with ok false and exit 2",
)
def test_json_on_a_usage_error_before_any_command_runs(project: Project):
    """The error paths that fail before the command's own work: still exactly one object."""
    for argv in (["lint", "--config", "missing.toml", "--json"], ["lint", "--bogus", "--json"]):
        done = command(project, *argv)
        body = json.loads(done.stdout)
        assert done.returncode == 2 and body["ok"] is False, argv
        assert {"schema_version", "command", "ok", "problems"} <= set(body), argv
        assert "Traceback" not in done.stderr
    project.write("broken.toml", "specs = \n")
    done = command(project, "lint", "--config", "broken.toml", "--json")
    assert done.returncode == 2 and json.loads(done.stdout)["ok"] is False


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
    assert len(check["requirements"]) == 1
    promised(
        check["requirements"][0],
        {
            "id": "T-REQ-001-01",
            "spec": "001",
            "status": "unclaimed",
            "text": "One.",
            "path": None,
            "line": 7,
            "evidence": [],
            "waiting_on": [],
        },
        "check.requirements[0]",
    )


def promised(actual: object, snapshot: object, where: str = "body") -> None:
    """Fail unless `actual` has everything `snapshot` promises, with the same value or type, and allow extra fields.

    A snapshot value that is a type means "a value of that type"; a dict is checked key by key, so a field
    added to `actual` passes (008-13 allows it) while a removed or retyped one fails.
    """
    if isinstance(snapshot, dict):
        assert isinstance(actual, dict), f"{where} is not an object"
        for key, value in snapshot.items():
            assert key in actual, f"{where}.{key} was removed"
            promised(actual[key], value, f"{where}.{key}")
    elif isinstance(snapshot, type):
        assert isinstance(actual, snapshot), f"{where} is {actual!r}, not a {snapshot.__name__}"
    else:
        assert actual == snapshot, f"{where} changed: {actual!r} != {snapshot!r}"


COUNTS = dict.fromkeys(("claimed", "failed", "not run", "passed", "planned", "retired", "unclaimed", "untested"), int)
"""The keys of `counts`, each a count."""
PROBLEM = {"path": str, "line": int, "message": str, "code": str}
"""A problem's fields."""
EVIDENCE = {
    "producer": str,
    "test": str,
    "kind": str,
    "outcome": str,
    "how": str,
    "file": str,
    "line": int,
    "job": str,
    "job_name": str,
    "url": str,
    "root": None,
}
"""One evidence entry's fields; `root` is null here because the results file gave none."""
REQUIREMENT = {
    "id": str,
    "spec": str,
    "status": str,
    "text": str,
    "path": None,
    "line": int,
    "evidence": list,
    "waiting_on": list,
}
"""One requirement's fields; `path` is null because the test project isn't in a repository."""
CHECKING = {
    "schema_version": 1,
    "ok": bool,
    "problems": list,
    "counts": COUNTS,
    "requirements": list,
    "producers": {"reported": list, "missing": list},
}
"""What `check`, `verify` and `report` all promise at the top level."""


@pytest.mark.covers(
    "SPC-REQ-008-04",
    "check, verify and report --json each give both requirements an id, a status and an evidence list, whose entry for the passing one holds its producer, test and outcome",
)
@pytest.mark.covers(
    "SPC-REQ-008-13",
    "check, verify and report --json at schema_version 1 each still have every promised field, with its type, in the top level, counts, problems, producers, requirements and evidence; extra fields are ignored",
)
def test_the_json_fields_of_schema_version_1(project: Project):
    """Removing or retyping a promised field fails here until `SCHEMA_VERSION` is bumped and the snapshot updated."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("u.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], "passed")], ci=CI)
    project.write("names.json", json.dumps({"8": "unit python 3.12"}))
    for argv in (
        ["check", "u.jsonl"],
        ["verify", "u.jsonl", "--job-names", "names.json"],
        ["report", "u.jsonl"],
    ):
        body = json.loads(command(project, *argv, "--json").stdout)
        promised(body, {**CHECKING, "command": argv[0]}, argv[0])
        promised(body["problems"][0], PROBLEM, f"{argv[0]}.problems[0]")
        first, second = body["requirements"]
        promised(first, {**REQUIREMENT, "id": "T-REQ-001-01", "status": "claimed" if argv[0] == "check" else "passed"})
        promised(second, {**REQUIREMENT, "id": "T-REQ-001-02", "status": "unclaimed", "evidence": []})
        promised(first["evidence"][0], {**EVIDENCE, "outcome": "passed", "kind": "test", "producer": "unit"})
    # Only `verify` read the job names, so only it names the job
    verify = json.loads(command(project, "verify", "u.jsonl", "--job-names", "names.json", "--json").stdout)
    assert verify["requirements"][0]["evidence"][0]["job_name"] == "unit python 3.12"
    assert json.loads(command(project, "report", "u.jsonl", "--json").stdout)["title"] == "speccheck requirements"


@pytest.mark.covers(
    "SPC-REQ-008-13",
    "lint --json at schema_version 1 still has its command, ok, problems, requirement_count and per-spec number, title, status and requirement_count",
)
def test_the_lint_json_fields_of_schema_version_1(project: Project):
    """`lint` has its own envelope, with no counts or requirements list."""
    project.spec("- T-REQ-001-01: One.")
    body = json.loads(command(project, "lint", "--json").stdout)
    promised(body, {"schema_version": 1, "command": "lint", "ok": True, "problems": [], "requirement_count": 1})
    promised(
        body["specs"][0],
        {"number": "001", "title": "Thing", "status": "draft", "requirement_count": 1},
        "lint.specs[0]",
    )


@pytest.mark.covers(
    "SPC-REQ-008-13",
    "an unknown command and a missing config under --json at schema_version 1 each still give an error object with code `usage` and a message, and ok false",
)
def test_the_error_object_of_schema_version_1(project: Project):
    """A usage error is still one object, with its `error` field."""
    for argv in (["nope", "--json"], ["lint", "--config", "missing.toml", "--json"]):
        body = json.loads(command(project, *argv).stdout)
        promised(
            body,
            {"schema_version": 1, "ok": False, "problems": [], "error": {"code": "usage", "message": str}},
            argv[0],
        )


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
        assert all({"path", "line", "message", "code"} <= set(p) for p in problems), argv
    verify = json.loads(command(project, "verify", "--json").stdout)["problems"]
    assert [p["line"] for p in verify if p["code"] == "no-results"] == [0]


@pytest.mark.covers(
    "SPC-REQ-008-03",
    "report with an output path under a plain file exits 2",
)
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


@pytest.mark.parametrize(
    ("name", "written"),
    [
        pytest.param(
            name,
            written,
            marks=pytest.mark.covers(
                "SPC-REQ-008-12",
                f"a failing test named {name!r} is printed by verify as {written!r}, with no raw control character on stdout or stderr",
            ),
            id=label,
        )
        for label, name, written in [
            ("escape", "t\x1b[31mred", "t\\x1b[31mred"),
            ("carriage-return", "t\rforged", "t\\rforged"),
            ("c1-control", "t\x85next", "t\\x85next"),
            ("line-separator", "t\u2028next", "t\\u2028next"),
            ("backspace-and-nul", "t\x08\x00", "t\\x08\\x00"),
            ("bidi", "t\u202eevil", "t\\u202eevil"),
        ]
    ],
)
def test_control_characters_in_a_test_name_are_written_out(project: Project, name: str, written: str):
    """The name's control characters are written as escapes on stderr, and no raw one reaches either stream."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [(name, ["T-REQ-001-01"], "failed")])
    for flags in ([], ["--verbose"]):
        done = command(project, "verify", "r.jsonl", *flags)
        for stream in (done.stdout, done.stderr):
            assert not CONTROLS.search(stream), repr(stream)
        assert f"{written} failed in unit" in done.stderr, repr(done.stderr)


@pytest.mark.covers(
    "SPC-REQ-008-12",
    "a --config file named with a newline and ::error:: is printed in the usage error with the newline written \\n",
)
def test_a_config_name_cant_start_a_log_command(project: Project):
    """The error() path, which prints the name the user gave."""
    done = command(project, "lint", "--config", "a\n::error::.toml")
    assert done.returncode == 2
    assert not CONTROLS.search(done.stdout + done.stderr)
    assert "a\\n::error::.toml" in done.stderr
    assert all(not line.lstrip().startswith("::") for line in done.stderr.splitlines())


@pytest.mark.covers(
    "SPC-REQ-008-12",
    "report to stdout for a test named with an escape and a carriage return prints the escape as \\x1b and no raw carriage return",
)
def test_report_on_stdout_writes_control_characters_out(project: Project):
    """The report's stdout path is not the problem list's, so it is tried too."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t\x1b[31m\rx", ["T-REQ-001-01"], "passed")])
    done = command(project, "report", "r.jsonl")
    assert done.returncode == 0 and not CONTROLS.search(done.stdout + done.stderr)
    # The report collapses whitespace, so the carriage return becomes a space; the escape is written out
    assert "`t\\x1b[31m x`" in done.stdout


SUMMARY_ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""The run the summary is written in: a report link must be under its server and repository."""
REPORT_URL = "https://github.com/o/r/actions/runs/7/artifacts/99"
"""An artifact URL of that run, as `actions/upload-artifact` gives it."""


@pytest.mark.covers(
    "SPC-REQ-008-09",
    "an artifact URL of this run's server and repository is linked as speccheck-report in the summary line",
)
def test_this_runs_report_is_linked(project: Project):
    """The positive case beside the refusals below: the same URL, under the run's own repository."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.run("verify", "r.jsonl", "--summary", "s.md", "--report-url", REPORT_URL, env=SUMMARY_ENV)
    assert run.code == 0
    assert f"Full report: [speccheck-report]({REPORT_URL})" in (project.root / "s.md").read_text()


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
    "SPC-REQ-008-07",
    "a failing verify's summary line gives the problem count and then exactly the counts its terminal summary line gives",
)
def test_the_summary_counts_are_the_terminals(project: Project):
    """Compared with what is printed, not with a copy of it written into the test."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.\n- T-REQ-001-03: Three.\n- T-REQ-001-04: Four. ⚠ untested")
    project.results(
        "r.jsonl",
        "unit",
        [("t1", ["T-REQ-001-01"], "passed"), ("t2", ["T-REQ-001-02"], "failed")],
    )
    done = project.run("verify", "r.jsonl", "--summary", "s.md")
    assert done.code == 1
    terminal = done.err.splitlines()[-1]
    counts = terminal.removeprefix("speccheck verify: ").split("; ")[0]
    problems = int(terminal.rsplit("; ", 1)[1].split()[0])
    line = (project.root / "s.md").read_text().splitlines()[0]
    assert line == f"**speccheck:** {problems} problems. {counts}"


@pytest.mark.covers(
    "SPC-REQ-008-07",
    "check with an unclaimed requirement writes a summary line with its problem count and the counts its terminal line gives, and one entry for it",
)
def test_a_failing_check_writes_its_summary(project: Project):
    """The `check` command's own failing summary, not only `lint`'s and `verify`'s."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("c.jsonl", "unit", [("t", ["T-REQ-001-01"], "collected")])
    done = project.run("check", "c.jsonl", "--summary", "s.md")
    assert done.code == 1
    counts = done.err.splitlines()[-1].removeprefix("speccheck check: ").split("; ")[0]
    lines = (project.root / "s.md").read_text().rstrip("\n").splitlines()
    assert lines[0] == f"**speccheck:** 1 problem. {counts}"
    assert len(lines) == 3 and lines[2].startswith("- `specs/001-thing.md:8: T-REQ-001-02 is not claimed")


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


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            name,
            marks=pytest.mark.covers(
                "SPC-REQ-008-08", f"a failing test named {name!r} sits in one code span on one summary line"
            ),
            id=label,
        )
        for label, name in [
            ("autolink", "t<https://evil.example>"),
            ("emphasis", "t*x*_y_"),
            ("heading", "# t"),
            ("quote", "> t"),
            ("newline", "t\n- injected item\n# heading"),
            ("escape", "t\x1b[31m"),
            ("pipe", "t|u"),
        ]
    ],
)
def test_a_test_name_stays_in_its_summary_entry(project: Project, name: str):
    """Whatever the name holds, the entry is one line holding one code span, and nothing after it adds an element."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [(name, ["T-REQ-001-01"], "failed")])
    project.run("verify", "r.jsonl", "--summary", "s.md")
    lines = (project.root / "s.md").read_text().rstrip("\n").splitlines()
    assert len(lines) == 3, lines  # the line, a blank, and the one entry
    assert lines[2].startswith("- `") and lines[2].endswith("`") and lines[2].count("`") == 2
    assert "\n" not in lines[2] and "\x1b" not in lines[2]


@pytest.mark.covers(
    "SPC-REQ-008-08",
    "a job display name from --job-names, holding a link, emphasis and a newline, stays inside the code span",
)
def test_a_job_name_stays_in_its_summary_entry(project: Project):
    """The display name appears in the problem, so it is inside the entry's one code span."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "failed")], ci=JOB_CI)
    project.write("names.json", json.dumps({"41": "<https://evil.example> *x*\n- item"}))
    project.run("verify", "r.jsonl", "--job-names", "names.json", "--summary", "s.md")
    lines = (project.root / "s.md").read_text().rstrip("\n").splitlines()
    assert len(lines) == 3 and lines[2].startswith("- `") and lines[2].endswith("`") and lines[2].count("`") == 2
    assert "<https://evil.example> *x* - item" in lines[2]


@pytest.mark.covers("SPC-REQ-008-08", "a few problems that fit give a summary with no cut note")
def test_no_cut_note_when_everything_fits(project: Project):
    """The note is only for a cut summary."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    assert project.run("verify", "r.jsonl", "nope.jsonl", "--summary", "s.md").code == 1
    text = (project.root / "s.md").read_text()
    assert "cut to fit" not in text and "nope.jsonl" in text


@pytest.mark.covers(
    "SPC-REQ-008-08",
    "3000 missing inputs with 3-byte-letter paths, under 1 MiB in characters but over it in bytes, give a summary under 1 MiB",
)
def test_the_summary_limit_counts_bytes(project: Project):
    """The limit is on the size of the file, so characters that take three bytes must count as three."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    # 'あ' is 3 bytes; a part of 80 is 240 bytes, under the 255-byte file name limit
    missing = [f"missing/{'あ' * 80}/{'あ' * 80}/{n}.jsonl" for n in range(3000)]
    assert project.run("verify", "r.jsonl", *missing, "--summary", "s.md").code == 1
    data = (project.root / "s.md").read_bytes()
    assert len(data) <= 1024 * 1024
    assert data.decode().rstrip("\n").splitlines()[-1].startswith("- … cut to fit")


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
        pytest.param(
            "https://github.com/o/r2/actions/runs/7/artifacts/99",
            SUMMARY_ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-008-09", "an artifact URL in repository o/r2, which starts with o/r, leaves the line unlinked"
            ),
            id="prefix-repository",
        ),
        pytest.param(
            "http://github.com/o/r/actions/runs/7/artifacts/99",
            SUMMARY_ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-008-09", "an artifact URL using http instead of the run's https leaves the line unlinked"
            ),
            id="http-scheme",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/7/artifacts/99/extra",
            SUMMARY_ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-008-09", "an artifact URL with a further path part leaves the line unlinked"
            ),
            id="extra-path",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/7/artifacts/abc",
            SUMMARY_ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-008-09", "an artifact URL whose artifact ID isn't digits leaves the line unlinked"
            ),
            id="non-digit-id",
        ),
        pytest.param(
            REPORT_URL,
            {"CI_SERVER_URL": "https://github.com", "CI_PROJECT_PATH": "o/r"},
            marks=pytest.mark.covers(
                "SPC-REQ-008-09",
                "with only GitLab-style variables set, which name no supported provider, the line has no link",
            ),
            id="gitlab-style-env",
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
        pytest.param(
            '"unit"',
            "--job-names names.json: must be a JSON object from job ID to name",
            marks=pytest.mark.covers("SPC-REQ-008-10", "a --job-names file holding a bare JSON string exits 2"),
            id="a-string",
        ),
        pytest.param(
            "null",
            "--job-names names.json: must be a JSON object from job ID to name",
            marks=pytest.mark.covers("SPC-REQ-008-10", "a --job-names file holding JSON null exits 2"),
            id="null",
        ),
        pytest.param(
            b"\xff\xfe{}",
            "--job-names names.json: ",
            marks=pytest.mark.covers(
                "SPC-REQ-008-10", "a --job-names file that is not UTF-8 text exits 2, no traceback"
            ),
            id="not-utf-8",
        ),
    ],
)
def test_a_bad_job_names_file_is_a_usage_error(project: Project, content: str | bytes | None, message: str):
    """For report and verify alike: exit 2 and the message, not a traceback."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=JOB_CI)
    if isinstance(content, bytes):
        (project.root / "names.json").write_bytes(content)
    elif content is not None:
        project.write("names.json", content)
    for command_name in ("report", "verify"):
        run = project.run(command_name, "r.jsonl", "--job-names", "names.json")
        assert run.code == 2 and message in run.err and "Traceback" not in run.err, command_name


@pytest.mark.covers(
    "SPC-REQ-008-10",
    "without --job-names, or for a job ID the names don't list, a result is named by its producer, and still linked",
)
def test_without_a_name_a_result_is_named_by_its_producer(reported: Project):
    """The names are optional: a plain list of results files still gives a readable report."""
    reported.write("names.json", json.dumps({"999": "someone else"}))
    for extra in ([], ["--job-names", "names.json"]):
        text = reported.speccheck("report", "unit.jsonl", *extra, env=ENV).out
        assert "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/job/8)" in text, extra


@pytest.mark.covers(
    "SPC-REQ-008-10",
    "report with a map listing job 8 names the result by that display name, and with a map listing only job 99 names it by its producer",
)
def test_report_names_a_job_by_the_map_when_it_lists_it(reported: Project):
    """The positive case for `report`, beside the unlisted one."""
    reported.write("listed.json", json.dumps({"8": "unit python 3.12"}))
    reported.write("unlisted.json", json.dumps({"99": "someone else"}))
    listed = reported.speccheck("report", "unit.jsonl", "--job-names", "listed.json", env=ENV).out
    assert "- ✅ passed in [unit python 3.12](https://github.com/o/r/actions/runs/7/job/8)" in listed
    unlisted = reported.speccheck("report", "unit.jsonl", "--job-names", "unlisted.json", env=ENV).out
    assert "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/job/8)" in unlisted
    assert "someone else" not in unlisted


@pytest.mark.covers(
    "SPC-REQ-008-10",
    "verify with a map that doesn't list job 41 names the failing result by its producer in the problem, and its job_name in --json is empty",
)
def test_verify_names_an_unlisted_job_by_its_producer(project: Project):
    """The map is by job ID; one without an entry for this job leaves the producer's name."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "failed")], ci=JOB_CI)
    project.write("names.json", json.dumps({"7": "another job"}))
    run = project.run("verify", "r.jsonl", "--job-names", "names.json")
    assert run.code == 1 and "t failed in unit;" in run.err and "another job" not in run.err
    body = project.run("verify", "r.jsonl", "--job-names", "names.json", "--json").json()
    assert body["requirements"][0]["evidence"][0]["job_name"] == ""


@pytest.mark.covers(
    "SPC-REQ-008-05",
    "a verify of two configured producers where only unit reported prints reported: unit; missing: nightly; and the problem count as its last line",
)
def test_the_summary_line_names_missing_producers(project: Project):
    """The producers that reported, and those that did not, in the last line."""
    project.write(
        "speccheck.toml",
        'specs = "specs"\nid-prefix = "T"\n[producers.unit]\nworkflows = ["ci"]\n[producers.nightly]\nworkflows = ["ci"]\n',
    )
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    done = command(project, "verify", "unit.jsonl", "--complete")
    assert done.returncode == 1 and done.stdout == ""
    last = done.stderr.splitlines()[-1]
    assert last.startswith("speccheck verify: 1 requirement: 1 passed; reported: unit; missing: nightly; ")
    assert last.endswith(" problem") or last.endswith(" problems")


@pytest.mark.covers(
    "SPC-REQ-008-05",
    "a clean lint, check and verify each print their summary as the last line of stdout and nothing on stderr",
)
def test_a_clean_run_ends_with_its_summary_on_stdout(project: Project):
    """The same last-line rule for every command that checks, when nothing is wrong."""
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    expected = {
        "lint": "speccheck lint: 1 specs, 1 requirement",
        "check": "speccheck check: 1 requirement: 1 claimed; reported: unit",
        "verify": "speccheck verify: 1 requirement: 1 passed; reported: unit",
    }
    for name, line in expected.items():
        argv = [name] if name == "lint" else [name, "r.jsonl"]
        done = command(project, *argv)
        assert done.returncode == 0 and done.stderr == "", name
        assert done.stdout.splitlines()[-1] == line, name


@pytest.mark.covers(
    "SPC-REQ-008-05",
    "lint with a malformed bullet and check with an unclaimed requirement print their problems on stderr and end stderr with their summary and the problem count",
)
def test_a_failing_lint_and_check_end_with_their_summary(project: Project):
    """Problems on stderr and the last line there, with the number of problems, for `lint` and `check`."""
    project.spec("- T-REQ-001-01: One.\n* T-REQ-001-02: Star.")
    done = command(project, "lint")
    assert done.returncode == 1 and done.stdout == ""
    assert done.stderr.splitlines()[-1] == "speccheck lint: 1 specs, 1 requirement; 1 problem"
    project.spec("- T-REQ-001-01: One.")
    project.results("c.jsonl", "unit", [("t", ["T-REQ-001-02"], "collected")])
    done = command(project, "check", "c.jsonl")
    assert done.returncode == 1 and done.stdout == ""
    # The unknown ID the results claim, and the requirement nothing claims
    assert done.stderr.splitlines()[-1] == "speccheck check: 1 requirement: 1 unclaimed; reported: unit; 2 problems"


@pytest.mark.covers("SPC-REQ-008-03", "record with an output path under a plain file exits 2 instead of writing")
@pytest.mark.covers(
    "SPC-REQ-008-04",
    "record --json with an unwritable output prints one object with ok false and a usage error, not a traceback",
)
def test_record_to_an_unwritable_path_is_an_error_object(ci_project: Project):
    """A file where the output folder should be: exit 2 and one JSON object, not a traceback."""
    ci_project.write("blocker", "a file, not a folder")
    run = ci_project.speccheck("record", "--output", "blocker/publish.jsonl", "--json", env=JOB)
    body = run.json()
    assert run.code == 2 and body["ok"] is False and body["error"]["code"] == "usage"
    assert "blocker" in body["error"]["message"] and "Traceback" not in run.err
