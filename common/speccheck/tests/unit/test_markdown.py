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

"""Escaping untrusted text for markdown, and the only links allowed."""

from __future__ import annotations

import pytest

from speccheck import markdown

BASE = "https://github.com/o/r"
"""This run's repository URL, the only one linked."""


class TestEscape:
    """Untrusted strings in markdown."""

    def test_special_characters(self):
        """Markdown and HTML are backslashed."""
        assert markdown.escape("t[x](https://evil)<img>|`") == r"t\[x\]\(https://evil\)\<img\>\|\`"

    def test_one_line_and_capped(self):
        """Whitespace collapses, and long text is cut."""
        assert markdown.escape("a\n b\tc") == "a b c"
        assert markdown.escape("x" * 300, 10) == "x" * 9 + "…"
        assert markdown.escape(3) == "3"


class TestCode:
    """Untrusted strings in an inline code span, where markdown shows backslashes as they are."""

    def test_literal_text_without_backticks(self):
        """Markdown characters stay as written; a backtick is dropped so the span can't close early."""
        assert markdown.code("tests/t.py::test_a[x*](y)<b>", in_table=False) == "`tests/t.py::test_a[x*](y)<b>`"
        assert markdown.code("a`b``c", in_table=False) == "`abc`"

    def test_a_pipe_in_a_table(self):
        """GFM splits a row on `|` before it reads the span, so it is written `\\|` there only."""
        assert markdown.code("a|b", in_table=True) == r"`a\|b`"
        assert markdown.code("a|b", in_table=False) == "`a|b`"

    def test_one_line_and_capped(self):
        """Whitespace collapses, and long text is cut, after the backticks are gone."""
        assert markdown.code("a\n b", in_table=False) == "`a b`"
        assert markdown.code("`" * 5 + "x" * 20, 10, in_table=False) == "`" + "x" * 9 + "…`"


class TestProse:
    """Text outside a table cell: code spans kept, only link, HTML and emphasis characters escaped."""

    def test_spans_kept_and_only_what_matters_escaped(self):
        """`.` and `-` stay; a span's contents are left alone; brackets, HTML and emphasis are escaped."""
        assert markdown.prose("a-b.c `x[y]*` [l](u) <i>_e_ ~s~ |p| &amp; \\") == (
            "a-b.c `x[y]*` \\[l\\](u) \\<i\\>\\_e\\_ \\~s\\~ \\|p\\| \\&amp; \\\\"
        )

    def test_an_unmatched_backtick_escapes_every_backtick(self):
        """No span can open and swallow the rest."""
        assert markdown.prose("a `b` c` [d]") == "a \\`b\\` c\\` \\[d\\]"

    def test_one_line_and_capped(self):
        """Whitespace collapses, and long text is cut with an ellipsis."""
        assert markdown.prose("a\n  b") == "a b"
        assert markdown.prose("x" * 20, 10) == "x" * 9 + "…"
        assert markdown.prose(3) == "3"

    def test_a_line_start_is_escaped_only_when_asked(self):
        """A heading, quote, list or rule at the start of a line, and only there."""
        cases = {"# h": "\\# h", "- l": "\\- l", "+ l": "\\+ l", "= r": "\\= r", "1. n": "\\1. n", "2) n": "\\2) n"}
        assert {text: markdown.prose(text, line_start=True) for text in cases} == cases
        # `>` is escaped anywhere, as it can start HTML, so a quote is already inert
        assert markdown.prose("> q", line_start=True) == markdown.prose("> q") == "\\> q"
        assert markdown.prose("# h") == "# h"
        assert markdown.prose("a # b", line_start=True) == "a # b"


def test_anchor():
    """GitHub's: lower case, punctuation and emoji dropped, spaces as hyphens."""
    assert markdown.anchor("SPC-REQ-001-01 ✅ passed") == "spc-req-001-01--passed"
    assert markdown.anchor("001 Spec format") == "001-spec-format"
    assert markdown.anchor("A (b), c!") == "a-b-c"


class TestSourceUrl:
    """A file at this run's commit."""

    FILES = BASE + "/blob/" + "a" * 40
    """Where this run's files are browsed."""

    def test_linked_with_and_without_a_line(self):
        """A plain path, with `#L<line>` when the line is known."""
        assert markdown.source_url(self.FILES, "common/x.py", 3) == f"{self.FILES}/common/x.py#L3"
        assert markdown.source_url(self.FILES, "x.md") == f"{self.FILES}/x.md"

    @pytest.mark.parametrize(
        "path", [None, "", "a b.py", "a/../b.py", "../b.py", "/abs.py", "a//b.py", "a/", "x?.py", "a/#b", "é.py"]
    )
    def test_rejected(self, path):
        """Nothing, a space, `..`, an absolute or empty part, or anything but plain characters."""
        assert markdown.source_url(self.FILES, path, 3) == ""

    def test_nothing_without_a_base(self):
        """Outside CI there is no commit to link to."""
        assert markdown.source_url("", "x.py", 3) == ""


class TestSafeUrl:
    """Only run, attempt and job URLs under this run's own repository URL are linked."""

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "https://evil.example/o/r/actions/runs/1/job/2",
            "https://evil.example/o/r/actions/runs/1/job/2)[x](y",
            "https://github.com/o/other/actions/runs/1",
            "https://github.com/o/r2/actions/runs/1",
            "https://github.com.evil.example/o/r/actions/runs/1",
            "http://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/pulls/1",
            "https://github.com/o/r/actions/runs/x",
            "https://github.com/o/r/actions/runs/0",
            "https://github.com/o/r/actions/runs/1\n",
            "https://github.com/o/r/actions/runs/1/job/2/x",
            None,
            3,
        ],
    )
    def test_rejected(self, url):
        """Another host or repo, another shape, a trailing newline, or not a string: no link."""
        assert markdown.safe_url(url, BASE) == ""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/actions/runs/1/attempts/2",
            "https://github.com/o/r/actions/runs/1/job/3",
        ],
    )
    def test_accepted(self, url):
        """Run, attempt and job URLs of this repository."""
        assert markdown.safe_url(url, BASE) == url

    def test_a_server_with_a_port(self):
        """GitHub Enterprise on its own host and port."""
        assert markdown.safe_url("https://ghe.example:8443/o/r/actions/runs/1", "https://ghe.example:8443/o/r") != ""

    def test_nothing_is_linked_without_a_base(self):
        """Outside CI there is no repository to trust, so no link."""
        assert markdown.safe_url("https://github.com/o/r/actions/runs/1", "") == ""


class TestSafeArtifactUrl:
    """Only an artifact URL under this run's own repository URL is linked."""

    def test_accepted(self):
        """The form `actions/upload-artifact` gives."""
        url = "https://github.com/o/r/actions/runs/1/artifacts/2"
        assert markdown.safe_artifact_url(url, BASE) == url

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/actions/runs/1/job/2",
            "https://github.com/o/r/actions/artifacts/2",
            "https://github.com/o/r/actions/runs/1/artifacts/2)[x](y",
            "https://github.com/o/other/actions/runs/1/artifacts/2",
            "https://evil.example/o/r/actions/runs/1/artifacts/2",
            "https://github.com/o/r/actions/runs/1/artifacts/0",
            None,
        ],
    )
    def test_rejected(self, url):
        """A run or job link, another shape, repository or host, or not a string."""
        assert markdown.safe_artifact_url(url, BASE) == ""

    def test_nothing_without_a_base(self):
        """Outside CI there is no repository to trust."""
        assert markdown.safe_artifact_url("https://github.com/o/r/actions/runs/1/artifacts/2", "") == ""
