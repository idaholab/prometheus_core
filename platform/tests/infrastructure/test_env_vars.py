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

"""Validate .env.example completeness and cross-references with docker-compose.yml."""

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest


def _load_init_env():
    path = Path(__file__).resolve().parents[2] / "scripts" / "init_env.py"
    spec = importlib.util.spec_from_file_location("init_env", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REQUIRED_VARS = [
    "LLM_API_KEY",
    "AGENT_SECRET",
    "REDIS_PASSWORD",
    "BACKEND_JWT_SECRET",
    "ADMIN_DB_PASSWORD",
    "ADMIN_DB_ENCRYPTION_KEY",
]

LLM_CONFIG_VARS = [
    "LLM_CONFIG_PROFILE",
    "LLM_CONFIG_FILE",
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
]


def test_env_example_exists(env_example_path):
    assert env_example_path.exists(), ".env.example file does not exist"


@pytest.mark.parametrize("var", REQUIRED_VARS)
def test_required_var_present(env_example_vars, var):
    assert var in env_example_vars, f"Required variable '{var}' missing from .env.example"


@pytest.mark.parametrize("var", LLM_CONFIG_VARS)
def test_llm_config_var_present(env_example_vars, var):
    assert var in env_example_vars, f"LLM configuration variable '{var}' missing from .env.example"


def test_all_compose_var_refs_have_entry_or_default(compose_var_refs, env_example_vars):
    """Every ${VAR} in docker-compose.yml without a :-default must exist in .env.example.

    Well-known optional vars (proxy settings) are excluded since they are
    intentionally commented out in .env.example and only needed behind a corporate proxy.
    """
    optional_vars = {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
    missing = []
    for var_name, has_default in compose_var_refs:
        if not has_default and var_name not in env_example_vars and var_name not in optional_vars:
            missing.append(var_name)
    assert not missing, f"Compose references without defaults or .env.example entry: {missing}"


def test_required_secrets_have_generator(env_example_path):
    """Required secrets ship blank; scripts/init_env.py fills each from the
    python3 one-liner in its comment block, so every one must have one."""
    init_env = _load_init_env()
    gens = init_env.generators(env_example_path.read_text())
    missing = [v for v in REQUIRED_VARS if v != "LLM_API_KEY" and v not in gens]
    assert not missing, f"Required secrets without a generator one-liner: {missing}"


def test_init_env_fills_secrets_and_checks_llm_key(tmp_path, env_example_path, monkeypatch):
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_CONFIG_PROFILE", raising=False)
    llm_vars = ("LLM_API_KEY", "LLM_CONFIG_PROFILE")

    assert init_env.main() == 1  # LLM_CONFIG_PROFILE and LLM_API_KEY still blank
    first = init_env.values(env.read_text())
    assert all(first[v] for v in REQUIRED_VARS if v != "LLM_API_KEY")

    env.write_text(env.read_text().replace("LLM_CONFIG_PROFILE=\n", "LLM_CONFIG_PROFILE=anthropic\n"))
    assert init_env.main() == 1  # LLM_API_KEY still blank

    env.write_text(env.read_text().replace("LLM_API_KEY=\n", "LLM_API_KEY=sk-ant-x\n"))
    assert init_env.main() == 0
    second = init_env.values(env.read_text())
    assert {k: v for k, v in second.items() if k not in llm_vars} == {
        k: v for k, v in first.items() if k not in llm_vars
    }, "existing values must never be overwritten"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX file modes")
def test_init_env_creates_an_owner_only_env_and_keeps_an_existing_mode(tmp_path, env_example_path, monkeypatch):
    """A new .env is 0600 from the start, through every later rewrite; an existing one keeps its mode."""
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.setenv("LLM_CONFIG_PROFILE", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-x")
    old_umask = os.umask(0o022)  # the usual one, under which a plain copy would be 0644
    try:
        assert init_env.main() == 0
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600, "secrets were written to a world-readable file"
    assert init_env.values(env.read_text())["LLM_API_KEY"] == "sk-ant-x"

    # An existing .env that gets a missing value filled in keeps whatever mode its owner chose
    env.chmod(0o640)
    env.write_text(
        env.read_text().replace("AGENT_SECRET=" + init_env.values(env.read_text())["AGENT_SECRET"], "AGENT_SECRET=")
    )
    assert init_env.main() == 0
    assert init_env.values(env.read_text())["AGENT_SECRET"], "the blank secret was regenerated"
    assert stat.S_IMODE(env.stat().st_mode) == 0o640, "an existing .env's mode must be left alone"


def test_init_env_requires_a_profile(tmp_path, env_example_path, monkeypatch, capsys):
    """There is no default profile: a blank one fails, even with a key set."""
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.delenv("LLM_CONFIG_PROFILE", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")

    assert init_env.main() == 1
    assert "LLM_CONFIG_PROFILE is empty" in capsys.readouterr().err

    env.write_text(env.read_text().replace("LLM_CONFIG_FILE=\n", "LLM_CONFIG_FILE=/custom.yaml\n"))
    assert init_env.main() == 0  # a custom YAML replaces the profile


def test_init_env_takes_llm_key_from_environment(tmp_path, env_example_path, monkeypatch):
    """CI sets LLM_CONFIG_PROFILE and LLM_API_KEY in the environment instead of answering the prompt."""
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.setenv("LLM_CONFIG_PROFILE", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")

    assert init_env.main() == 0
    written = init_env.values(env.read_text())
    assert written["LLM_CONFIG_PROFILE"] == "anthropic"
    assert written["LLM_API_KEY"] == "sk-from-env"

    # A profile and key already in .env win over the environment
    monkeypatch.setenv("LLM_CONFIG_PROFILE", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-other")
    assert init_env.main() == 0
    rerun = init_env.values(env.read_text())
    assert rerun["LLM_CONFIG_PROFILE"] == "anthropic"
    assert rerun["LLM_API_KEY"] == "sk-from-env"


def test_init_env_prompts_for_profile_and_key(tmp_path, env_example_path, monkeypatch, capsys):
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: True)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(init_env, "choose", lambda options, labels, default: "openai")
    monkeypatch.setattr(init_env.getpass, "getpass", lambda prompt: "sk-openai-x")
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert init_env.main() == 0
    written = init_env.values(env.read_text())
    assert written["LLM_CONFIG_PROFILE"] == "openai"
    assert written["LLM_API_KEY"] == "sk-openai-x"
    out = capsys.readouterr().out
    # Names the key it saved, never the key itself
    assert "Saved LLM_CONFIG_PROFILE=openai, LLM_API_KEY in .env." in out
    assert "sk-openai-x" not in out


def test_init_env_names_no_key_for_a_keyless_profile(tmp_path, env_example_path, monkeypatch, capsys):
    """ollama needs no key, so none is asked for and the saved line names only the profile."""
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: True)
    monkeypatch.delenv("LLM_CONFIG_PROFILE", raising=False)
    monkeypatch.setattr(init_env, "choose", lambda options, labels, default: "ollama")
    monkeypatch.setattr(init_env.getpass, "getpass", lambda prompt: pytest.fail("asked for a key"))
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    assert init_env.main() == 0
    assert "Saved LLM_CONFIG_PROFILE=ollama in .env." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("", True), ("y", True), ("Y", True), ("yes", True), ("YES", True), (" Yes ", True)]
    + [("n", False), ("N", False), ("no", False), ("NO", False), (" No ", False)],
)
def test_yes_accepts_enter_y_yes_n_no_in_any_case(monkeypatch, typed, expected):
    init_env = _load_init_env()
    monkeypatch.setattr("builtins.input", lambda prompt: typed)
    assert init_env.yes("Run it?") is expected


@pytest.mark.parametrize("typo", ["false", "0", "nope", "yep", "t", "ok"])
def test_yes_asks_again_instead_of_taking_a_typo_for_yes(monkeypatch, capsys, typo):
    """`false` used to count as yes, which meant a local build or DeepLynx the user had declined."""
    init_env = _load_init_env()
    typed = iter([typo, "n"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(typed))

    assert init_env.yes("Run it?") is False
    assert "Please answer y or n" in capsys.readouterr().out


def test_choose_runs_on_python_39(monkeypatch):
    """/usr/bin/python3 on macOS is 3.9, where zip() takes no keyword arguments (strict= is 3.10+)."""
    init_env = _load_init_env()

    def zip39(*iterables, **kwargs):
        if kwargs:
            raise TypeError("zip() takes no keyword arguments")
        return zip(*iterables)

    monkeypatch.setattr(init_env, "zip", zip39, raising=False)
    monkeypatch.setitem(sys.modules, "termios", None)  # the numbered prompt, as without a terminal
    monkeypatch.setattr("builtins.input", lambda prompt: "2")

    assert init_env.choose(["a", "b"], ["first", "second"], 0) == "b"


def test_choose_rejects_a_label_count_that_differs(monkeypatch):
    """What zip(strict=True) guarded: one label per option."""
    init_env = _load_init_env()
    monkeypatch.setitem(sys.modules, "termios", None)
    with pytest.raises(ValueError, match="one label per option"):
        init_env.choose(["a", "b"], ["first"], 0)


def _new_env(tmp_path, env_example_path, monkeypatch, answers):
    """init_env with a fresh .env, a terminal and a set LLM profile; ``answers`` feed input()."""
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: True)
    for var, _ in init_env.LOCAL_OPTIONS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_CONFIG_PROFILE", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-x")
    asked = []
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or next(replies))
    return init_env, env, asked


