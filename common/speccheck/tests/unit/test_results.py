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

"""The results file: writing, reading and validating it."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from speccheck import results
from speccheck.claims import Claim

SCHEMA_FILE = Path(results.__file__).parent / "schema" / "speccheck-results-1.schema.json"
"""The JSON Schema that ships with the package."""


def sample() -> results.ResultsFile:
    """A results file with one test and one CI job result."""
    return results.ResultsFile(
        producer="unit",
        runner="pytest 9",
        ci={"run_id": 1, "job_id": 2},
        root="sub",
        started="2026-11-01T00:00:00Z",
        results=[
            results.Result(
                test="tests/test_x.py::test_a",
                covers=[Claim("T-REQ-001-01", "test_a writes the file")],
                outcome="passed",
                file="tests/test_x.py",
                line=3,
            ),
            results.Result(
                test="publish", covers=[Claim("T-REQ-001-02", "the job publishes")], outcome="passed", kind="ci"
            ),
        ],
    )


def header(**change) -> str:
    """A header line, with some keys changed."""
    return json.dumps({"schema": results.SCHEMA, "producer": "unit", **change})


def parse_lines(*lines: str):
    """Parse a file made of the given lines."""
    return results.parse("\n".join(lines) + "\n", "r.jsonl")


class TestFormat:
    """JSON Lines with a versioned header, and the schema file."""

    def test_round_trip(self, tmp_path: Path):
        """A written file reads back the same."""
        path = tmp_path / "out" / "r.jsonl"
        results.write(path, sample())
        lines = path.read_text().splitlines()
        assert json.loads(lines[0])["schema"] == results.SCHEMA
        assert len(lines) == 3
        parsed, problems = results.read(path)
        assert problems == []
        assert parsed.producer == "unit" and parsed.ci == {"run_id": 1, "job_id": 2} and parsed.root == "sub"
        assert [r.to_json() for r in parsed.results] == [r.to_json() for r in sample().results]
        assert parsed.source == path.as_posix()

    def test_defaults_are_left_out(self):
        """A result line carries `file`, `line` and `kind` only when they aren't the defaults."""
        assert results.Result("t", [Claim("X", "h")], "passed").to_json() == {
            "test": "t",
            "covers": [{"id": "X", "how": "h"}],
            "outcome": "passed",
        }
        full = results.Result("t", [Claim("X", "h")], "passed", file="f.py", line=2, kind="ci").to_json()
        assert (full["file"], full["line"], full["kind"]) == ("f.py", 2, "ci")

    def test_dumps(self):
        """One sorted-key JSON object per line, header first, non-ASCII kept as is."""
        text = results.dumps(
            results.ResultsFile(producer="é", results=[results.Result("t", [Claim("X", "h")], "passed")])
        )
        assert text.splitlines() == [
            '{"ci": null, "producer": "é", "root": null, "runner": "", "schema": "speccheck-results/1", "started": ""}',
            '{"covers": [{"how": "h", "id": "X"}], "outcome": "passed", "test": "t"}',
        ]

    def test_the_schema_ships_and_describes_the_format(self):
        """Runners in other languages validate against it."""
        schema = json.loads(SCHEMA_FILE.read_text())
        assert schema["$defs"]["header"]["properties"]["schema"]["const"] == results.SCHEMA
        assert schema["$defs"]["result"]["properties"]["outcome"]["enum"] == list(results.OUTCOMES)
        assert set(schema["$defs"]["header"]["properties"]) == results.HEADER_KEYS
        assert set(schema["$defs"]["result"]["properties"]) == results.RESULT_KEYS
        assert set(schema["$defs"]["ci"]["properties"]) == results.CI_KEYS
        assert set(schema["$defs"]["claim"]["properties"]) == results.CLAIM_KEYS

    def test_the_explanation_limit_is_the_text_limit(self):
        """The reader caps `how` with the general text cap, so the two must agree."""
        from speccheck.claims import MAX_HOW

        assert results.MAX_TEXT == MAX_HOW

    @pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85"])
    def test_a_line_separator_inside_a_test_id_survives(self, separator: str):
        """Only "\\n" ends a line: `dumps` leaves these three unescaped, and splitlines() would cut the line."""
        test = f"t.py::test[a{separator}b]"
        written = results.dumps(
            results.ResultsFile(producer="unit", results=[results.Result(test, [Claim("X", "h")], "passed")])
        )
        parsed, problems = results.parse(written, "r.jsonl")
        assert problems == [] and [r.test for r in parsed.results] == [test]

    def test_the_last_line_needs_no_newline(self):
        """A file cut off after its last line, with no "\\n", still reads."""
        text = header() + "\n" + json.dumps({"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed"})
        parsed, problems = results.parse(text, "r.jsonl")
        assert problems == [] and len(parsed.results) == 1

    def test_blank_lines_are_skipped(self):
        """A trailing blank line is harmless."""
        parsed, problems = parse_lines(
            header(), "", json.dumps({"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed"})
        )
        assert problems == [] and len(parsed.results) == 1


