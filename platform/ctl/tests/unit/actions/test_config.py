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
import stat
import sys

import pytest

from platformctl.actions import config as config_action
from platformctl.system import envfile, terminal
from tests.unit.conftest import assert_golden, make_context

DOTENV = "BACKEND_PORT=9000\nLLM_API_KEY=value-held-in-the-env-1\nCUSTOM_FLAG=on\nEMPTY_SECRET=\n"
"""A `.env` with a registered setting, a secret, an unregistered key and a blank secret."""


def sub(name: str):
    """The `config` subcommand with this name."""
    return next(s for s in config_action.SUBCOMMANDS if s.NAME == name)


def parse(name: str, *argv: str) -> argparse.Namespace:
    """Parse a subcommand's own arguments."""
    parser = argparse.ArgumentParser()
    sub(name).add_arguments(parser)
    return parser.parse_args(list(argv))


@pytest.fixture
def ctx_env(platform_root, runner):
    """A context over a platform folder with a `.env` (mode 0600) and an environment holding some values."""
    (platform_root / ".env").write_text(DOTENV)
    (platform_root / ".env").chmod(0o600)

    def factory(env=None, **kw):
        """Build the context with this environment."""
        return make_context(platform_root, runner, {"PATH": "/usr/bin", **(env or {})}, **kw)

    return factory


def test_the_group_lists_its_subcommands():
    """`config` offers `init`, `set` and `show`."""
    assert {s.NAME for s in config_action.SUBCOMMANDS} >= {"set", "show"}


def test_set_writes_in_place_and_keeps_the_rest(ctx_env, platform_root):
    """A registered setting is rewritten where it is; every other line is kept; the mode is kept."""
    ctx, out, _ = ctx_env()
    assert config_action.set_values(ctx, parse("set", "BACKEND_PORT=9100", "PROFILE=prod")) == 0
    assert envfile.read(platform_root / ".env") == {
        "BACKEND_PORT": "9100",
        "LLM_API_KEY": "value-held-in-the-env-1",
        "CUSTOM_FLAG": "on",
        "EMPTY_SECRET": "",
        "PROFILE": "prod",
    }
    assert stat.S_IMODE((platform_root / ".env").stat().st_mode) == 0o600
    assert out.getvalue() == "Set BACKEND_PORT, PROFILE in .env.\n"


def test_set_tightens_a_world_readable_env_and_says_so(ctx_env, platform_root):
    """Commands that add secrets don't leave them in a 0644 file."""
    (platform_root / ".env").chmod(0o644)
    ctx, _, err = ctx_env()
    assert config_action.set_values(ctx, parse("set", "BACKEND_PORT=9100")) == 0
    assert stat.S_IMODE((platform_root / ".env").stat().st_mode) == 0o600
    assert ".env was readable by other users (mode 0644); it is now owner-only (0600)." in err.getvalue()


def test_set_refuses_a_secret_key_and_writes_nothing(ctx_env, platform_root):
    """A secret on the command line would reach history and `ps`: refused, with the way to do it."""
    ctx, _, err = ctx_env()
    code = config_action.set_values(
        ctx, parse("set", "BACKEND_PORT=9100", "LLM_API_KEY=value-given-on-the-command-line-22")
    )
    assert code == 1
    assert "LLM_API_KEY can't be set with config set" in err.getvalue()
    assert "config set --from-env LLM_API_KEY" in err.getvalue()
    assert "value-given-on-the-command-line-22" not in err.getvalue()
    assert (platform_root / ".env").read_text() == DOTENV


@pytest.mark.parametrize(
    ("pair", "message"),
    [
        ("BACKEND_PORT=abc", "BACKEND_PORT must be a number, got 'abc'"),
        ("BACKEND_PORT=", "BACKEND_PORT must be a number"),
        ("LOCAL_SDK=yes", "LOCAL_SDK must be true or false, got 'yes'"),
        ("LOCAL_SDK=True", "LOCAL_SDK must be true or false"),
    ],
)
def test_set_refuses_a_value_the_setting_cannot_hold(ctx_env, platform_root, pair, message):
    """`BACKEND_PORT=abc` would only fail on the next command, and `LOCAL_SDK=yes` reads as off: refuse, write nothing."""
    ctx, _, err = ctx_env()
    assert config_action.set_values(ctx, parse("set", "PROFILE=prod", pair)) == 1
    assert message in err.getvalue()
    assert (platform_root / ".env").read_text() == DOTENV


def test_set_checks_values_given_through_from_env_too(ctx_env, platform_root):
    """A registered setting copied from the environment is checked like one given as KEY=value."""
    ctx, _, err = ctx_env({"BACKEND_PORT": "not-a-port"})
    assert config_action.set_values(ctx, parse("set", "--from-env", "BACKEND_PORT")) == 1
    assert "BACKEND_PORT must be a number" in err.getvalue()
    assert (platform_root / ".env").read_text() == DOTENV