@pytest.mark.parametrize(("answers", "expected"), [(["", ""], "true"), (["n", "no"], "false"), (["Y", "yes"], "true")])
def test_init_env_asks_local_options_when_it_creates_env(tmp_path, env_example_path, monkeypatch, answers, expected):
    """A new .env asks for LOCAL_SDK and LOCAL_DEEPLYNX (Enter = yes) and sets the commented default lines."""
    init_env, env, asked = _new_env(tmp_path, env_example_path, monkeypatch, answers)

    assert init_env.main() == 0
    assert len(asked) == 2
    text = env.read_text()
    written = init_env.values(text)
    for var, _ in init_env.LOCAL_OPTIONS:
        assert written[var] == expected
        # In place of the commented default, not appended a second time
        lines = text.splitlines()
        assert f"#{var}=false" not in lines
        assert sum(line.startswith(f"{var}=") for line in lines) == 1


def test_init_env_asks_an_existing_env_that_has_no_local_lines(tmp_path, env_example_path, monkeypatch):
    """An .env from before the questions (or made without a terminal) is asked, once, in a terminal."""
    init_env, env, asked = _new_env(tmp_path, env_example_path, monkeypatch, ["n", ""])
    env.write_text(env_example_path.read_text())

    assert init_env.main() == 0
    assert len(asked) == 2
    written = init_env.values(env.read_text())
    assert written["LOCAL_SDK"] == "false" and written["LOCAL_DEEPLYNX"] == "true"


