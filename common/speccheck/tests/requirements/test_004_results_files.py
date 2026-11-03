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
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import speccheck
from tests.requirements.conftest import EXPECTED, OUTCOMES, Project, outcomes

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
    assert any(message in p["message"] and p["path"] == "r.jsonl" for p in run.json()["problems"])
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
                "30,000 nested brackets reject the file as not JSON, and verify and report still print one object",
            ),
            id="deep-nesting",
        ),
        pytest.param(
            '{"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed", "line": '
            + "9" * 5000
            + "}",
            "digits",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02", "a 5000-digit line number rejects the file instead of crashing the integer parser"
            ),
            id="huge-number",
        ),
        pytest.param(
            '{"test": "t\\ud800", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}',
            "lone surrogate",
            marks=pytest.mark.covers(
                "SPC-REQ-004-02",
                "a test name with a lone surrogate escape rejects the file, and report still writes r.md",
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


@pytest.mark.covers("SPC-REQ-004-02", "a test ID containing U+2028 and U+0085 reads back as one line and verify passes")
def test_a_test_id_with_a_unicode_line_separator_still_reads(project: Project):
    """U+2028 and U+0085 in a test ID are written as they are, and must not split the line on read."""
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t.py::test[a\u2028b\u0085c]", ["T-REQ-001-01"], "passed")])
    done = project.speccheck("verify", "unit.jsonl")
    assert done.code == 0 and "not JSON" not in done.err


@pytest.mark.covers(
    "SPC-REQ-004-05",
    "a plain inner run writes no .jsonl, and SPECCHECK_RESULTS=out/env.jsonl writes it relative to where pytest started",
)
def test_a_file_only_when_asked(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Nothing by default; the option or SPECCHECK_RESULTS (relative to where pytest started) asks for one."""
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
    assert "Traceback" not in run.stdout.str()


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
    "SPC-REQ-004-06",
    "an inner run with -n 2 writes a single x.jsonl holding every test's real outcome from both workers",
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
    # pytester's folder is under the system temp folder, which isn't in any repository
    project.pytest("--speccheck-results=none.jsonl")
    assert project.results_lines("none.jsonl")[0]["root"] is None


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