def test_set_accepts_a_path_and_a_url_setting(ctx_env, platform_root):
    """`LLM_CONFIG_FILE` and `DEEPLYNX_BASE_URL` hold a path and a URL, not secrets, so `config set` takes them."""
    ctx, _, _ = ctx_env()
    assert (
        config_action.set_values(
            ctx, parse("set", "LLM_CONFIG_FILE=/etc/llm.yaml", "DEEPLYNX_BASE_URL=https://deeplynx.example/api/v1")
        )
        == 0
    )
    values = envfile.read(platform_root / ".env")
    assert values["LLM_CONFIG_FILE"] == "/etc/llm.yaml"
    assert values["DEEPLYNX_BASE_URL"] == "https://deeplynx.example/api/v1"


def test_set_accepts_any_value_for_a_text_setting(ctx_env, platform_root):
    """A `str` setting has no type to check, so any value is written."""
    ctx, _, _ = ctx_env()
    assert config_action.set_values(ctx, parse("set", "UP_ARGS=--build --quiet-pull")) == 0
    assert envfile.read(platform_root / ".env")["UP_ARGS"] == "--build --quiet-pull"


def test_set_rejects_a_pair_without_an_equals_sign(ctx_env):
    """`config set BACKEND_PORT` is a mistake, named as such."""
    ctx, _, err = ctx_env()
    assert config_action.set_values(ctx, parse("set", "BACKEND_PORT")) == 1
    assert "config set expects KEY=VALUE" in err.getvalue()


def test_set_without_an_env_file_says_to_run_init(platform_root, runner):
    """There is nothing to edit before `config init`."""
    ctx, _, err = make_context(platform_root, runner)
    assert config_action.set_values(ctx, parse("set", "BACKEND_PORT=1")) == 1
    assert ".env does not exist; run ./platformctl config init first" in err.getvalue()
    assert not (platform_root / ".env").exists()


def test_set_dry_run_writes_nothing(ctx_env, platform_root):
    """`--dry-run` says what it would do."""
    ctx, out, _ = ctx_env(dry_run=True)
    assert config_action.set_values(ctx, parse("set", "BACKEND_PORT=9100")) == 0
    assert out.getvalue() == "Would set BACKEND_PORT in .env.\n"
    assert (platform_root / ".env").read_text() == DOTENV


def test_from_env_copies_values_without_them_appearing_in_argv_or_output(ctx_env, platform_root):
    """A secret is read from the environment: it is in `.env`, and in no output."""
    secret = "value-from-the-environment-33"
    ctx, out, err = ctx_env({"LLM_API_KEY": secret, "NEW_SECRET": "another-secret-44"})
    assert config_action.set_values(ctx, parse("set", "--from-env", "LLM_API_KEY", "NEW_SECRET")) == 0
    values = envfile.read(platform_root / ".env")
    assert values["LLM_API_KEY"] == secret and values["NEW_SECRET"] == "another-secret-44"
    assert secret not in out.getvalue() + err.getvalue()
    assert out.getvalue() == "Set LLM_API_KEY, NEW_SECRET in .env.\n"


def test_from_env_names_every_key_that_is_not_set(ctx_env, platform_root):
    """Exit 1 naming each missing key we know, writing nothing; a blank value counts as not set."""
    ctx, _, err = ctx_env({"HAVE": "x" * 12, "EMPTY_SECRET": ""})
    assert config_action.set_values(ctx, parse("set", "--from-env", "HAVE", "EMPTY_SECRET", "BACKEND_PORT")) == 1
    assert "not set in the environment: EMPTY_SECRET, BACKEND_PORT" in err.getvalue()
    assert (platform_root / ".env").read_text() == DOTENV


def test_from_env_does_not_echo_a_name_it_does_not_know(ctx_env, platform_root):
    """A secret pasted as `--from-env "$SECRET"` looks like a name: it is counted, never printed."""
    pasted = "sk0123456789abcdefPASTEDSECRET"
    ctx, _, err = ctx_env({"HAVE": "x" * 12})
    assert config_action.set_values(ctx, parse("set", "--from-env", "BACKEND_PORT", pasted)) == 1
    assert pasted not in err.getvalue()
    assert "not set in the environment: BACKEND_PORT; 1 other name(s)" in err.getvalue()


def test_from_env_does_not_echo_a_name_in_json_either(ctx_env, capsys):
    """The JSON error object carries the same message, so the same rule holds."""
    pasted = "sk0123456789abcdefPASTEDSECRET"
    ctx, out, _ = ctx_env(json_mode=True)
    assert config_action.set_values(ctx, parse("set", "--from-env", pasted)) == 1
    assert pasted not in out.getvalue()
    assert "1 other name(s)" in out.getvalue()


