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

"""A claim and the rules for its explanation."""

from __future__ import annotations

import pytest

from speccheck import claims
from tests.unit.conftest import make_requirement, make_spec, make_specs, spec_set


def test_a_claim_as_json():
    """The `covers` entry a results file holds."""
    assert claims.Claim("A", "how").to_json() == {"id": "A", "how": "how"}


class TestHowProblem:
    """The rules that need no specs."""

    @pytest.mark.parametrize(
        ("how", "message"),
        [
            ("", "the explanation for A-1 is empty"),
            ("x" * 1001, "the explanation for A-1 is 1001 characters; the limit is 1000"),
            ("a-1", "the explanation for A-1 is just the ID"),
            ("A-1.", "the explanation for A-1 is just the ID"),
            ("TODO", "the explanation for A-1 is a placeholder ('TODO')"),
            ("Tbd", "the explanation for A-1 is a placeholder ('Tbd')"),
            ("fixme", "the explanation for A-1 is a placeholder ('fixme')"),
            ("...", "the explanation for A-1 is a placeholder ('...')"),
            ("-", "the explanation for A-1 is a placeholder ('-')"),
        ],
    )
    def test_refused(self, how: str, message: str):
        """Empty, too long, the ID (case and a trailing full stop ignored), or a whole-text placeholder."""
        assert claims.how_problem("A-1", how).startswith(message)

    @pytest.mark.parametrize("how", ["x" * 1000, "TODO list is cleared", "..", "a-1 is written"])
    def test_accepted(self, how: str):
        """At the limit, a placeholder word inside a sentence, and text that only starts with the ID."""
        assert claims.how_problem("A-1", how) == ""


class TestCopied:
    """An explanation that is a requirement's text."""

    def test_any_requirement_not_retired(self):
        """Its own or another's, compared ignoring case, whitespace and a trailing full stop."""
        loaded = make_specs("The file MUST be written.", "It MUST be read.")
        assert claims.copied_from("the file  must be WRITTEN", loaded).id == "T-REQ-001-01"
        assert claims.copied_problem("T-REQ-001-01", "it must be read", loaded) == (
            "the explanation for T-REQ-001-01 is the text of T-REQ-001-02; describe how the test proves T-REQ-001-01"
        )
        assert claims.copied_from("the file is written", loaded) is None
        assert claims.copied_problem("T-REQ-001-01", "the file is written", loaded) == ""

    def test_a_retired_requirement_is_not_compared(self):
        """Retired by its text, or by its whole spec."""
        spec = make_spec()
        make_requirement(spec, "Retired: old text.")
        retired_spec = make_spec("002", status="retired")
        make_requirement(retired_spec, "Gone text.")
        loaded = spec_set(spec, retired_spec)
        assert claims.copied_from("Retired: old text", loaded) is None
        assert claims.copied_from("gone text", loaded) is None


class TestUnique:
    """An explanation given by one owner only."""

    def test_the_same_owner_again_is_fine(self):
        """Another leg or producer of the same test claiming the same ID."""
        unique = claims.Unique()
        assert unique.add("t::a", "A", "the file is written") == ""
        assert unique.add("t::a", "A", "The file is WRITTEN.") == ""

    def test_another_owner_or_id_is_a_repeat(self):
        """Another test, or another ID on the same test, naming the first owner."""
        unique = claims.Unique()
        unique.add("t::a", "A", "the file is written")
        assert unique.add("t::b", "B", "the  file is written.") == (
            "t::b gives the same explanation for B as t::a does for A; "
            "each claim says how its own test proves its requirement"
        )
        assert unique.add("t::a", "C", "the file is written").startswith(
            "t::a gives the same explanation for C as t::a"
        )
        assert unique.add("t::b", "B", "something else") == ""