class TestValidation:
    """A bad file is a problem, and none of its results count."""

    @pytest.mark.parametrize(
        ("lines", "message"),
        [
            ([], "empty results file"),
            (["{"], "1: not JSON"),
            (["[]"], "the first line must be the header"),
            ([header(schema="speccheck-results/2")], "this speccheck reads only 'speccheck-results/1'"),
            ([header(producer="")], "`producer` must not be empty"),
            ([header(producer=3)], "`producer` must be a string"),
            ([header(root=3)], "`root` must be a string"),
            ([header(runner="x" * 1001)], "`runner` is longer than 1000"),
            ([header(ci=[])], "`ci` must be an object or null"),
            ([header(ci={"run_id": [1]})], "`ci.run_id` must be a string, a number or null"),
            ([header(ci={"run_id": True})], "`ci.run_id` must be a string, a number or null"),
            ([header(ci={"job": "x" * 1001})], "`ci.job` is longer"),
            ([header(), "[]"], "2: not a valid speccheck-results/1 line: a result must be an object"),
            ([header(), '{"test": "t", "covers": [], "outcome": "passed"}'], "`covers` must be a list of 1 to 200"),
            ([header(), '{"test": "t", "covers": "X", "outcome": "passed"}'], "`covers` must be a list"),
            (
                [header(), '{"test": "t", "covers": ["X"], "outcome": "passed"}'],
                "each `covers` entry must be an object",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "", "how": "h"}], "outcome": "passed"}'],
                "`covers[].id` must not be empty",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": ""}], "outcome": "passed"}'],
                "`covers[].how` must not be empty",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": 3}], "outcome": "passed"}'],
                "`covers[].how` must be a string",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": "a\\nb"}], "outcome": "passed"}'],
                "`covers[].how` for X has a line break",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": "' + "x" * 1001 + '"}], "outcome": "passed"}'],
                "`covers[].how` is longer than 1000",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": "  tBd "}], "outcome": "passed"}'],
                "the explanation for X is a placeholder ('tBd')",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": " x "}], "outcome": "passed"}'],
                "the explanation for X is just the ID",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": "   "}], "outcome": "passed"}'],
                "the explanation for X is empty",
            ),
            (
                [
                    header(),
                    '{"test": "t", "covers": [{"id": "X", "how": "a"}, {"id": "X", "how": "b"}], "outcome": "passed"}',
                ],
                "`covers` claims X more than once",
            ),
            ([header(), '{"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "ok"}'], "`outcome` is 'ok'"),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed", "kind": "x"}'],
                "`kind` must be one of",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed", "line": -1}'],
                "`line` must be a whole",
            ),
            (
                [header(), '{"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed", "line": true}'],
                "`line` must be a whole",
            ),
            (
                [header(), '{"test": "", "covers": [{"id": "X", "how": "h"}], "outcome": "passed"}'],
                "`test` must not be empty",
            ),
            ([header(), '{"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed"}', "{"], "3: not JSON"),
            # Python before 3.14 raises RecursionError ("not JSON this reader accepts: nested too deeply");
            # 3.14 parses deeper and reports the unclosed bracket ("not JSON: Expecting value")
            ([header(), "[" * 30000], "2: not JSON"),
            (
                [
                    header(),
                    '{"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed", "line": '
                    + "9" * 5000
                    + "}",
                ],
                "2: not JSON this reader accepts: Exceeds the limit",
            ),
            (
                [header(), '{"test": "\\ud800", "covers": [{"id": "X", "how": "h"}], "outcome": "passed"}'],
                "`test` has a lone surrogate",
            ),
            ([header(runner="\udfff")], "`runner` has a lone surrogate"),
        ],
    )
    def test_rejected(self, lines: list[str], message: str):
        """Each rule, with the line it's on."""
        parsed, problems = parse_lines(*lines) if lines else results.parse("", "r.jsonl")
        assert parsed is None
        assert len(problems) == 1 and message in str(problems[0]), problems

    def test_unknown_keys_are_dropped(self):
        """A key this speccheck doesn't read, at any level, is dropped unread rather than rejected."""
        parsed, problems = parse_lines(
            header(extra=[1], ci={"job": "unit", "leg": "3.12", "bad": {"x": 1}}),
            '{"test": "t", "covers": [{"id": "X", "how": "h", "new": 1}], "outcome": "passed", "more": 1}',
        )
        assert problems == []
        assert parsed.ci == {"job": "unit"}
        assert parsed.results[0].to_json() == {"test": "t", "covers": [{"id": "X", "how": "h"}], "outcome": "passed"}

    def test_null_ci_and_strings_are_fine(self):
        """A local run's header, and a CI block with null and string values."""
        assert parse_lines(header(ci=None))[1] == []
        assert parse_lines(header(root=None))[0].root is None
        assert parse_lines(header(root="common/speccheck"))[0].root == "common/speccheck"
        assert parse_lines(header())[0].root is None
        assert parse_lines(header(ci={"job": "unit", "job_id": None, "run_id": 3}))[1] == []

    def test_read_names_the_source(self, tmp_path: Path):
        """Problems and the parsed file carry `source` when given, else the path."""
        path = tmp_path / "r.jsonl"
        path.write_text(header() + "\n")
        assert results.read(path, "shown.jsonl")[0].source == "shown.jsonl"
        path.write_text("")
        assert results.read(path)[1][0].path == path.as_posix()