@pytest.mark.parametrize(
    ("item", "value"),
    [("KEY=sentinelvalue77", "sentinelvalue77"), ("bad-name", None), ("has space", None), ("1ABCDEFG", None)],
)
def test_from_env_takes_names_not_pairs(ctx_env, item, value):
    """`--from-env KEY=value` would put a value in argv, so it is refused without echoing it."""
    ctx, _, err = ctx_env()
    assert config_action.set_values(ctx, parse("set", "--from-env", item)) == 1
    assert "expects key names" in err.getvalue()
    assert value is None or value not in err.getvalue()


def test_set_does_not_write_over_a_malformed_env_file(platform_root, runner):
    """A `.env` that doesn't parse raises (`cli.main` reports it as `config_invalid`) and is left as it is."""
    (platform_root / ".env").write_text("not a pair\n")
    ctx, _, _ = make_context(platform_root, runner)
    with pytest.raises(envfile.EnvFileError, match="line 1"):
        config_action.set_values(ctx, parse("set", "BACKEND_PORT=1"))
    assert (platform_root / ".env").read_text() == "not a pair\n"


def test_set_failure_is_one_json_object(ctx_env):
    """With `--json`, a refusal is the usual error object."""
    ctx, out, _ = ctx_env(json_mode=True)
    assert config_action.set_values(ctx, parse("set", "LLM_API_KEY=value-given-on-the-command-line-22")) == 1
    body = json.loads(out.getvalue())
    assert body["ok"] is False and body["error"]["code"] == "config_invalid" and body["command"] == "config set"


def test_set_json_success_is_one_object_naming_the_keys(ctx_env):
    """With `--json`, a successful write is one object: the keys written, never their values."""
    ctx, out, _ = ctx_env(json_mode=True)
    assert config_action.set_values(ctx, parse("set", "BACKEND_PORT=9100", "PROFILE=prod")) == 0
    body = json.loads(out.getvalue())
    assert body["command"] == "config set" and body["ok"] is True and body["keys"] == ["BACKEND_PORT", "PROFILE"]
    assert "9100" not in out.getvalue()


def test_set_json_dry_run_says_so(ctx_env):
    """A dry run is reported as one, so a script can tell nothing was written."""
    ctx, out, _ = ctx_env(json_mode=True, dry_run=True)
    assert config_action.set_values(ctx, parse("set", "BACKEND_PORT=9100")) == 0
    assert json.loads(out.getvalue())["dry_run"] is True


def test_show_prints_secrets_as_set_or_blank_with_their_source(ctx_env):
    """A table of settings: safe values as they are, secrets as `set`/`blank`, and where each came from."""
    ctx, out, _ = ctx_env({"CLIENT_AGENT_PORT": "8100"})
    assert config_action.show(ctx, parse("show")) == 0
    lines = {line.split()[0]: line for line in out.getvalue().splitlines()}
    assert lines["BACKEND_PORT"].split() == ["BACKEND_PORT", "9000", ".env"]
    assert lines["CLIENT_AGENT_PORT"].split() == ["CLIENT_AGENT_PORT", "8100", "environment"]
    assert lines["COMPOSE_PROJECT_NAME"].split() == ["COMPOSE_PROJECT_NAME", "prometheus_platform", "default"]
    assert lines["LLM_API_KEY"].split() == ["LLM_API_KEY", "set", ".env"]
    assert lines["EMPTY_SECRET"].split() == ["EMPTY_SECRET", "blank", ".env"]
    # A key the registry doesn't know is secret by default, so even a harmless-looking value is hidden.
    assert lines["CUSTOM_FLAG"].split() == ["CUSTOM_FLAG", "set", ".env"]
    assert "value-held-in-the-env-1" not in out.getvalue()


def test_show_json_is_pinned(ctx_env, platform_root):
    """The golden file pins the object a skill reads."""
    ctx, out, _ = ctx_env(json_mode=True)
    assert config_action.show(ctx, parse("show")) == 0
    body = json.loads(out.getvalue())
    assert "value-held-in-the-env-1" not in out.getvalue()
    assert_golden("config_show", body, platform_root)


# -- config init --------------------------------------------------------------------------------

EXAMPLE = (
    "LLM_CONFIG_PROFILE=\nLLM_API_KEY=\nLLM_CONFIG_FILE=\n"
    '# one\n#   python3 -c "print(1)"\nAGENT_SECRET=\n'
    '# two\n#   python3 -c "print(2)"\nREDIS_PASSWORD=\n'
    "NEW_KEY=default\n"
)
"""A `.env.example` with the LLM keys, two generated secrets and a plain key."""


@pytest.fixture
def init_root(platform_root):
    """A platform folder with a `.env.example` and the SDK's profiles (one keyed, one keyless) beside it."""
    (platform_root / ".env.example").write_text(EXAMPLE)
    profiles = platform_root.parent / "sdk" / "prometheus_api" / "llm_configs"
    profiles.mkdir(parents=True)
    (profiles / "anthropic.yaml").write_text("# Anthropic. x\nk: os.environ/LLM_API_KEY\n")
    (profiles / "ollama.yaml").write_text("# Local models. x\napi_key: none\n")
    (profiles / "registry.yaml").write_text("# Proxy. x\nk: os.environ/LLM_API_KEY\n")
    return platform_root


