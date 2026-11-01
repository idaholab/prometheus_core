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

import argparse
import json

import pytest

from platformctl.actions import doctor
from tests.unit.conftest import assert_golden, make_context

GOOD_ENV = (
    "AGENT_SECRET=aaaaaaaaaaaaaaaa\nREDIS_PASSWORD=bbbbbbbbbbbbbbbb\nADMIN_DB_PASSWORD=cccccccccccccccc\n"
    "BACKEND_JWT_SECRET=dddddddddddddddd\nADMIN_DB_ENCRYPTION_KEY=eeeeeeeeeeeeeeee\nLLM_CONFIG_PROFILE=anthropic\n"
)
"""A `.env` that sets every key the `platform-env` check requires."""


@pytest.fixture(autouse=True)
def ports_free(monkeypatch):
    """Make every port look free, so `doctor` doesn't depend on the machine."""
    from platformctl.system import host

    monkeypatch.setattr(host, "port_free", lambda port: True)


def args(*checks, tag=None, list_=False):
    """The parsed arguments of a `doctor` run."""
    return argparse.Namespace(checks=list(checks), tag=tag, list=list_)


def ctx_with_env(platform_root, runner, **kw):
    """A context whose platform folder has a good `.env` (mode 0600)."""
    (platform_root / ".env").write_text(GOOD_ENV)
    (platform_root / ".env").chmod(0o600)
    return make_context(platform_root, runner, **kw)


def test_add_arguments_parses_the_options():
    """Add arguments parses the options."""
    parser = argparse.ArgumentParser()
    doctor.add_arguments(parser)
    ns = parser.parse_args(["docker", "ports-free", "--tag", "preflight", "--list"])
    assert (ns.checks, ns.tag, ns.list) == (["docker", "ports-free"], "preflight", True)


def test_text_output_for_a_clean_run(platform_root, runner):
    """Text output for a clean run."""
    ctx, out, _ = ctx_with_env(platform_root, runner)
    assert doctor.run(ctx, args("docker", "platform-env")) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("PASS  docker") and "Docker Desktop 29.1.0" in lines[0]
    assert lines[1].startswith("PASS  platform-env")
    assert lines[-1] == "No problems found."


def test_text_output_lists_the_fix_under_each_failure_and_counts_problems(platform_root, runner):
    """Text output lists the fix under each failure and counts problems."""
    ctx, out, _ = make_context(platform_root, runner)  # no .env
    code = doctor.run(ctx, args("platform-env", "env-derived-keys"))
    text = out.getvalue()
    assert code == 1
    assert "FAIL  platform-env" in text and "      fix: Run `./platformctl config init`" in text
    assert "1 problem: run the fixes above, then ./platformctl doctor again" in text


def test_only_warnings_exit_zero_and_are_counted_as_problems(platform_root, runner):
    """Only warnings exit zero and are counted as problems."""
    (platform_root / ".env").write_text(GOOD_ENV + "BUILD_CACHE=x\nBACKEND_PORT=1\n")
    ctx, out, _ = make_context(platform_root, runner)
    code = doctor.run(ctx, args("env-derived-keys"))
    assert code == 0 and "1 problem: run the fixes" in out.getvalue()


def test_several_problems_are_plural(platform_root, runner):
    """Two problems are counted as "2 problems"."""
    runner.reply("docker", "info", code=1, stderr="Cannot connect to the Docker daemon")
    ctx, out, _ = make_context(platform_root, runner)
    assert doctor.run(ctx, args("docker", "platform-env")) == 1
    assert "2 problems: run the fixes above" in out.getvalue()


def test_a_skipped_check_shows_why(platform_root, runner):
    """A skipped check shows why."""
    runner.reply("docker", "info", code=1, stderr="Cannot connect to the Docker daemon")
    ctx, out, _ = make_context(platform_root, runner)
    doctor.run(ctx, args("docker", "build-cache-store"))
    assert "SKIP  build-cache-store" in out.getvalue() and "needs docker" in out.getvalue()


def test_the_tag_filter(platform_root, runner):
    """`--tag preflight` runs only the preflight checks."""
    ctx, out, _ = ctx_with_env(platform_root, runner)
    doctor.run(ctx, args(tag="preflight"))
    text = out.getvalue()
    assert "docker " in text and "env-hides-environment" not in text


def test_all_checks_run_by_default(platform_root, runner):
    """All checks run by default."""
    ctx, out, _ = ctx_with_env(platform_root, runner)
    doctor.run(ctx, args())
    assert len([line for line in out.getvalue().splitlines() if line[:4] in ("PASS", "WARN", "FAIL", "SKIP")]) == 9