def test_init_env_asks_a_question_only_until_it_has_an_answer(tmp_path, env_example_path, monkeypatch):
    """A No is saved as a false line, so the next run in a terminal asks nothing."""
    init_env, env, asked = _new_env(tmp_path, env_example_path, monkeypatch, ["n", "n"])
    assert init_env.main() == 0
    assert len(asked) == 2

    before = env.read_text()
    assert init_env.main() == 0
    assert len(asked) == 2, "asked again after both were answered"
    assert env.read_text() == before


@pytest.mark.parametrize("line", ["LOCAL_SDK=true", "LOCAL_SDK=false", "LOCAL_SDK="])
def test_init_env_never_changes_or_asks_about_a_line_that_is_there(tmp_path, env_example_path, monkeypatch, line):
    """A hand-set line (even blank) is respected: only the missing question is asked."""
    init_env, env, asked = _new_env(tmp_path, env_example_path, monkeypatch, [""])
    env.write_text(env_example_path.read_text() + f"\n{line}\n")

    assert init_env.main() == 0
    assert len(asked) == 1 and "DeepLynx" in asked[0]
    lines = env.read_text().splitlines()
    assert lines.count(line) == 1
    assert sum(entry.startswith("LOCAL_SDK=") for entry in lines) == 1


def test_init_env_asks_a_complete_env_nothing(tmp_path, env_example_path, monkeypatch):
    """Both lines present: nothing is asked and .env is not rewritten."""
    init_env, env, asked = _new_env(tmp_path, env_example_path, monkeypatch, [])
    env.write_text(env_example_path.read_text() + "\nLOCAL_SDK=true\nLOCAL_DEEPLYNX=false\n")
    assert init_env.main() == 0  # fills the blank secrets and the profile, which rewrites it once
    complete = (env.read_text(), env.stat().st_mtime_ns)

    assert init_env.main() == 0
    assert asked == []
    assert (env.read_text(), env.stat().st_mtime_ns) == complete


def test_init_env_skips_local_options_set_in_the_environment(tmp_path, env_example_path, monkeypatch):
    """`make up LOCAL_SDK=false` passes the value on: that question is skipped, the other still asked."""
    init_env, env, asked = _new_env(tmp_path, env_example_path, monkeypatch, [""])
    monkeypatch.setenv("LOCAL_SDK", "false")

    assert init_env.main() == 0
    assert len(asked) == 1 and "DeepLynx" in asked[0]
    written = init_env.values(env.read_text())
    assert "LOCAL_SDK" not in written
    assert written["LOCAL_DEEPLYNX"] == "true"