@pytest.fixture
def init_ctx(init_root, runner, monkeypatch):
    """A context factory for `config init`: generators answer, no terminal, the registry unreachable."""
    runner.reply(sys.executable, "-c", "print(1)", stdout="generated-secret-one\n")
    runner.reply(sys.executable, "-c", "print(2)", stdout="generated-secret-two\n")
    runner.reply("docker", "manifest", "inspect", code=1)
    monkeypatch.setattr(terminal, "interactive", lambda: False)

    def factory(env=None, **kw):
        """Build the context with this environment."""
        return make_context(init_root, runner, {"PATH": "/usr/bin", **(env or {})}, **kw)

    return factory


def init_args(local_sdk=None, local_deeplynx=None) -> argparse.Namespace:
    """The parsed arguments of `config init`."""
    return argparse.Namespace(local_sdk=local_sdk, local_deeplynx=local_deeplynx)


def test_init_creates_env_from_the_example_and_reports_each_step_word_for_word(init_ctx, init_root):
    """A fresh clone with the profile and key in the environment, as in CI: the lines the slides quote."""
    ctx, out, err = init_ctx({"LLM_CONFIG_PROFILE": "anthropic", "LLM_API_KEY": "value-from-the-environment-1"})
    assert config_action.init(ctx, init_args()) == 0
    lines = out.getvalue().splitlines()
    assert lines[:6] == [
        "Created .env from .env.example.",
        "Generated in .env: AGENT_SECRET, REDIS_PASSWORD",
        "Saved LLM_CONFIG_PROFILE from the environment in .env.",
        "Saved LLM_API_KEY from the environment in .env.",
        "Local SDK: no (not asked without a terminal; use --local-sdk to turn it on)",
        "Local DeepLynx: no (not asked without a terminal; use --local-deeplynx to turn it on)",
    ]
    assert lines[6] == "LLM profile: anthropic, key set"
    assert lines[-1] == "Next: make up"
    values = envfile.read(init_root / ".env")
    assert values["AGENT_SECRET"] == "generated-secret-one" and values["LLM_API_KEY"] == "value-from-the-environment-1"
    assert stat.S_IMODE((init_root / ".env").stat().st_mode) == 0o600
    assert err.getvalue() == ""
    for secret in ("generated-secret-one", "generated-secret-two", "value-from-the-environment-1"):
        assert secret not in out.getvalue()


def test_init_without_a_terminal_and_without_a_profile_fails_as_the_script_did(init_ctx, init_root):
    """Exit 1 only for what `init_env.py` required: here, the profile. The new questions never fail it."""
    ctx, out, err = init_ctx()
    assert config_action.init(ctx, init_args()) == 1
    assert "[ERROR] LLM_CONFIG_PROFILE is empty in " in err.getvalue()
    assert "Available profiles: anthropic, ollama." in err.getvalue()
    assert "Local SDK: no (not asked without a terminal" in out.getvalue()


def test_init_without_a_terminal_names_the_flags_only_on_the_run_that_creates_env(init_ctx, init_root):
    """Every `make up` runs `config init`: after the first run the "not asked" note would only be noise."""
    first, out, _ = init_ctx({"LLM_CONFIG_PROFILE": "anthropic", "LLM_API_KEY": "value-from-the-environment-1"})
    assert config_action.init(first, init_args()) == 0
    assert "not asked without a terminal" in out.getvalue()
    for key in ("LOCAL_SDK", "LOCAL_DEEPLYNX"):  # the person never answered, so .env still doesn't decide them
        assert key not in envfile.read(init_root / ".env")
    again, out, _ = init_ctx({})
    assert config_action.init(again, init_args()) == 0
    assert "not asked" not in out.getvalue() and "Local SDK" not in out.getvalue()


def test_init_keeps_the_key_it_saved_when_run_again_with_another_one_in_the_environment(init_ctx, init_root):
    """A re-run (every `make up`) must not replace a saved key with whatever is exported now."""
    first = {"LLM_CONFIG_PROFILE": "anthropic", "LLM_API_KEY": "first-key-from-the-environment-1"}
    ctx, _, _ = init_ctx(first)
    assert config_action.init(ctx, init_args()) == 0
    other = {"LLM_CONFIG_PROFILE": "ollama", "LLM_API_KEY": "another-key-in-the-environment-2"}
    ctx, out, _ = init_ctx(other)
    assert config_action.init(ctx, init_args()) == 0
    values = envfile.read(init_root / ".env")
    assert values["LLM_API_KEY"] == "first-key-from-the-environment-1"
    assert values["LLM_CONFIG_PROFILE"] == "anthropic"
    assert "Saved LLM" not in out.getvalue()
    assert "another-key-in-the-environment-2" not in out.getvalue()


