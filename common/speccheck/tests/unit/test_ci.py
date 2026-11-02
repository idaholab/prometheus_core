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

"""The GitHub Actions context and the run and job links."""

from __future__ import annotations

from pathlib import Path

import pytest

from speccheck import ci

GITHUB = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "idaholab/prometheus_core",
    "GITHUB_WORKFLOW": "speccheck",
    "GITHUB_JOB": "unit",
    "GITHUB_RUN_ID": "123",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_SHA": "a" * 40,
    "GITHUB_REF": "refs/heads/devel",
    "GITHUB_EVENT_NAME": "push",
    "SPECCHECK_JOB_ID": "456",
}
"""A fake GitHub Actions environment, on a re-run attempt."""


class TestContext:
    """The `ci` block."""

    def test_in_github_actions(self):
        """Every field, from the environment."""
        block = ci.context(GITHUB)
        assert block["repository"] == "idaholab/prometheus_core"
        assert (block["workflow"], block["job"]) == ("speccheck", "unit") and "leg" not in block
        assert (block["run_id"], block["run_attempt"], block["job_id"]) == (123, 2, 456)
        assert block["sha"] == "a" * 40
        assert block["provider"] == ci.PROVIDER == "github"

    def test_outside_ci(self):
        """None, so a local file is only good for `check`."""
        assert ci.context({}) is None
        assert ci.context({"GITHUB_ACTIONS": "false"}) is None

    def test_missing_and_bad_numbers(self):
        """A missing attempt is 1; a non-number ID is dropped, not trusted."""
        block = ci.context({**GITHUB, "GITHUB_RUN_ATTEMPT": "", "SPECCHECK_JOB_ID": "12; rm"})
        assert (block["run_attempt"], block["job_id"]) == (1, None)


class TestLinks:
    """Run and job URLs."""

    def test_run_url_has_the_attempt(self):
        """A re-run links its own attempt."""
        assert (
            ci.context(GITHUB)["run_url"] == "https://github.com/idaholab/prometheus_core/actions/runs/123/attempts/2"
        )

    def test_job_url_uses_the_check_run_id(self):
        """`${{ job.check_run_id }}` gives the job's own page; each attempt's job has its own ID."""
        assert ci.context(GITHUB)["job_url"] == "https://github.com/idaholab/prometheus_core/actions/runs/123/job/456"

    @pytest.mark.parametrize(
        ("server", "repository", "url"),
        [
            ("https://github.com", "o/r", "https://github.com/o/r"),
            ("https://ghe.example:8443", "o/r", "https://ghe.example:8443/o/r"),
            ("http://github.com", "o/r", ""),
            ("https://github.com/", "o/r", ""),
            ("https://github.com", "o/r/x", ""),
            ("https://github.com", "o/r\n", ""),
            ("", "o/r", ""),
            ("https://github.com", "", ""),
        ],
    )
    def test_repository_url(self, server: str, repository: str, url: str):
        """The base a report links under, only from a safe server and an `owner/name`."""
        env = {"GITHUB_SERVER_URL": server, "GITHUB_REPOSITORY": repository}
        assert ci.repository_url(env) == url

    def test_without_a_job_id_the_job_link_is_the_run(self):
        """The fallback when the workflow doesn't pass SPECCHECK_JOB_ID."""
        env = {k: v for k, v in GITHUB.items() if k != "SPECCHECK_JOB_ID"}
        block = ci.context(env)
        assert block["job_url"] == block["run_url"]

    @pytest.mark.parametrize(
        "change",
        [
            {"server": "http://github.com"},
            {"server": "https://github.com/x"},
            {"server": "javascript:alert(1)"},
            {"repository": "a/b/c"},
            {"repository": "a b/c"},
            {"run_id": "x"},
            {"run_id": 0},
            {"run_id": True},
            {"server": None},
        ],
    )
    def test_an_unsafe_part_gives_no_link(self, change):
        """Links are built only from parts of the expected shape."""
        block = {"server": "https://github.com", "repository": "a/b", "run_id": 1, "run_attempt": 1, **change}
        assert ci.run_url(block) == "" and ci.job_url(block) == ""

    def test_no_attempt(self):
        """A block with no attempt links the run itself."""
        assert ci.run_url({"server": "https://ghe.example:8443", "repository": "a/b", "run_id": 5}) == (
            "https://ghe.example:8443/a/b/actions/runs/5"
        )


@pytest.mark.parametrize(
    ("value", "number"),
    [
        ("1", 1),
        ("456", 456),
        (7, 7),
        ("0", None),
        ("01", None),
        ("-1", None),
        ("1.5", None),
        (" 1", None),
        ("1" * 21, None),
        (0, None),
        (-3, None),
        (True, None),
        (None, None),
        (1.0, None),
    ],
)
def test_number(value, number):
    """Only a positive whole number, from a string of digits or an int; never a bool."""
    assert ci._number(value) == number


def test_in_github_actions():
    """Only `GITHUB_ACTIONS=true`."""
    assert ci.in_github_actions({"GITHUB_ACTIONS": "true"})
    assert not any(ci.in_github_actions({"GITHUB_ACTIONS": v}) for v in ("1", "True", ""))


def test_commit_url():
    """This run's repository and a full commit hash; nothing outside CI or with a bad hash."""
    env = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_SHA": "a" * 40}
    assert ci.commit_url(env) == "https://github.com/o/r/blob/" + "a" * 40
    assert ci.commit_url({**env, "GITHUB_SHA": "a" * 39}) == ""
    assert ci.commit_url({**env, "GITHUB_SHA": "../x"}) == ""
    assert ci.commit_url({"GITHUB_SHA": "a" * 40}) == ""


class TestRepositoryRoot:
    """Where the repository starts."""

    def test_the_workspace_in_ci(self, tmp_path: Path):
        """`GITHUB_WORKSPACE` wins, resolved."""
        assert ci.repository_root(tmp_path, {"GITHUB_WORKSPACE": str(tmp_path / "w")}) == (tmp_path / "w").resolve()

    def test_the_nearest_git_folder(self, tmp_path: Path):
        """Without the variable, the nearest folder up with a `.git`, a folder or a worktree's file."""
        (tmp_path / "repo" / "a" / "b").mkdir(parents=True)
        (tmp_path / "repo" / ".git").write_text("gitdir: elsewhere\n")
        assert ci.repository_root(tmp_path / "repo" / "a" / "b", {}) == (tmp_path / "repo").resolve()

    def test_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No variable and no `.git` above: None."""
        monkeypatch.setattr(Path, "exists", lambda self: False)
        assert ci.repository_root(tmp_path, {}) is None


def test_from_root(tmp_path: Path):
    """A path under the root from it, the root itself as `.`, else None."""
    root = tmp_path.resolve()
    assert ci.from_root(tmp_path / "a" / "b.md", root) == "a/b.md"
    assert ci.from_root(tmp_path, root) == "."
    assert ci.from_root(Path("/elsewhere/x"), root) is None
    assert ci.from_root(tmp_path / "x", None) is None
