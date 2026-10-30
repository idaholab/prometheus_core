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

from platformctl.diagnostics import env_checks as ec
from platformctl.diagnostics.base import FAIL, PASS, SKIP, WARN
from tests.unit.conftest import make_context

GOOD = (
    "AGENT_SECRET=aaaaaaaaaaaaaaaa\nREDIS_PASSWORD=bbbbbbbbbbbbbbbb\nADMIN_DB_PASSWORD=cccccccccccccccc\n"
    "BACKEND_JWT_SECRET=dddddddddddddddd\nADMIN_DB_ENCRYPTION_KEY=eeeeeeeeeeeeeeee\nLLM_CONFIG_PROFILE=anthropic\n"
)


def run(check, root, runner, dotenv=None, env=None, sets=None):
    if dotenv is not None:
        (root / ".env").write_text(dotenv)
    ctx, _, _ = make_context(root, runner, env, sets)
    return check.run(ctx)


# -- platform-env ------------------------------------------------------------------------------


def test_platform_env_pass(platform_root, runner):
    result = run(ec.PLATFORM_ENV, platform_root, runner, GOOD)
    assert (result.status, result.evidence) == (PASS, "6 required values are set")


def test_platform_env_missing_file(platform_root, runner):
    result = run(ec.PLATFORM_ENV, platform_root, runner)
    assert result.status == FAIL and result.evidence == ".env does not exist" and "make init-env" in result.fix


@pytest.mark.parametrize("placeholder", ["", "sk-ant-...", "sk-change-me", "change-me-please", "your-key-here"])
def test_platform_env_names_what_is_unset_but_never_a_value(platform_root, runner, placeholder):
    dotenv = GOOD.replace("LLM_CONFIG_PROFILE=anthropic", f"LLM_CONFIG_PROFILE={placeholder}").replace(
        "aaaaaaaaaaaaaaaa", ""
    )
    result = run(ec.PLATFORM_ENV, platform_root, runner, dotenv)
    assert result.status == FAIL
    assert result.evidence == "not set: AGENT_SECRET, LLM_CONFIG_PROFILE"
    assert "bbbbbbbbbbbbbbbb" not in result.evidence + result.fix


def test_platform_env_missing_key_entirely(platform_root, runner):
    result = run(ec.PLATFORM_ENV, platform_root, runner, "AGENT_SECRET=aaaaaaaaaaaaaaaa\n")
    assert result.evidence.startswith("not set: REDIS_PASSWORD")


def test_platform_env_bad_line_names_the_line_not_its_text(platform_root, runner):
    result = run(ec.PLATFORM_ENV, platform_root, runner, "AGENT_SECRET=ok\nsk-live-supersecretvalue\n")
    assert result.status == FAIL
    assert "line 2" in result.evidence and "supersecret" not in result.evidence


# -- base-image-pin ----------------------------------------------------------------------------


def test_base_image_pin_local_sdk(platform_root, runner):
    result = run(ec.BASE_IMAGE_PIN, platform_root, runner, "LOCAL_SDK=true\n")
    assert result.status == PASS and "built from ../sdk" in result.evidence


def test_base_image_pin_default(platform_root, runner):
    result = run(ec.BASE_IMAGE_PIN, platform_root, runner)
    assert result.status == PASS and "prometheus_api:1914b55" in result.evidence


@pytest.mark.parametrize("key", ["PROMETHEUS_API_BASE_IMAGE_HASH", "PROMETHEUS_API_BASE_IMAGE_REPO"])
def test_base_image_pin_blank_line_warns(platform_root, runner, key):
    result = run(ec.BASE_IMAGE_PIN, platform_root, runner, f"{key}=\n")
    assert result.status == WARN and key in result.evidence and f"Remove the empty {key}= line" in result.fix


# -- .env hiding / derived keys ----------------------------------------------------------------


def test_env_hides_environment(platform_root, runner):
    assert run(ec.ENV_HIDES_ENVIRONMENT, platform_root, runner).status == PASS
    result = run(
        ec.ENV_HIDES_ENVIRONMENT,
        platform_root,
        runner,
        "LLM_API_KEY=fake-dotenv-value\nA=1\n",
        {"LLM_API_KEY": "fake-env-value", "A": "1"},
    )
    assert result.status == WARN and result.evidence.endswith("for: LLM_API_KEY")
    assert "fake-" not in result.evidence + result.fix


def test_env_derived_keys(platform_root, runner):
    assert run(ec.ENV_DERIVED_KEYS, platform_root, runner, "BACKEND_PORT=1\n").status == PASS
    result = run(ec.ENV_DERIVED_KEYS, platform_root, runner, "PROMETHEUS_API_BASE_IMAGE_HASH=abc\nBUILD_CACHE=x\n")
    assert result.status == WARN
    assert (
        "PROMETHEUS_API_BASE_IMAGE_HASH, BUILD_CACHE" in result.evidence
        and "hand-run `docker compose`" in result.evidence
    )


# -- env-file ----------------------------------------------------------------------------------


def set_git(runner, root, *, tracked=False, ignored=True, inside=True):
    from platformctl.system.runner import Result

    for verb, ok in (("ls-files", tracked), ("check-ignore", ignored), ("rev-parse", inside)):
        runner.responses[("git", "-C", str(root), verb)] = Result([], 0 if ok else 1)


def test_env_file_skipped_without_a_file(platform_root, runner):
    result = run(ec.ENV_FILE, platform_root, runner)
    assert result.status == SKIP


def test_env_file_ok(platform_root, runner):
    (platform_root / ".env").write_text("A=1\n")
    (platform_root / ".env").chmod(0o600)
    set_git(runner, platform_root)
    ctx, _, _ = make_context(platform_root, runner)
    result = ec.ENV_FILE.run(ctx)
    assert (result.status, result.evidence) == (PASS, ".env is mode 0600 and ignored by git")


def test_env_file_group_readable_and_tracked(platform_root, runner):
    (platform_root / ".env").write_text("A=1\n")
    (platform_root / ".env").chmod(0o644)
    set_git(runner, platform_root, tracked=True)
    ctx, _, _ = make_context(platform_root, runner)
    result = ec.ENV_FILE.run(ctx)
    assert result.status == WARN
    assert result.evidence == ".env mode is 0644, readable by others and not ignored by git"


def test_env_file_not_ignored(platform_root, runner):
    (platform_root / ".env").write_text("A=1\n")
    (platform_root / ".env").chmod(0o600)
    set_git(runner, platform_root, ignored=False)
    ctx, _, _ = make_context(platform_root, runner)
    assert ec.ENV_FILE.run(ctx).evidence == ".env not ignored by git"


def test_env_file_outside_a_git_checkout_is_not_a_problem(platform_root, runner):
    (platform_root / ".env").write_text("A=1\n")
    (platform_root / ".env").chmod(0o600)
    set_git(runner, platform_root, ignored=False, inside=False)
    ctx, _, _ = make_context(platform_root, runner)
    assert ec.ENV_FILE.run(ctx).status == PASS


def test_env_file_mode_is_skipped_on_a_windows_drive(platform_root, runner, monkeypatch):
    (platform_root / ".env").write_text("A=1\n")
    ctx, _, _ = make_context(platform_root, runner)
    monkeypatch.setattr(type(ctx.host), "on_windows_drive", staticmethod(lambda path: True))
    result = ec.ENV_FILE.run(ctx)
    assert result.status == SKIP and "/mnt" in result.evidence