def test_init_names_a_missing_key_a_profile_needs(init_ctx, init_root):
    """The profile is chosen but its key is blank."""
    (init_root / ".env").write_text(EXAMPLE.replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=anthropic"))
    ctx, _, err = init_ctx()
    assert config_action.init(ctx, init_args()) == 1
    assert "[ERROR] LLM_API_KEY is empty in " in err.getvalue()
    assert "LLM_CONFIG_PROFILE=anthropic needs it" in err.getvalue()
    assert "In a script, export LLM_API_KEY first and it is saved for you." in err.getvalue()


@pytest.mark.parametrize(
    ("profile", "reason"),
    [("genisis", "is not an installed profile"), ("registry", "needs an LLM proxy at REGISTRY_URL")],
)
def test_init_rejects_a_profile_that_is_unknown_or_unsupported(init_ctx, init_root, profile, reason):
    """A typo, and the SDK's `registry` profile that has no proxy here."""
    (init_root / ".env").write_text(
        EXAMPLE.replace("LLM_CONFIG_PROFILE=", f"LLM_CONFIG_PROFILE={profile}").replace("LLM_API_KEY=", "LLM_API_KEY=k")
    )
    ctx, _, err = init_ctx()
    assert config_action.init(ctx, init_args()) == 1
    assert f"LLM_CONFIG_PROFILE={profile} in " in err.getvalue() and reason in err.getvalue()


def test_init_accepts_a_custom_llm_file_in_place_of_a_profile(init_ctx, init_root):
    """`LLM_CONFIG_FILE` replaces the profile and its key."""
    (init_root / ".env").write_text(EXAMPLE.replace("LLM_CONFIG_FILE=", "LLM_CONFIG_FILE=/custom.yaml"))
    ctx, out, _ = init_ctx()
    assert config_action.init(ctx, init_args()) == 0
    assert "LLM profile: custom file, key set" in out.getvalue()


def test_init_never_overwrites_a_value_that_is_set(init_ctx, init_root):
    """Existing values stay, including a profile and key the environment disagrees with."""
    (init_root / ".env").write_text(
        EXAMPLE.replace("AGENT_SECRET=", "AGENT_SECRET=mine")
        .replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=anthropic")
        .replace("LLM_API_KEY=", "LLM_API_KEY=my-own-key")
    )
    ctx, out, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama", "LLM_API_KEY": "other"})
    assert config_action.init(ctx, init_args()) == 0
    values = envfile.read(init_root / ".env")
    assert (values["AGENT_SECRET"], values["LLM_CONFIG_PROFILE"], values["LLM_API_KEY"]) == (
        "mine",
        "anthropic",
        "my-own-key",
    )
    assert "Created" not in out.getvalue() and "from the environment" not in out.getvalue()


def test_init_reports_the_keys_the_example_has_and_the_env_lacks(init_ctx, init_root):
    """A key added to `.env.example` after `.env` was made is listed."""
    (init_root / ".env").write_text(
        "LLM_CONFIG_PROFILE=ollama\nLLM_API_KEY=\nLLM_CONFIG_FILE=\nAGENT_SECRET=a\nREDIS_PASSWORD=b\n"
    )
    ctx, out, _ = init_ctx()
    assert config_action.init(ctx, init_args()) == 0
    assert "Keys in .env.example that .env lacks: NEW_KEY" in out.getvalue()


def test_init_asks_for_the_profile_and_key_on_a_terminal(init_ctx, init_root, monkeypatch):
    """The menu and the hidden key prompt, with the lines the slides quote."""
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "choose", lambda options, labels, default: "anthropic")
    monkeypatch.setattr(terminal, "read_secret", lambda prompt: "value-typed-by-the-user-9")
    monkeypatch.setattr(terminal, "confirm", lambda question, default: default)
    ctx, out, _ = init_ctx()
    assert config_action.init(ctx, init_args()) == 0
    assert "\nChoose an LLM profile (up/down, Enter):\n" in "\n" + out.getvalue()
    assert "Saved LLM_CONFIG_PROFILE=anthropic in .env." in out.getvalue()
    assert envfile.read(init_root / ".env")["LLM_API_KEY"] == "value-typed-by-the-user-9"
    assert "value-typed-by-the-user-9" not in out.getvalue()


def test_init_menu_marks_profiles_without_a_key_and_starts_on_the_current_one(init_ctx, init_root, monkeypatch):
    """The labels carry `[no key]`, and a profile already in `.env` is the menu's default."""
    seen = {}
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "confirm", lambda question, default: default)
    monkeypatch.setattr(
        terminal, "choose", lambda options, labels, default: seen.update(labels=labels, default=default) or "ollama"
    )
    # A profile that is installed but whose key is blank brings the menu up, starting on that profile.
    (init_root / ".env").write_text(EXAMPLE.replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=anthropic"))
    ctx, _, _ = init_ctx()
    config_action.init(ctx, init_args())
    assert seen["labels"] == ["Anthropic", "Local models  [no key]"] and seen["default"] == 0


def test_init_leaves_the_key_blank_when_the_user_presses_enter(init_ctx, init_root, monkeypatch):
    """An empty answer saves the profile only, and the run then fails naming the missing key."""
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "choose", lambda options, labels, default: "anthropic")
    monkeypatch.setattr(terminal, "read_secret", lambda prompt: "")
    monkeypatch.setattr(terminal, "confirm", lambda question, default: default)
    ctx, _, err = init_ctx()
    assert config_action.init(ctx, init_args()) == 1
    assert envfile.read(init_root / ".env")["LLM_API_KEY"] == ""
    assert "[ERROR] LLM_API_KEY is empty in " in err.getvalue()


