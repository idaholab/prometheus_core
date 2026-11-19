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

"""The e2e stack (`make up-e2e`) gets DeepLynx and LLM settings every SDK agent accepts at startup.

.env.example leaves the DEEPLYNX_* credentials and the LLM profile blank, and an agent
can't start without them. The stack sets made-up ones in the Makefile's E2E_STACK, so a
fresh clone's `make up-e2e` comes up. These tests apply E2E_STACK to a Makefile next to
a copy of .env.example, as `up-e2e` does, and run the SDK's own checks on what a recipe
then sees. Nothing here needs Docker.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs GNU make")

DEEPLYNX = ("DEEPLYNX_KEY", "DEEPLYNX_SECRET", "DEEPLYNX_JWT_TOKEN", "DEEPLYNX_ORG_ID", "DEEPLYNX_PROJECT_ID")

# Extra targets for the copied Makefile: the stack's variables, and what a recipe sees under them
PROBE = """\
show-e2e:
\t@printf '%s\\n' '$(E2E_STACK)'
show-env:
\t@env
"""


def clean_env() -> dict[str, str]:
    # Nothing from the developer's shell: DEEPLYNX_*, LOCAL_*, MAKE* or a compose setting
    prefixes = ("DEEPLYNX_", "LLM_", "EMBEDDING_", "LOCAL_", "MAKE", "COMPOSE_")
    return {k: v for k, v in os.environ.items() if not k.startswith(prefixes)}


def make(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["make", "-f", "Makefile", "-f", "probe.mk", "--no-print-directory", *args],
        cwd=root,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def platform(tmp_path: Path, project_root: Path) -> Path:
    """The Makefile beside a fresh clone's .env: .env.example as shipped, DEEPLYNX_* blank."""
    root = tmp_path / "platform"
    root.mkdir()
    shutil.copy(project_root / "Makefile", root)
    shutil.copy(project_root / ".env.example", root / ".env")
    (root / "probe.mk").write_text(PROBE)
    return root


def stack_args(root: Path) -> list[str]:
    """E2E_STACK as the `NAME=value` arguments `up-e2e` hands to the make it starts."""
    return shlex.split(make(root, "show-e2e", "ENV_READY=true"))


def recipe_env(root: Path, *args: str) -> dict[str, str]:
    """What the container gets: a variable make exports to the recipe, else the .env line.

    make exports only command-line and environment variables; the ones `include .env` defines
    stay make's own. Compose reads .env itself, and a variable in its shell environment wins
    over that file (checked against `docker compose config`, which these tests don't need).
    """
    lines = make(root, "show-env", "ENV_READY=true", *args).splitlines()
    exported = dict(line.split("=", 1) for line in lines if "=" in line)
    dotenv = dict(
        line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line and line[0] != "#"
    )
    return {**dotenv, **exported}


def test_a_fresh_clones_blank_deeplynx_settings_fail_the_agents_check(platform):
    """The starting point: with .env as shipped, a recipe sees blank values and the SDK refuses them."""
    from prometheus_api.agent.base import PrometheusAgent

    env = recipe_env(platform)
    assert not any(env.get(name) for name in DEEPLYNX), "the .env copy should leave DEEPLYNX_* blank"
    with pytest.MonkeyPatch.context() as mp:
        for name in DEEPLYNX:
            mp.setenv(name, env.get(name, ""))
        with pytest.raises(RuntimeError, match="Invalid required DeepLynx configuration"):
            PrometheusAgent._validate_deeplynx_configuration()


def test_up_e2e_gives_the_agents_deeplynx_settings_their_startup_check_accepts(platform):
    """E2E_STACK beats the blank .env lines, and the SDK accepts what is left."""
    from prometheus_api.agent.base import PrometheusAgent

    env = recipe_env(platform, *stack_args(platform))
    with pytest.MonkeyPatch.context() as mp:
        for name in DEEPLYNX:
            mp.setenv(name, env.get(name, ""))
        PrometheusAgent._validate_deeplynx_configuration()  # raises on a missing or conflicting value


def test_a_developers_deeplynx_token_stays_out_of_the_e2e_stack(platform):
    """The SDK refuses a token together with a key, so the stack must not pass a real one on."""
    env_file = platform / ".env"
    env_file.write_text(env_file.read_text().replace("DEEPLYNX_JWT_TOKEN=\n", "DEEPLYNX_JWT_TOKEN=real.jwt.token\n"))
    assert "DEEPLYNX_JWT_TOKEN=real.jwt.token" in env_file.read_text()
    assert recipe_env(platform).get("DEEPLYNX_JWT_TOKEN") == "real.jwt.token"
    assert recipe_env(platform, *stack_args(platform)).get("DEEPLYNX_JWT_TOKEN") == ""


def test_the_e2e_stack_does_not_read_a_developers_real_deeplynx_credentials(platform):
    """A real key in .env must not reach a stack that only needs made-up ones."""
    env_file = platform / ".env"
    env_file.write_text(env_file.read_text().replace("DEEPLYNX_KEY=\n", "DEEPLYNX_KEY=my-real-key\n"))
    assert recipe_env(platform).get("DEEPLYNX_KEY") == "my-real-key"
    assert recipe_env(platform, *stack_args(platform)).get("DEEPLYNX_KEY") != "my-real-key"


LLM = ("LLM_CONFIG_PROFILE", "LLM_CONFIG_FILE", "LLM_API_KEY", "EMBEDDING_API_KEY")


def test_up_e2e_gives_the_agents_an_llm_profile_the_sdk_loads(platform):
    """A fresh clone's blank profile is replaced by one the SDK's LLM config accepts, with its key."""
    from prometheus_api.llm_client.config import LLMConfig

    assert not recipe_env(platform).get("LLM_CONFIG_PROFILE"), "the .env copy should leave the profile blank"
    env = recipe_env(platform, *stack_args(platform))
    assert env["LLM_CONFIG_PROFILE"] and env["LLM_API_KEY"]
    config = LLMConfig.from_env(env={name: env.get(name, "") for name in LLM})
    assert config.config_file.stem == env["LLM_CONFIG_PROFILE"]


@pytest.mark.parametrize(
    "real",
    ["LLM_API_KEY=sk-my-real-key", "EMBEDDING_API_KEY=my-real-embedding-key", "LLM_CONFIG_FILE=/my/custom.yaml"],
)
def test_the_e2e_stack_does_not_read_a_developers_real_llm_settings(platform, real):
    """A real key, or a custom config that would replace the stack's profile, stays out of the stack."""
    name, value = real.split("=", 1)
    env_file = platform / ".env"
    env_file.write_text(env_file.read_text().replace(f"\n{name}=\n", f"\n{real}\n", 1))
    assert recipe_env(platform).get(name) == value
    assert recipe_env(platform, *stack_args(platform)).get(name) != value


def test_the_e2e_stack_publishes_its_ports_on_loopback_only(platform):
    """Its admin's password is in the repo, so other machines must not reach its ports.

    Docker Engine's port rules bypass ufw and firewalld, so publishing on 127.0.0.1 is what
    keeps them off the network. Compose reads PUBLISH_ADDR from the recipe's environment.
    """
    assert recipe_env(platform, *stack_args(platform)).get("PUBLISH_ADDR") == "127.0.0.1"
    assert not recipe_env(platform).get("PUBLISH_ADDR"), "a dev stack keeps Docker's default"
