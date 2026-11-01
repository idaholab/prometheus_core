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

from __future__ import annotations

import pytest

from platformctl.diagnostics.base import FAIL, PASS, SKIP, WARN, Check, Registry, Result, counts, run_checks


def check(ident, status=PASS, depends=(), targets=("compose",), aliases=(), calls=None):
    """A check that returns `status` and records that it ran."""

    def run(ctx):
        """Record the run and return the check's canned result."""
        if calls is not None:
            calls.append(ident)
        return Result(status, f"{ident} evidence")

    return Check(ident, "area", ("diagnose",), run, depends_on=depends, targets=targets, aliases=aliases)


def test_duplicate_ids_are_refused():
    """Registering two checks with the same id raises.

    Covers REQ-006-13.
    """
    registry = Registry()
    registry.add(check("a"))
    with pytest.raises(ValueError, match="duplicate check id 'a'"):
        registry.add(check("a"))


def test_find_by_id_or_alias():
    """Find by id or alias.

    Covers REQ-006-12.
    """
    registry = Registry()
    a = registry.add(check("a", aliases=("old-a",)))
    assert registry.find("a") is a and registry.find("old-a") is a
    assert registry.find("zzz") is None


def test_validate_requires_dependencies_to_come_first():
    """Validate requires dependencies to come first."""
    registry = Registry()
    registry.add(check("b", depends=("a",)))
    with pytest.raises(ValueError, match="'b' depends on 'a'"):
        registry.validate()
    ok = Registry()
    ok.add(check("a"))
    ok.add(check("b", depends=("a",)))
    ok.validate()


def test_a_failed_dependency_skips_what_depends_on_it(ctx_factory):
    """A failed dependency skips what depends on it.

    Covers REQ-006-03.
    """
    ctx, _, _ = ctx_factory()
    calls: list[str] = []
    registry = Registry()
    for c in (
        check("docker", FAIL, calls=calls),
        check("needs-docker", depends=("docker",), calls=calls),
        check("then-that", depends=("needs-docker",), calls=calls),
        check("independent", calls=calls),
        check("after-warn", depends=("independent",), calls=calls),
    ):
        registry.add(c)
    outcomes = run_checks(ctx, registry, registry.checks)
    assert calls == ["docker", "independent", "after-warn"]
    by_id = {o.check.id: o.result for o in outcomes}
    assert by_id["needs-docker"] == Result(SKIP, "needs docker", skipped_because="docker")
    assert by_id["then-that"].skipped_because == "needs-docker"  # a skipped dependency skips too
    assert by_id["after-warn"].status == PASS


def test_a_warning_does_not_block_dependents(ctx_factory):
    """A warning does not block dependents.

    Covers REQ-006-03.
    """
    ctx, _, _ = ctx_factory()
    registry = Registry()
    registry.add(check("a", WARN))
    registry.add(check("b", depends=("a",)))
    assert [o.result.status for o in run_checks(ctx, registry, registry.checks)] == [WARN, PASS]


def test_only_selected_checks_run_in_registry_order(ctx_factory):
    """Only selected checks run in registry order.

    Covers REQ-006-09.
    """
    ctx, _, _ = ctx_factory()
    registry = Registry()
    for ident in ("a", "b", "c"):
        registry.add(check(ident))
    outcomes = run_checks(ctx, registry, [registry.find("c"), registry.find("a")])
    assert [o.check.id for o in outcomes] == ["a", "c"]


def test_a_check_for_another_target_is_skipped(ctx_factory):
    """A check for another target is skipped.

    Covers REQ-006-04.
    """
    ctx, _, _ = ctx_factory()
    registry = Registry()
    registry.add(check("k3d-only", targets=("k3d",)))
    (outcome,) = run_checks(ctx, registry, registry.checks)
    assert outcome.result.status == SKIP and outcome.result.skipped_because == "target"


def test_counts(ctx_factory):
    """The outcomes are tallied by status.

    Covers REQ-006-14.
    """
    ctx, _, _ = ctx_factory()
    registry = Registry()
    for ident, status in (("a", PASS), ("b", WARN), ("c", FAIL), ("d", PASS)):
        registry.add(check(ident, status))
    assert counts(run_checks(ctx, registry, registry.checks)) == {"pass": 2, "warn": 1, "fail": 1, "skip": 0}