def test_init_stops_rather_than_echo_a_key(init_ctx, monkeypatch):
    """A terminal that can't hide input is `needs_terminal`, and nothing is saved from it."""
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "choose", lambda options, labels, default: "anthropic")

    def echoing(prompt):
        """A terminal that would echo."""
        raise terminal.TerminalError("this terminal would echo the value as you type it, so it was not asked")

    monkeypatch.setattr(terminal, "read_secret", echoing)
    ctx, _, err = init_ctx()
    assert config_action.init(ctx, init_args()) == 1
    assert "would echo" in err.getvalue()


def test_init_does_not_ask_while_printing_json(init_ctx, monkeypatch):
    """`--json` never prompts, even on a terminal."""
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "choose", lambda *a: pytest.fail("asked"))
    ctx, out, err = init_ctx(json_mode=True)
    assert config_action.init(ctx, init_args()) == 1
    body = json.loads(out.getvalue())
    assert body["command"] == "config init" and body["ok"] is False
    assert body["error"]["code"] == "config_invalid" and "LLM_CONFIG_PROFILE is empty" in body["error"]["message"]
    assert "[ERROR]" not in err.getvalue(), "the failure is the one JSON object, not an error block"


def test_init_json_success_is_one_object_saying_what_it_did(init_ctx, init_root):
    """`--json config init` prints what an assistant needs: what was created, generated and chosen."""
    ctx, out, _ = init_ctx(
        {"LLM_CONFIG_PROFILE": "anthropic", "LLM_API_KEY": "value-from-the-environment-1"}, json_mode=True
    )
    assert config_action.init(ctx, init_args(local_sdk=True)) == 0
    body = json.loads(out.getvalue())
    assert body["command"] == "config init" and body["ok"] is True
    assert body["created"] is True and body["generated"] == ["AGENT_SECRET", "REDIS_PASSWORD"]
    assert body["llm_profile"] == "anthropic"
    assert (body["local_sdk"], body["local_deeplynx"]) == (True, False)
    assert body["missing_keys"] == []
    assert "value-from-the-environment-1" not in out.getvalue()


def test_init_json_failure_for_a_missing_key_has_the_usual_error_object(init_ctx):
    """A profile that needs a key we don't have is `config_invalid`, as one object."""
    ctx, out, _ = init_ctx({"LLM_CONFIG_PROFILE": "anthropic"}, json_mode=True)
    assert config_action.init(ctx, init_args()) == 1
    body = json.loads(out.getvalue())
    assert body["command"] == "config init" and body["error"]["code"] == "config_invalid"
    assert "LLM_API_KEY is empty" in body["error"]["message"]


def test_init_asks_the_two_local_questions_with_a_recommended_answer(init_ctx, init_root, monkeypatch):
    """Plain words, recommended answers that Enter accepts; the SDK one follows the registry test."""
    asked = []
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "confirm", lambda question, default: asked.append((question, default)) or default)
    ctx, out, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama"})
    assert config_action.init(ctx, init_args()) == 0
    assert asked == [
        ("Build everything on this laptop (no INL login needed)? (recommended: yes)", True),
        ("Run DeepLynx (file storage) on this laptop? (recommended: yes)", True),
    ]
    values = envfile.read(init_root / ".env")
    assert (values["LOCAL_SDK"], values["LOCAL_DEEPLYNX"]) == ("true", "true")
    assert "Local SDK: yes" in out.getvalue() and "Local DeepLynx: yes" in out.getvalue()
    assert out.getvalue().rstrip().endswith("Next: make up, then ./platformctl deeplynx setup")


def test_init_does_not_recommend_building_locally_when_the_registry_works(init_ctx, runner, monkeypatch):
    """With a working INL login the recommended answer is no, and the question says so."""
    runner.reply("docker", "manifest", "inspect", code=0)
    asked = []
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "confirm", lambda question, default: asked.append((question, default)) or default)
    ctx, _, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama"})
    config_action.init(ctx, init_args())
    assert asked[0] == ("Build everything on this laptop (no INL login needed)? (recommended: no)", False)


def test_init_says_it_is_checking_the_registry_before_the_first_question(init_ctx, monkeypatch):
    """Off the VPN the check waits up to 15 s; the person is told, so it doesn't look like a hang."""
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "confirm", lambda question, default: default)
    ctx, out, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama"})
    config_action.init(ctx, init_args())
    assert "Checking whether you can pull from the INL registry (up to 15 s) ..." in out.getvalue()


