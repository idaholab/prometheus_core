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

"""The step summary: one line, then the problems."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from speccheck import summary
from speccheck.specs import Problem
from tests.unit.conftest import make_ctx, namespace

ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""This run's server and repository."""
REPORT = "https://github.com/o/r/actions/runs/1/artifacts/2"
"""An artifact link of this run."""


def test_the_arguments():
    """Both optional."""
    parser = argparse.ArgumentParser()
    summary.add_arguments(parser)
    assert vars(parser.parse_args([])) == {"summary": None, "report_url": None}
    args = parser.parse_args(["--summary", "s.md", "--report-url", REPORT])
    assert (args.summary, args.report_url) == ("s.md", REPORT)


class TestText:
    """What is written."""

    def test_a_pass(self):
        """The counts, escaped, and the link; no list."""
        assert summary.text("3 requirements: 3 passed_x", [], REPORT) == (
            f"**speccheck:** 3 requirements: 3 passed\\_x. Full report: [speccheck-report]({REPORT})\n\n"
        )
        assert summary.text("1 requirement: 1 passed", []) == "**speccheck:** 1 requirement: 1 passed\n\n"

    def test_problems(self):
        """The count, singular or plural, then each problem as a code span."""
        one = summary.text("c", [Problem("a`b", 1, "x*y")])
        assert one == "**speccheck:** 1 problem. c\n\n- `ab:1: x*y`\n\n"
        two = summary.text("c", [Problem("a", 1, "m"), Problem("b", 0, "n")])
        assert two.splitlines()[:1] == ["**speccheck:** 2 problems. c"]
        assert two.splitlines()[2:] == ["- `a:1: m`", "- `b: n`", ""]

    def test_cut_after_a_whole_entry(self, monkeypatch: pytest.MonkeyPatch):
        """Under LIMIT bytes, counting multi-byte characters, with the note last."""
        monkeypatch.setattr(summary, "LIMIT", 300)
        text = summary.text("c", [Problem("é" * 40, n, "m") for n in range(1, 20)])
        assert len(text.encode("utf-8")) <= 300
        lines = text.rstrip("\n").splitlines()
        assert lines[-1] == summary.CUT
        assert all(line.endswith(":1: m`") or line.endswith(": m`") for line in lines[2:-1])
        assert 0 < len(lines[2:-1]) < 19


class TestWrite:
    """Appending to `--summary`."""

    def test_nothing_without_the_option(self, tmp_path: Path):
        """No file, whether the arguments have the option or not."""
        summary.write(make_ctx(tmp_path), namespace(), "c", [])
        summary.write(make_ctx(tmp_path), argparse.Namespace(), "c", [])
        assert list(tmp_path.iterdir()) == []

    def test_appended_with_folders_made(self, tmp_path: Path):
        """After what an earlier step wrote; a relative path is under the cwd, an absolute one as given."""
        (tmp_path / "s.md").write_text("earlier\n")
        summary.write(make_ctx(tmp_path), namespace(summary="s.md"), "c", [])
        assert (tmp_path / "s.md").read_text() == "earlier\n**speccheck:** c\n\n"
        summary.write(make_ctx(tmp_path), namespace(summary=str(tmp_path / "d" / "s.md")), "c", [])
        assert (tmp_path / "d" / "s.md").is_file()

    def test_the_report_is_linked_only_when_safe(self, tmp_path: Path):
        """An artifact of this run's repository, in CI; not elsewhere, and not outside CI."""
        summary.write(make_ctx(tmp_path, env=ENV), namespace(summary="a.md", report_url=REPORT), "c", [])
        assert REPORT in (tmp_path / "a.md").read_text()
        summary.write(make_ctx(tmp_path), namespace(summary="b.md", report_url=REPORT), "c", [])
        bad = "https://evil.example/o/r/actions/runs/1/artifacts/2"
        summary.write(make_ctx(tmp_path, env=ENV), namespace(summary="c.md", report_url=bad), "c", [])
        assert (tmp_path / "b.md").read_text() == (tmp_path / "c.md").read_text() == "**speccheck:** c\n\n"

    def test_a_lone_surrogate_is_written_as_a_question_mark(self, tmp_path: Path):
        """A file name that isn't UTF-8 decodes with a surrogate; the summary is still written, not a crash."""
        summary.write(make_ctx(tmp_path), namespace(summary="s.md"), "c", [Problem("bad\udcff.jsonl", 0, "m")])
        assert (tmp_path / "s.md").read_text() == "**speccheck:** 1 problem. c\n\n- `bad?.jsonl: m`\n\n"
