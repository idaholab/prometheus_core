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

import io
import os
import stat
import sys
from pathlib import Path

import pytest

from platformctl import env_init
from platformctl.output import Output, Scrubber
from platformctl.system import envfile
from platformctl.system.runner import Runner
from tests.unit.conftest import FakeRunner

EXAMPLE = (
    '# one\n#   python3 -c "print(1)"\nAGENT_SECRET=\n'
    '# two\n#   python3 -c "print(2)"\nREDIS_PASSWORD=\n'
    "# not generated\nLLM_API_KEY=\n"
)
"""A `.env.example` with two generated secrets and one the user must supply."""


def test_create_copies_the_example_as_owner_only_even_under_a_loose_umask(tmp_path):
    """A new `.env` is 0600 from the start, so a secret is never written to a world-readable file."""
    example, env = tmp_path / ".env.example", tmp_path / ".env"
    example.write_text(EXAMPLE)
    old = os.umask(0o022)
    try:
        assert env_init.create(example, env) is True
    finally:
        os.umask(old)
    assert env.read_text() == EXAMPLE
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_create_leaves_an_existing_env_and_its_mode_alone(tmp_path):
    """An existing `.env` is not touched."""
    example, env = tmp_path / ".env.example", tmp_path / ".env"
    example.write_text(EXAMPLE)
    env.write_text("MINE=1\n")
    env.chmod(0o640)
    assert env_init.create(example, env) is False
    assert env.read_text() == "MINE=1\n" and stat.S_IMODE(env.stat().st_mode) == 0o640


def test_write_env_tightens_a_loose_env_before_adding_secrets_and_says_so(tmp_path):
    """A 0644 `.env` would keep that mode through a rewrite: it becomes 0600 first, with a warning."""
    env = tmp_path / ".env"
    env.write_text("MINE=1\n")
    env.chmod(0o644)
    err = io.StringIO()
    output = Output(Scrubber(), out=io.StringIO(), err=err, env={})
    env_init.write_env(env, output, {"AGENT_SECRET": "s"})
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "was readable by other users (mode 0644); it is now owner-only (0600)." in err.getvalue()
    assert envfile.read(env) == {"MINE": "1", "AGENT_SECRET": "s"}


def test_write_env_says_nothing_for_a_private_env(tmp_path):
    """A `.env` that is already owner-only (0600, or 0400) is written without a warning."""
    env = tmp_path / ".env"
    env.write_text("MINE=1\n")
    env.chmod(0o600)
    err = io.StringIO()
    env_init.write_env(env, Output(Scrubber(), out=io.StringIO(), err=err, env={}), {"K": "v"})
    assert err.getvalue() == "" and stat.S_IMODE(env.stat().st_mode) == 0o600


def test_generate_secret_runs_the_one_liner_with_this_python():
    """The real runner runs the one-liner with the interpreter the tool runs on."""
    assert env_init.generate_secret(Runner(), "K", "print('abc')") == "abc"


@pytest.mark.parametrize(("code", "stdout"), [(1, "PRINTED-VALUE"), (0, "  \n")])
def test_generate_secret_fails_naming_the_key_not_the_output(code, stdout):
    """A failing or empty generator is an error that names the key and carries no output."""
    runner = FakeRunner()
    runner.reply(sys.executable, "-c", "boom", code=code, stdout=stdout, stderr="LEAKED-STDERR")
    with pytest.raises(env_init.GenerateError, match="generator for AGENT_SECRET") as info:
        env_init.generate_secret(runner, "AGENT_SECRET", "boom")
    assert "LEAKED-STDERR" not in str(info.value) and "PRINTED-VALUE" not in str(info.value)


def test_fill_secrets_generates_only_the_blank_ones_with_a_generator():
    """A set value is kept, a blank one is generated, and a key with no generator is left for the user."""
    runner = FakeRunner()
    runner.reply(sys.executable, "-c", "print(1)", stdout="one\n")
    runner.reply(sys.executable, "-c", "print(2)", stdout="two\n")
    assert env_init.fill_secrets(runner, EXAMPLE, {"AGENT_SECRET": "", "LLM_API_KEY": ""}) == {
        "AGENT_SECRET": "one",
        "REDIS_PASSWORD": "two",
    }
    assert env_init.fill_secrets(runner, EXAMPLE, {"AGENT_SECRET": "keep", "REDIS_PASSWORD": "kept"}) == {}


def test_the_example_in_the_repository_has_a_generator_for_every_required_secret():
    """The real `.env.example` can be filled: every secret `doctor` requires has a one-liner."""
    example = Path(__file__).resolve().parents[3] / ".env.example"
    keys = env_init.envfile.generators(example.read_text())
    required = ["AGENT_SECRET", "REDIS_PASSWORD", "ADMIN_DB_PASSWORD", "BACKEND_JWT_SECRET", "ADMIN_DB_ENCRYPTION_KEY"]
    assert [key for key in required if key not in keys] == []