def test_init_env_asks_no_local_options_without_a_terminal(tmp_path, env_example_path, monkeypatch, capsys):
    """CI and assistant runs: nothing asked, nothing written, so both keep the Makefile default (false).

    It says so, when it created .env, and a later run in a terminal asks.
    """
    init_env, env, asked = _new_env(tmp_path, env_example_path, monkeypatch, [])
    monkeypatch.setattr(init_env, "interactive", lambda: False)

    assert init_env.main() == 0
    assert asked == []
    written = init_env.values(env.read_text())
    assert "LOCAL_SDK" not in written and "LOCAL_DEEPLYNX" not in written
    out = capsys.readouterr().out
    assert "Not asked (no terminal): LOCAL_SDK, LOCAL_DEEPLYNX stay false" in out
    assert "LOCAL_SDK=true and LOCAL_DEEPLYNX=true" in out


def test_init_env_only_names_the_local_options_it_did_not_ask_about(tmp_path, env_example_path, monkeypatch, capsys):
    """A variable set in the environment is not named; with both set there is nothing to say."""
    init_env, env, _ = _new_env(tmp_path, env_example_path, monkeypatch, [])
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.setenv("LOCAL_SDK", "false")

    assert init_env.main() == 0
    out = capsys.readouterr().out
    assert "Not asked (no terminal): LOCAL_DEEPLYNX stay false" in out
    assert "LOCAL_SDK=true" not in out

    env.unlink()
    monkeypatch.setenv("LOCAL_DEEPLYNX", "false")
    assert init_env.main() == 0
    assert "Not asked" not in capsys.readouterr().out


def test_init_env_does_not_repeat_the_no_terminal_hint_for_an_existing_env(
    tmp_path, env_example_path, monkeypatch, capsys
):
    """Said once, when .env is created; CI and assistants reruns on that .env stay quiet."""
    init_env, env, _ = _new_env(tmp_path, env_example_path, monkeypatch, [])
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    env.write_text(env_example_path.read_text())

    assert init_env.main() == 0
    assert "Not asked" not in capsys.readouterr().out


def test_init_env_leaves_a_complete_env_unwritten(tmp_path, env_example_path, monkeypatch):
    """A second run changes nothing, so make (which rereads the Makefile after a changed .env) reads it once."""
    init_env, env, _ = _new_env(tmp_path, env_example_path, monkeypatch, ["", ""])
    assert init_env.main() == 0
    before = (env.read_text(), env.stat().st_mtime_ns)

    assert init_env.main() == 0
    assert (env.read_text(), env.stat().st_mtime_ns) == before


def test_init_env_rejects_unknown_profile(tmp_path, env_example_path, monkeypatch, capsys):
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    env.write_text(
        example.read_text()
        .replace("LLM_CONFIG_PROFILE=\n", "LLM_CONFIG_PROFILE=genisis\n")
        .replace("LLM_API_KEY=\n", "LLM_API_KEY=sk-x\n")
    )
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)

    assert init_env.main() == 1
    err = capsys.readouterr().err
    assert "LLM_CONFIG_PROFILE=genisis" in err
    assert "anthropic" in err

    env.write_text(env.read_text().replace("LLM_CONFIG_PROFILE=genisis\n", "LLM_CONFIG_PROFILE=registry\n"))
    assert init_env.main() == 1
    assert "LLM_CONFIG_PROFILE=registry" in capsys.readouterr().err  # installed by the SDK, but no proxy here

    env.write_text(env.read_text().replace("LLM_CONFIG_FILE=\n", "LLM_CONFIG_FILE=/custom.yaml\n"))
    assert init_env.main() == 0  # a custom YAML replaces the profile


def test_profiles_match_sdk_llm_configs():
    """Every installed profile but "registry" is offered; all but the keyless ollama read LLM_API_KEY."""
    init_env = _load_init_env()
    known = init_env.profiles()
    installed = {p.stem for p in init_env.LLM_CONFIGS.glob("*.yaml")}
    assert list(known) == sorted(installed - {"registry"})
    # EMBEDDING_API_KEY is never the profile key. Only the keyless local ollama
    # profile (api_key: none) needs no key at all.
    keys = {name: key for name, (key, _) in known.items()}
    assert [name for name, key in keys.items() if key is None] == ["ollama"]
    for name, key in keys.items():
        if name != "ollama":
            assert key == "LLM_API_KEY", f"{name} must read LLM_API_KEY"


def test_port_vars_have_values(env_example_vars):
    """Port variables should have values defined in .env.example."""
    port_vars = [
        "REDIS_LOCAL_PORT",
        "CLIENT_AGENT_PORT",
        "BACKEND_PORT",
    ]
    missing = [v for v in port_vars if v not in env_example_vars]
    assert not missing, f"Port variables missing from .env.example: {missing}"
