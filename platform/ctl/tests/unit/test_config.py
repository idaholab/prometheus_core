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

from pathlib import Path

import pytest

from platformctl import config as cfg
from platformctl.config import ConfigError, PlatformConfig, make_overrides, parse_set


def make(tmp_path: Path, dotenv: str | None = None, env: dict | None = None, sets: dict | None = None):
    """Settings over a temporary folder, optionally with a `.env`."""
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv)
    return PlatformConfig(tmp_path, env or {}, sets)


# -- precedence: defaults < environment < .env < make < --set ---------------------------------


@pytest.mark.parametrize(
    ("env", "dotenv", "sets", "expected", "source"),
    [
        ({}, None, {}, "8600", "default"),
        ({"BACKEND_PORT": "1"}, None, {}, "1", "environment"),
        ({"BACKEND_PORT": "1"}, "BACKEND_PORT=2\n", {}, "2", ".env"),
        ({"BACKEND_PORT": "1"}, "BACKEND_PORT=2\n", {"BACKEND_PORT": "3"}, "3", "--set"),
        ({}, "BACKEND_PORT=2\n", {"BACKEND_PORT": "3"}, "3", "--set"),
        ({}, "BACKEND_PORT=2\n", {}, "2", ".env"),
        ({"BACKEND_PORT": "1"}, None, {"BACKEND_PORT": "3"}, "3", "--set"),
        ({}, None, {"BACKEND_PORT": "3"}, "3", "--set"),
    ],
)
def test_precedence(tmp_path, env, dotenv, sets, expected, source):
    """Defaults lose to the environment, which loses to `.env`, which loses to `--set`.

    Covers REQ-002-01.
    """
    value = make(tmp_path, dotenv, env, sets).resolve("BACKEND_PORT")
    assert (value.value, value.source) == (expected, source)


def test_a_blank_env_line_wins_over_the_environment(tmp_path):
    """A blank env line wins over the environment.

    Covers REQ-002-02.
    """
    config = make(tmp_path, "PROFILE=\n", {"PROFILE": "prod"})
    assert config.get("PROFILE") == ""
    assert config.frontend_profile() == ""


def test_blank_base_image_falls_back_to_the_default(tmp_path):
    """Blank base image falls back to the default.

    Covers REQ-002-02.
    """
    config = make(tmp_path, "PROMETHEUS_API_BASE_IMAGE_HASH=\nPROMETHEUS_API_BASE_IMAGE_REPO=\n")
    assert config.base_image() == (cfg.DEFAULT_BASE_IMAGE_REPO, cfg.DEFAULT_BASE_IMAGE_HASH)
    assert config.resolve("PROMETHEUS_API_BASE_IMAGE_HASH").source == "default"


def test_local_sdk_overrides_the_pin(tmp_path):
    """Local sdk overrides the pin.

    Covers REQ-002-03, BEH-002-01.
    """
    config = make(tmp_path, 'LOCAL_SDK="true"\nPROMETHEUS_API_BASE_IMAGE_HASH=abc\n')
    assert config.local_sdk  # dotenv rules: the quotes are stripped
    assert config.base_image() == ("prometheus_api", "local")


def test_unknown_key_resolves_to_blank_default(tmp_path):
    """Unknown key resolves to blank default."""
    assert make(tmp_path).resolve("NOT_A_SETTING").value == ""


def test_resolve_is_cached(tmp_path):
    """Resolving a setting twice gives the same object."""
    config = make(tmp_path)
    assert config.resolve("BACKEND_PORT") is config.resolve("BACKEND_PORT")


def test_int_and_flag(tmp_path):
    """Numeric and boolean settings convert, and a blank or bad number raises.

    Covers REQ-002-07.
    """
    config = make(tmp_path, "BACKEND_PORT=9000\nDEBUG_AGENTS=TRUE\nCLIENT_AGENT_PORT=abc\nREDIS_LOCAL_PORT=\n")
    assert config.int("BACKEND_PORT") == 9000
    assert config.flag("DEBUG_AGENTS")
    assert not config.flag("OPTIONAL_AGENTS")
    with pytest.raises(ConfigError, match="CLIENT_AGENT_PORT must be a number"):
        config.int("CLIENT_AGENT_PORT")
    with pytest.raises(ConfigError, match="blank"):
        config.int("REDIS_LOCAL_PORT")


def test_project_falls_back_when_blank(tmp_path):
    """Project falls back when blank.

    Covers REQ-002-06.
    """
    assert make(tmp_path, "COMPOSE_PROJECT_NAME=\n").project == "prometheus_platform"
    assert make(tmp_path, "COMPOSE_PROJECT_NAME=second\n").project == "second"


@pytest.mark.parametrize(("profile", "expected"), [("dev", "dev"), ("prod", "prod"), ("", ""), ("other", "")])
def test_frontend_profile(tmp_path, profile, expected):
    """Only `dev` and `prod` are frontends; anything else is none.

    Covers REQ-002-08.
    """
    assert make(tmp_path, f"PROFILE={profile}\n").frontend_profile() == expected