class TestLimits:
    """Size limits and symlinks."""

    def test_a_file_over_the_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Refused before it is read."""
        monkeypatch.setattr(results, "MAX_FILE_BYTES", 10)
        path = tmp_path / "r.jsonl"
        path.write_text(header() + "\n")
        parsed, problems = results.read(path)
        assert parsed is None and "the limit is 10" in str(problems[0])

    def test_a_line_over_the_limit(self):
        """One huge line is a problem, not a memory spike in json.loads."""
        parsed, problems = parse_lines(header(), "x" * (results.MAX_LINE_BYTES + 1))
        assert parsed is None and "2: line longer than" in str(problems[0])

    def test_unreadable_and_not_utf8(self, tmp_path: Path):
        """A folder named like a file, and bytes that aren't UTF-8."""
        (tmp_path / "d.jsonl").mkdir()
        assert "can't read" in str(results.read(tmp_path / "d.jsonl")[1][0])
        (tmp_path / "b.jsonl").write_bytes(b"\xff\xfe")
        assert "not UTF-8" in str(results.read(tmp_path / "b.jsonl")[1][0])

    def test_symlinks_are_not_followed(self, tmp_path: Path):
        """A link in an artifact can't point the reader at a file elsewhere."""
        outside = tmp_path / "outside"
        outside.mkdir()
        results.write(outside / "r.jsonl", sample())
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        (inputs / "link.jsonl").symlink_to(outside / "r.jsonl")
        (inputs / "dir").symlink_to(outside, target_is_directory=True)
        results.write(inputs / "real.jsonl", sample())
        (inputs / "notes.txt").write_text("not a results file")
        assert results.collect([inputs]) == [inputs / "real.jsonl"]
        assert results.collect([inputs / "link.jsonl"]) == []

    def test_a_symlink_input_is_a_problem(self, tmp_path: Path):
        """A symlink given as an input is skipped, and says so, whether or not its target exists."""
        results.write(tmp_path / "r.jsonl", sample())
        (tmp_path / "link.jsonl").symlink_to(tmp_path / "r.jsonl")
        (tmp_path / "broken.jsonl").symlink_to(tmp_path / "gone.jsonl")
        files, problems = results.read_all([tmp_path / "link.jsonl", tmp_path / "broken.jsonl"])
        assert files == []
        assert [(p.path, p.code) for p in problems] == [
            ((tmp_path / "link.jsonl").as_posix(), "results-symlink"),
            ((tmp_path / "broken.jsonl").as_posix(), "results-symlink"),
        ]

    def test_read_all(self, tmp_path: Path):
        """Files and folders; a missing input and a bad file are problems, good files still count."""
        results.write(tmp_path / "a" / "good.jsonl", sample())
        (tmp_path / "a" / "bad.jsonl").write_text("{\n")
        (tmp_path / "a" / "notes.txt").write_text("ignored")
        files, problems = results.read_all([tmp_path / "a", tmp_path / "missing"])
        assert [f.producer for f in files] == ["unit"]
        assert sorted(p.message.split(":")[0] for p in problems) == ["no such results file or folder", "not JSON"]

    def test_an_input_the_os_cant_look_at_is_a_problem(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """An OS error looking at an input is a problem for that input, not an exit 2; the rest count.

        Whether a too-long name raises depends on the platform (macOS does, Linux reports it
        missing), so the error is made here.
        """
        results.write(tmp_path / "good.jsonl", sample())
        bad = tmp_path / "bad.jsonl"
        real = Path.is_symlink

        def is_symlink(self: Path) -> bool:
            """Raise for `bad` as an over-long name would, and answer for anything else."""
            if self == bad:
                raise OSError(63, "File name too long")
            return real(self)

        monkeypatch.setattr(Path, "is_symlink", is_symlink)
        files, problems = results.read_all([bad, tmp_path / "good.jsonl"])
        assert [f.producer for f in files] == ["unit"]
        assert [(p.code, p.message) for p in problems] == [("results-unreadable", "can't read: File name too long")]


def test_a_failed_write_leaves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The file is written to a temporary name and renamed, so a crash leaves no partial file."""

    def broken(*args):
        """os.replace failing, as on a full disk."""
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        results.write(tmp_path / "r.jsonl", sample())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_written_file_gets_the_mode_the_umask_allows(tmp_path: Path):
    """Not mkstemp's 0600, so a file written by a container as root can be read by the host user."""
    old = os.umask(0o022)
    try:
        results.write(tmp_path / "r.jsonl", sample())
    finally:
        os.umask(old)
    assert (tmp_path / "r.jsonl").stat().st_mode & 0o777 == 0o644