def test_init_does_not_announce_the_check_with_yes(init_ctx):
    """`--yes` asks nothing, so it prints nothing about it either."""
    ctx, out, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama"}, yes=True)
    config_action.init(ctx, init_args())
    assert "Checking whether" not in out.getvalue()


def test_init_reports_needs_terminal_when_the_input_closes_under_a_question(init_ctx, monkeypatch):
    """Ctrl-D at a question is a clear error naming the closed input, not an `internal` traceback."""

    def closed(question, default):
        """`confirm` on a closed stdin."""
        raise terminal.TerminalError("the input was closed before the question was answered")

    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "confirm", closed)
    ctx, _, err = init_ctx({"LLM_CONFIG_PROFILE": "ollama"})
    assert config_action.init(ctx, init_args()) == 1
    assert "the input was closed before the question was answered" in err.getvalue()


def test_init_recommends_building_locally_when_the_pin_has_no_image_for_this_machine(init_ctx, runner, monkeypatch):
    """A login that works is not enough: an amd64-only pin on an arm64 Mac would fail or run emulated."""
    amd64_only = '{"manifests": [{"platform": {"architecture": "amd64", "os": "linux"}}]}'
    runner.reply("docker", "manifest", "inspect", code=0, stdout=amd64_only)  # the fake daemon reports aarch64
    asked = []
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "confirm", lambda question, default: asked.append((question, default)) or default)
    ctx, _, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama"})
    config_action.init(ctx, init_args())
    assert asked[0] == ("Build everything on this laptop (no INL login needed)? (recommended: yes)", True)


def test_init_skips_a_question_that_env_already_decides(init_ctx, init_root, monkeypatch):
    """`LOCAL_SDK` set, and `DEEPLYNX_KEY` set (so DeepLynx is elsewhere): nothing is asked or changed."""
    (init_root / ".env").write_text(
        EXAMPLE.replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=ollama") + "LOCAL_SDK=false\nDEEPLYNX_KEY=abc\n"
    )
    monkeypatch.setattr(terminal, "interactive", lambda: True)
    monkeypatch.setattr(terminal, "confirm", lambda *a: pytest.fail("asked"))
    ctx, out, _ = init_ctx()
    assert config_action.init(ctx, init_args()) == 0
    values = envfile.read(init_root / ".env")
    assert values["LOCAL_SDK"] == "false" and "LOCAL_DEEPLYNX" not in values
    assert "Local SDK" not in out.getvalue()


def test_init_flags_set_the_values_even_over_what_env_has(init_ctx, init_root, monkeypatch):
    """A flag is an explicit request: it wins, without asking."""
    (init_root / ".env").write_text(
        EXAMPLE.replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=ollama") + "LOCAL_SDK=true\nLOCAL_DEEPLYNX=true\n"
    )
    monkeypatch.setattr(terminal, "confirm", lambda *a: pytest.fail("asked"))
    ctx, out, _ = init_ctx()
    assert config_action.init(ctx, init_args(local_sdk=False, local_deeplynx=False)) == 0
    values = envfile.read(init_root / ".env")
    assert (values["LOCAL_SDK"], values["LOCAL_DEEPLYNX"]) == ("false", "false")
    assert "Local SDK: no\n" in out.getvalue() and "Local DeepLynx: no\n" in out.getvalue()


def test_init_yes_takes_the_recommended_answers_without_a_terminal(init_ctx, init_root, monkeypatch):
    """`--yes`: SDK follows the registry test (unreachable here, so yes), DeepLynx yes."""
    monkeypatch.setattr(terminal, "confirm", lambda *a: pytest.fail("asked"))
    ctx, _, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama"}, yes=True)
    assert config_action.init(ctx, init_args()) == 0
    values = envfile.read(init_root / ".env")
    assert (values["LOCAL_SDK"], values["LOCAL_DEEPLYNX"]) == ("true", "true")


def test_init_yes_does_not_build_locally_when_the_registry_works(init_ctx, init_root, runner):
    """`--yes` with a working login keeps the registry image."""
    runner.reply("docker", "manifest", "inspect", code=0)
    ctx, _, _ = init_ctx({"LLM_CONFIG_PROFILE": "ollama"}, yes=True)
    config_action.init(ctx, init_args())
    assert envfile.read(init_root / ".env")["LOCAL_SDK"] == "false"


def test_init_under_make_stops_when_a_changed_answer_needs_another_run(init_ctx, init_root):
    """Make read `.env` before this ran, so going on would build the old way: the answers are saved, and it stops."""
    via_make = {"PLATFORMCTL_VIA_MAKE": "1", "LLM_CONFIG_PROFILE": "ollama"}
    ctx, out, err = init_ctx(via_make, yes=True)
    assert config_action.init(ctx, init_args()) == 1
    assert "Saved your answers (LOCAL_SDK, LOCAL_DEEPLYNX) in .env. make read .env before" in err.getvalue()
    assert "Run the same make command again." in err.getvalue()
    values = envfile.read(init_root / ".env")
    assert (values["LOCAL_SDK"], values["LOCAL_DEEPLYNX"]) == ("true", "true")
    assert "Next:" not in out.getvalue()