def test_registry_is_consistent():
    """The registry has no duplicates, and the derived keys and `PLATFORM_SOURCE` are in it."""
    assert len(cfg.REGISTRY) == len(cfg.SETTINGS)
    assert cfg.REGISTRY["PLATFORM_SOURCE"].default == "build"
    for key in cfg.DERIVED_KEYS:
        assert key in cfg.REGISTRY


# -- --set ------------------------------------------------------------------------------------


def test_parse_set():
    """`--set` pairs parse, including a blank value."""
    assert parse_set(["BACKEND_PORT=1", "PROFILE="]) == {"BACKEND_PORT": "1", "PROFILE": ""}


@pytest.mark.parametrize("item", ["NOEQUALS", "=value"])
def test_parse_set_needs_key_value(item):
    """Parse set needs key value."""
    with pytest.raises(ConfigError, match="KEY=VALUE"):
        parse_set([item])


@pytest.mark.parametrize(
    ("item", "shown"),
    [
        ("NOEQUALS", True),  # looks like a setting name: safe to show
        ("sk-ant-NOTINDOTENV123456", False),  # `--set $LLM_API_KEY`: a value, not a name
        ("=sk-ant-NOTINDOTENV123456", False),
        ("sk-ant-NOTINDOTENV123456=x", False),  # a value in the key position
    ],
)
def test_parse_set_errors_do_not_echo_what_might_be_a_secret(item, shown):
    """Only text shaped like a setting name is echoed; the scrubber doesn't know a value outside `.env`.

    Covers REQ-003-08.
    """
    with pytest.raises(ConfigError) as info:
        parse_set([item])
    assert ("NOEQUALS" in str(info.value)) is shown
    assert "NOTINDOTENV" not in str(info.value)


@pytest.mark.parametrize("key", ["LLM_API_KEY", "AGENT_SECRET", "SOMETHING_UNKNOWN"])
def test_parse_set_refuses_secrets_and_unknown_keys(key):
    """Parse set refuses secrets and unknown keys.

    Covers REQ-003-10, BEH-003-03.
    """
    with pytest.raises(ConfigError) as info:
        parse_set([f"{key}=hunter2hunter2"])
    assert f"set {key} in .env instead" in str(info.value)
    assert "hunter2" not in str(info.value)


# -- make -------------------------------------------------------------------------------------


def test_make_overrides_reads_names_from_makeflags_and_values_from_env():
    """Make overrides reads names from makeflags and values from env.

    Covers REQ-002-04.
    """
    env = {
        "PLATFORMCTL_VIA_MAKE": "1",
        "MAKEFLAGS": r" -- BACKEND_PORT=9 UP_ARGS=a\ b\ 'q'",
        "BACKEND_PORT": "9",
        "UP_ARGS": "a b 'q'",
    }
    assert make_overrides(env) == {"BACKEND_PORT": "9", "UP_ARGS": "a b 'q'"}


def test_make_overrides_only_via_make_and_with_arguments():
    """Make overrides only via make and with arguments.

    Covers REQ-002-04.
    """
    assert make_overrides({"MAKEFLAGS": " -- A=1", "A": "1"}) == {}
    assert make_overrides({"PLATFORMCTL_VIA_MAKE": "1", "MAKEFLAGS": "w"}) == {}
    # A name in MAKEFLAGS with no value in the environment is ignored.
    assert make_overrides({"PLATFORMCTL_VIA_MAKE": "1", "MAKEFLAGS": " -- GONE=1"}) == {}


def test_make_beats_dotenv_but_not_set(tmp_path):
    """Make beats dotenv but not set.

    Covers REQ-002-04, BEH-002-02.
    """
    env = {"PLATFORMCTL_VIA_MAKE": "1", "MAKEFLAGS": " -- BACKEND_PORT=7", "BACKEND_PORT": "7"}
    config = make(tmp_path, "BACKEND_PORT=2\n", env)
    assert config.resolve("BACKEND_PORT") == cfg.Value("7", "make")
    config = make(tmp_path, "BACKEND_PORT=2\n", env, {"BACKEND_PORT": "3"})
    assert config.get("BACKEND_PORT") == "3"


# -- child environment ------------------------------------------------------------------------


def test_child_env(tmp_path):
    """The child environment drops Make's variables, prefers `.env` over the environment and adds the derived values."""
    env = {
        "PATH": "/bin",
        "MAKEFLAGS": " -- BACKEND_PORT=7",
        "MFLAGS": "x",
        "MAKELEVEL": "1",
        "MAKEOVERRIDES": "y",
        "PLATFORMCTL_VIA_MAKE": "1",
        "BACKEND_PORT": "7",
        "REDIS_PASSWORD": "from-environment",
        "UNRELATED": "u",
    }
    config = make(tmp_path, "REDIS_PASSWORD=from-dotenv\nOTHER=left-for-compose\n", env, {"PROFILE": "prod"})
    child = config.child_env({"EXTRA": "1"})
    for name in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "PLATFORMCTL_VIA_MAKE"):
        assert name not in child
    assert child["REDIS_PASSWORD"] == "from-dotenv"  # .env wins over the environment, as in Make
    assert "OTHER" not in child  # other .env keys are left for Compose to read
    assert child["UNRELATED"] == "u"
    assert child["BACKEND_PORT"] == "7"
    assert child["PROFILE"] == "prod"
    assert child["EXTRA"] == "1"
    assert child["COMPOSE_PROJECT_NAME"] == "prometheus_platform"
    assert child["PROMETHEUS_API_BASE_IMAGE_HASH"] == cfg.DEFAULT_BASE_IMAGE_HASH


