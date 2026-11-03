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

"""A claim: one requirement ID and how the test or CI job proves it, and the rules its explanation follows.

See plan/design.md, "Claiming a requirement". The plugin, the config and `check`/`verify` all
apply these rules, so a claim is judged the same wherever it is written.
"""

from __future__ import annotations

from dataclasses import dataclass

from speccheck.specs import Requirement, SpecSet, collapse, comparable

MAX_HOW = 1000
"""The longest explanation, in characters, after its whitespace is collapsed."""
PLACEHOLDERS = frozenset({"todo", "tbd", "fixme", "...", "-"})
"""Explanations that stand in for one, compared as the whole text, in any case."""


@dataclass(frozen=True)
class Claim:
    """One claimed requirement and how the claimant proves it."""

    id: str
    """The requirement ID."""
    how: str
    """How the test or job proves it: plain text, one line."""

    def to_json(self) -> dict[str, str]:
        """The claim as a results file writes it."""
        return {"id": self.id, "how": self.how}


def how_problem(claimed: str, how: str) -> str:
    """Why an explanation (already collapsed) can't be used, or "". Needs no specs (SPC-REQ-003-17)."""
    if not how:
        return f"the explanation for {claimed} is empty; say how the test proves it"
    if len(how) > MAX_HOW:
        return f"the explanation for {claimed} is {len(how)} characters; the limit is {MAX_HOW}"
    if comparable(how) == comparable(claimed):
        return f"the explanation for {claimed} is just the ID; say how the test proves it"
    # The whole text, case ignored but punctuation kept: `comparable` would turn `...` into `..`
    if how.casefold() in PLACEHOLDERS:
        return f"the explanation for {claimed} is a placeholder ({how!r}); say how the test proves it"
    return ""


def copied_from(how: str, specs: SpecSet) -> Requirement | None:
    """The requirement, not retired, whose text the explanation is (SPC-REQ-003-09), or None."""
    key = comparable(how)
    for requirement in specs.requirements.values():
        if not requirement.retired and comparable(requirement.text) == key:
            return requirement
    return None


def copied_problem(claimed: str, how: str, specs: SpecSet) -> str:
    """The message for an explanation that is a requirement's text, or ""."""
    source = copied_from(how, specs)
    if source is None:
        return ""
    return f"the explanation for {claimed} is the text of {source.id}; describe how the test proves {claimed}"


class Unique:
    """Finds explanations given more than once (SPC-REQ-003-11, 005-10).

    Each claim has an owner: a test's node ID, or a CI job's name, with the ID it claims. The same
    owner seen again (another leg, producer or attempt) is the same claim, not a repeat.
    """

    def __init__(self) -> None:
        """Nothing seen yet."""
        self.seen: dict[str, tuple[str, str]] = {}
        """The first owner of each explanation, by its comparable form: `(where, ID)`."""

    def add(self, where: str, claimed: str, how: str) -> str:
        """Note one claim; the message when another owner already gave this explanation, else ""."""
        first = self.seen.setdefault(comparable(how), (where, claimed))
        if first == (where, claimed):
            return ""
        return (
            f"{where} gives the same explanation for {claimed} as {first[0]} does for {first[1]}; "
            f"each claim says how its own test proves its requirement"
        )


__all__ = ["MAX_HOW", "PLACEHOLDERS", "Claim", "Unique", "collapse", "copied_from", "copied_problem", "how_problem"]