def test_init_under_make_stop_is_one_json_object(init_ctx):
    """With `--json` the stop is the usual error object."""
    ctx, out, _ = init_ctx({"PLATFORMCTL_VIA_MAKE": "1", "LLM_CONFIG_PROFILE": "ollama"}, yes=True, json_mode=True)
    assert config_action.init(ctx, init_args()) == 1
    body = json.loads(out.getvalue())
    assert body["error"]["code"] == "config_invalid" and body["error"]["hint"] == "Run the same make command again."


def test_init_under_make_prints_no_next_line(init_ctx, init_root):
    """`make up` is already the next step, so "Next: make up" would only mislead."""
    (init_root / ".env").write_text(
        EXAMPLE.replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=ollama") + "LOCAL_SDK=true\nLOCAL_DEEPLYNX=true\n"
    )
    ctx, out, _ = init_ctx({"PLATFORMCTL_VIA_MAKE": "1"})
    assert config_action.init(ctx, init_args()) == 0
    assert "Next:" not in out.getvalue()


def test_init_under_make_is_quiet_when_nothing_changed(init_ctx, init_root):
    """An answer that matches what make already saw (or no answer at all) says nothing extra."""
    (init_root / ".env").write_text(
        EXAMPLE.replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=ollama") + "LOCAL_SDK=true\nLOCAL_DEEPLYNX=false\n"
    )
    ctx, _, err = init_ctx({"PLATFORMCTL_VIA_MAKE": "1", "LOCAL_SDK": "true"})
    assert config_action.init(ctx, init_args()) == 0
    assert "make read" not in err.getvalue()


def test_init_under_make_does_not_stop_for_a_setting_that_comes_from_the_environment(init_ctx, init_root):
    """CI exports `LOCAL_SDK=true` and `.env` never holds it: make already read it, so nothing changed.

    A first version compared the exported value with the missing `.env` key and stopped every `make up` in CI.
    """
    ctx, out, err = init_ctx(
        {
            "PLATFORMCTL_VIA_MAKE": "1",
            "LOCAL_SDK": "true",
            "LLM_CONFIG_PROFILE": "anthropic",
            "LLM_API_KEY": "value-from-the-environment-1",
        }
    )
    assert config_action.init(ctx, init_args()) == 0
    assert "make read" not in err.getvalue()
    assert "LOCAL_SDK" not in envfile.read(init_root / ".env"), "an exported value is left out of .env"


def test_init_without_make_never_warns_about_make(init_ctx):
    """Run by hand, a changed answer needs no second run."""
    ctx, _, err = init_ctx({"LLM_CONFIG_PROFILE": "ollama"}, yes=True)
    assert config_action.init(ctx, init_args()) == 0
    assert "make read" not in err.getvalue()


def test_init_tightens_a_world_readable_env_before_generating_secrets(init_ctx, init_root):
    """An `.env` made 0644 by hand keeps that mode through a rewrite: `config init` makes it 0600 first."""
    (init_root / ".env").write_text(EXAMPLE.replace("LLM_CONFIG_PROFILE=", "LLM_CONFIG_PROFILE=ollama"))
    (init_root / ".env").chmod(0o644)
    ctx, _, err = init_ctx({"LLM_CONFIG_PROFILE": "ollama"})
    assert config_action.init(ctx, init_args()) == 0
    assert stat.S_IMODE((init_root / ".env").stat().st_mode) == 0o600
    assert err.getvalue().count("readable by other users") == 1, "said once, not for every write"


def test_init_dry_run_writes_nothing(init_ctx, init_root):
    """`--dry-run` creates no file."""
    ctx, out, _ = init_ctx(dry_run=True)
    assert config_action.init(ctx, init_args()) == 0
    assert not (init_root / ".env").exists()
    assert out.getvalue() == "Would create or complete .env from .env.example.\n"


def test_init_reports_a_missing_profile_folder(init_ctx, init_root):
    """No SDK next to the platform is a `config_invalid` error."""
    profiles = init_root.parent / "sdk" / "prometheus_api" / "llm_configs"
    for child in profiles.iterdir():
        child.unlink()
    profiles.rmdir()
    ctx, _, err = init_ctx()
    assert config_action.init(ctx, init_args()) == 1
    assert "LLM config profiles not found" in err.getvalue()


def test_init_reports_a_failing_generator(init_ctx, runner):
    """A broken one-liner in `.env.example` names the key."""
    runner.reply(sys.executable, "-c", "print(1)", code=1)
    ctx, _, err = init_ctx()
    assert config_action.init(ctx, init_args()) == 1
    assert "generator for AGENT_SECRET" in err.getvalue()