def test_child_env_ignores_unknown_make_variables(tmp_path):
    """Child env ignores unknown make variables.

    Covers REQ-002-05.
    """
    env = {"PLATFORMCTL_VIA_MAKE": "1", "MAKEFLAGS": " -- WHATEVER=1", "WHATEVER": "1"}
    config = make(tmp_path, None, env)
    assert config.make == {"WHATEVER": "1"}
    # Not a registered setting: it isn't copied over as a setting (it stays in the environment as given).
    assert config.child_env()["WHATEVER"] == "1"
    assert "WHATEVER" not in cfg.REGISTRY


# -- what hides what --------------------------------------------------------------------------


def test_hidden_by_dotenv_and_env_hiding_value(tmp_path):
    """Hidden by dotenv and env hiding value."""
    config = make(tmp_path, "BUILD_CACHE=x\nA=1\nB=same\n", {"A": "2", "B": "same"})
    assert config.hidden_by_dotenv() == ["BUILD_CACHE"]
    assert config.env_hiding_value() == ["A"]  # B is the same value, so nothing is hidden


# -- secrets ----------------------------------------------------------------------------------


def test_secret_values_and_keys(tmp_path):
    """Secret values come from `.env`, `--set` and secret-looking environment names, never from safe keys.

    Covers REQ-003-01, REQ-003-02.
    """
    config = make(
        tmp_path,
        "LLM_API_KEY=fake-dotenv-secret\nBACKEND_PORT=9999\nBLANK=\n",
        {
            "LLM_API_KEY": "fake-environment-secret",
            "PATH": "/usr/bin:/bin",
            "MY_TOKEN": "fake-token-value",
            "BACKEND_PORT": "1",
        },
        {"PROFILE": "dev"},
    )
    values = config.secret_values()
    assert "fake-dotenv-secret" in values
    assert "fake-environment-secret" in values  # the environment's value of a key .env sets
    assert "fake-token-value" in values  # a name that looks like a secret
    assert "/usr/bin:/bin" not in values
    assert "9999" not in values  # a registered, safe key
    assert config.secret_keys() == ["BLANK", "LLM_API_KEY"]


def test_is_safe_denies_by_default():
    """Is safe denies by default.

    Covers REQ-003-01.
    """
    assert cfg.is_safe("BACKEND_PORT")
    assert not cfg.is_safe("LLM_API_KEY")
    assert not cfg.is_safe("ANYTHING_ELSE")


# -- version and architecture -----------------------------------------------------------------


def test_platform_version(tmp_path):
    """The version is the git date and hash, or `unknown` when git fails or prints nothing."""
    from platformctl.system.runner import Result, RunnerError

    class Fake:
        def __init__(self, result=None, error=None):
            """Keep the canned result or error."""
            self.result, self.error = result, error

        def run(self, argv, **_):
            """Return the canned result, or raise the canned error."""
            if self.error:
                raise self.error
            return self.result

    assert cfg.platform_version(tmp_path, Fake(Result([], 0, "2026-10-30-abc1234\n"))) == "2026-10-30-abc1234"
    assert cfg.platform_version(tmp_path, Fake(Result([], 128, ""))) == "unknown"
    assert cfg.platform_version(tmp_path, Fake(Result([], 0, "\n"))) == "unknown"
    assert cfg.platform_version(tmp_path, Fake(error=RunnerError("no git"))) == "unknown"


@pytest.mark.parametrize(
    ("arch", "expected"), [("aarch64", "arm64"), ("ARM64", "arm64"), ("x86_64", "amd64"), (None, None)]
)
def test_host_arch(arch, expected, monkeypatch):
    """Docker's `aarch64` and `arm64` map to `arm64`, anything else to `amd64`."""
    if arch is None:
        monkeypatch.setattr(cfg._platform, "machine", lambda: "arm64")
        expected = "arm64"
    assert cfg.host_arch(arch) == expected


def test_now_iso():
    """The timestamp ends in `Z`."""
    assert cfg.now_iso().endswith("Z")


def test_a_malformed_dotenv_is_recorded_and_raised_only_on_demand(tmp_path):
    """A malformed dotenv is recorded and raised only on demand."""
    from platformctl.system import envfile

    config = make(tmp_path, "this is not valid\n")
    assert isinstance(config.dotenv_error, envfile.EnvFileError)
    assert config.dotenv == {}
    with pytest.raises(envfile.EnvFileError, match="line 1"):
        config.require_valid_dotenv()
    make(tmp_path, "A=1\n").require_valid_dotenv()