def test_list(platform_root, runner):
    """`--list` prints each check's id, tags and targets, and exits 0."""
    ctx, out, _ = make_context(platform_root, runner)
    assert doctor.run(ctx, args(list_=True)) == 0
    rows = [line.split() for line in out.getvalue().splitlines()]
    assert rows[0] == ["docker", "preflight,diagnose", "compose"]
    assert [r[0] for r in rows][-1] == "checkout-path"


def test_list_json(platform_root, runner):
    """`--list --json` prints the same listing as one JSON object."""
    ctx, out, _ = make_context(platform_root, runner, json_mode=True)
    assert doctor.run(ctx, args(list_=True)) == 0
    body = json.loads(out.getvalue())
    assert body["ok"] and body["command"] == "doctor"
    assert body["checks"][0] == {
        "id": "docker",
        "area": "laptop",
        "tags": ["preflight", "diagnose"],
        "targets": ["compose"],
    }


def test_unknown_check_id(platform_root, runner):
    """An unknown check id exits 2 and points to `--list`."""
    ctx, _, err = make_context(platform_root, runner)
    assert doctor.run(ctx, args("nope", "docker")) == 2
    assert "unknown check id: nope" in err.getvalue() and "doctor --list" in err.getvalue()


def test_unknown_check_id_json(platform_root, runner):
    """An unknown check id is a `usage` error in JSON, with nothing on stderr."""
    ctx, out, err = make_context(platform_root, runner, json_mode=True)
    assert doctor.run(ctx, args("nope")) == 2
    body = json.loads(out.getvalue())
    assert body["error"]["code"] == "usage" and body["ok"] is False and err.getvalue() == ""


def test_json_per_check_fields_and_counts(platform_root, runner):
    """Json per check fields and counts."""
    ctx, out, _ = make_context(platform_root, runner, json_mode=True)  # no .env: platform-env fails
    code = doctor.run(ctx, args("docker", "platform-env", "env-file"))
    body = json.loads(out.getvalue())
    assert code == 1
    assert body["ok"] is True  # doctor itself worked; a failed check is in counts
    assert body["counts"] == {"pass": 1, "warn": 0, "fail": 1, "skip": 1}
    by_id = {c["id"]: c for c in body["checks"]}
    assert set(by_id["docker"]) == {"id", "area", "tags", "status", "evidence", "fix", "fix_kind", "skipped_because"}
    assert by_id["platform-env"]["status"] == "FAIL" and by_id["platform-env"]["fix_kind"] == "yes"
    assert by_id["env-file"]["status"] == "SKIP"
    assert set(body["platform"]) == {"root", "project", "version"}


def test_the_json_never_has_a_secret(platform_root, runner):
    """The json never has a secret."""
    (platform_root / ".env").write_text(GOOD_ENV + "LLM_API_KEY=fake-secret-fake-secret\n")
    ctx, out, err = make_context(
        platform_root, runner, json_mode=True, env={"PATH": "/usr/bin", "LLM_API_KEY": "fake-env-secret-fake-env"}
    )
    doctor.run(ctx, args())
    for secret in ("fake-secret-fake-secret", "fake-env-secret-fake-env", "aaaaaaaaaaaaaaaa", "eeeeeeeeeeeeeeee"):
        assert secret not in out.getvalue() + err.getvalue()


# -- golden files: the --json contract, field by field ------------------------------------------


def test_golden_doctor_all_pass(platform_root, runner):
    """The whole object of a healthy `doctor --json`."""
    ctx, out, _ = ctx_with_env(platform_root, runner, json_mode=True)
    assert doctor.run(ctx, args()) == 0
    assert_golden("doctor_pass", json.loads(out.getvalue()), platform_root)


def test_golden_doctor_with_a_failed_check(platform_root, runner):
    """Exit 1 and `ok` true: the failure is in `counts` and the check's `status` (README: "Reading --json")."""
    ctx, out, _ = make_context(platform_root, runner, json_mode=True)  # no .env
    assert doctor.run(ctx, args()) == 1
    assert_golden("doctor_fail", json.loads(out.getvalue()), platform_root)


def test_golden_doctor_list(platform_root, runner):
    """`doctor --list --json`: every check's id, area, tags and targets."""
    ctx, out, _ = make_context(platform_root, runner, json_mode=True)
    assert doctor.run(ctx, args(list_=True)) == 0
    assert_golden("doctor_list", json.loads(out.getvalue()), platform_root)


def test_golden_doctor_unknown_check(platform_root, runner):
    """An unknown check id is a `usage` error object."""
    ctx, out, _ = make_context(platform_root, runner, json_mode=True)
    assert doctor.run(ctx, args("nope")) == 2
    assert_golden("doctor_unknown_check", json.loads(out.getvalue()), platform_root)
