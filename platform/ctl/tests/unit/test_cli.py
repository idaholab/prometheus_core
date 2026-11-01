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
import json
import types

import pytest

from platformctl import cli, jsonout
from platformctl.system import envfile
from platformctl.system.runner import RunnerError
from platformctl.targets.base import UnsupportedError
from tests.unit.conftest import assert_golden


def module(name, section="run", order=10, aliases=(), subcommands=None, run=None, help_text="help"):
    """A fake action module, optionally with aliases and subcommands."""
    ns = types.SimpleNamespace(
        NAME=name,
        HELP=f"{help_text} for {name}",
        SECTION=section,
        ORDER=order,
        ALIASES=list(aliases),
        add_arguments=lambda parser: (
            parser.add_argument("services", nargs="*"),
            parser.add_argument("--flag", action="store_true"),
        ),
        run=run or (lambda ctx, args: 0),
    )
    if subcommands:
        ns.SUBCOMMANDS = subcommands
    return ns


def leaf(name, aliases=()):
    """A fake subcommand."""
    return types.SimpleNamespace(
        NAME=name,
        HELP=f"leaf {name}",
        ALIASES=list(aliases),
        add_arguments=lambda p: p.add_argument("--x"),
        run=lambda ctx, args: 0,
    )


MODULES = [
    module("up", "run", 10),
    module("restart", "run", 20, aliases=["bounce"]),
    module("config", "setup", 10, subcommands=[leaf("init"), leaf("set", aliases=["put"])]),
    module("doctor", "troubleshoot", 10),
]
"""A small set of fake commands across the three sections."""


def parse(*argv):
    """Parse arguments with the fake commands and merge the global options."""
    parser = cli.build_parser(MODULES)
    return cli.merge_globals(parser.parse_args(cli.split_double_dash(argv)[0]))


# -- global options in both positions ----------------------------------------------------------


def test_global_options_before_and_after_the_command():
    """Global options before and after the command.

    Covers REQ-001-09.
    """
    args = parse("--verbose", "up", "--dry-run")
    assert args.verbose and args.dry_run and not args.quiet


def test_mixed_set_keeps_both():
    """`--set` before and after the command are both kept.

    Covers REQ-001-09, BEH-001-04.
    """
    args = parse("--set", "A=1", "up", "--set", "B=2")
    assert args.set == ["A=1", "B=2"]


def test_set_only_after_or_only_before():
    """Set only after or only before.

    Covers REQ-001-09.
    """
    assert parse("up", "--set", "B=2").set == ["B=2"]
    assert parse("--set", "A=1", "up").set == ["A=1"]


def test_target_from_either_position_after_wins():
    """Target from either position after wins."""
    assert parse("--target", "compose", "up").target == "compose"
    assert parse("up", "--target", "k3d").target == "k3d"
    assert parse("--target", "compose", "up", "--target", "k3d").target == "k3d"
    assert parse("up").target is None


def test_all_flags_or_together():
    """A flag given in either position is on.

    Covers REQ-001-09.
    """
    args = parse("--json", "--yes", "up", "--quiet", "--debug")
    assert (args.json, args.yes, args.quiet, args.debug) == (True, True, True, True)


def test_subcommands_get_the_global_options_too():
    """Subcommands get the global options too.

    Covers REQ-001-09.
    """
    args = parse("--set", "A=1", "config", "init", "--set", "B=2", "--json")
    assert args.set == ["A=1", "B=2"] and args.json and args.subcommand == "init"


def test_split_double_dash():
    """Arguments after the first `--` are split off for the action.

    Covers REQ-001-10.
    """
    assert cli.split_double_dash(["restart", "backend", "--", "--force-recreate", "--", "x"]) == (
        ["restart", "backend"],
        ["--force-recreate", "--", "x"],
    )
    assert cli.split_double_dash(["up"]) == (["up"], [])


def test_services_are_not_swallowed_by_the_double_dash():
    """Services are not swallowed by the double dash.

    Covers REQ-001-10.
    """
    own, extra = cli.split_double_dash(["restart", "backend", "--", "--force-recreate"])
    assert parse(*own).services == ["backend"] and extra == ["--force-recreate"]


# -- help layout -------------------------------------------------------------------------------


def test_sections_epilog_lists_commands_by_section_most_used_first():
    """Sections epilog lists commands by section most used first.

    Covers REQ-001-11.
    """
    epilog = cli.sections_epilog(MODULES)
    lines = epilog.splitlines()
    assert lines[0] == "Run the platform:"
    assert [line.split()[0] for line in lines[1:3]] == ["up", "restart"]
    assert "Set up:" in lines and "Troubleshoot:" in lines
    assert lines.index("Run the platform:") < lines.index("Set up:") < lines.index("Troubleshoot:")
    assert lines[-1] == "Run `./platformctl <command> --help` for a command's options."


def test_empty_sections_are_left_out():
    """Empty sections are left out.

    Covers REQ-001-11.
    """
    epilog = cli.sections_epilog([module("up")])
    assert "Set up:" not in epilog and "Run the platform:" in epilog


def test_top_level_help_is_pinned(monkeypatch):
    """Top level help is pinned.

    Covers REQ-001-11.
    """
    monkeypatch.setenv("COLUMNS", "100")
    help_text = cli.build_parser(MODULES).format_help()
    assert help_text.endswith(
        "Run the platform:\n"
        "  up          help for up\n"
        "  restart     help for restart\n"
        "\n"
        "Set up:\n"
        "  config      help for config\n"
        "\n"
        "Troubleshoot:\n"
        "  doctor      help for doctor\n"
        "\n"
        "Run `./platformctl <command> --help` for a command's options.\n"
    )
    # The subcommand list is hidden from argparse's own output: the sections replace it.
    assert "{up" not in help_text


@pytest.mark.parametrize(
    "argv", [["up"], ["restart"], ["bounce"], ["config"], ["config", "init"], ["config", "put"], ["doctor"]]
)
def test_every_command_subcommand_and_alias_parses_help(argv, capsys):
    """Every command subcommand and alias parses help."""
    with pytest.raises(cli.UsageError if argv == ["config"] else SystemExit) as info:
        cli.build_parser(MODULES).parse_args([*argv, "--help"] if argv != ["config"] else argv)
    if isinstance(info.value, SystemExit):
        assert info.value.code == 0
        assert capsys.readouterr().out.startswith("usage:")


def test_aliases_map_to_the_real_name():
    """Aliases map to the real name.

    Covers REQ-001-13.
    """
    assert cli.aliases_of(MODULES) == {"bounce": "restart"}


def test_parser_errors_raise_usage_error_instead_of_exiting():
    """Parser errors raise usage error instead of exiting."""
    with pytest.raises(cli.UsageError, match="unrecognized arguments"):
        cli.build_parser(MODULES).parse_args(["up", "--nope"])


# -- main --------------------------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A clean environment, with the tool's platform folder pointed at a temporary folder."""
    monkeypatch.setattr(cli.Paths, "default", classmethod(lambda cls, agent=None: cli.Paths(tmp_path)))
    return {"PATH": "/usr/bin"}


def call(*argv, env=None, modules=None):
    """Run `cli.main` and return the exit code, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), env=env if env is not None else {"PATH": "/usr/bin"}, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_version_text_and_json(env):
    """`--version` prints text, or one JSON object with the commands and features.

    Covers REQ-001-17.
    """
    code, out, _ = call("--version", env=env)
    assert code == 0 and out.startswith("platformctl 0.1.0 (platform ")
    code, out, _ = call("--version", "--json", env=env)
    body = json.loads(out)
    assert code == 0 and body["ok"] and body["schema_version"] == 1 and body["command"] == "version"
    assert body["commands"] == ["doctor"] and body["features"] == ["doctor.checks.v1"]
    assert set(body["platform"]) == {"root", "project", "version"}


def test_golden_version_json(env, tmp_path):
    """`--version --json`, with the commands and features a script branches on.

    Covers REQ-001-17.
    """
    _, out, _ = call("--version", "--json", env=env)
    assert_golden("version", json.loads(out), tmp_path)


def test_golden_usage_error_json(env, tmp_path):
    """A usage error is one object with `error.code` `usage`.

    Covers REQ-001-19, BEH-001-05.
    """
    _, out, _ = call("--json", "doctor", "--nope", env=env)
    assert_golden("usage_error", json.loads(out), tmp_path)


def test_no_command_prints_help(env):
    """With no command, the help is printed and the exit code is 0.

    Covers REQ-001-12.
    """
    code, out, _ = call(env=env)
    assert code == 0 and "Troubleshoot:" in out


def test_usage_error_text_and_json(env):
    """Usage error text and json.

    Covers REQ-001-18, BEH-001-05.
    """
    code, out, err = call("nope", env=env)
    assert code == 2 and out == "" and "invalid choice" in err
    code, out, err = call("--json", "doctor", "--nope", env=env)
    body = json.loads(out)
    assert code == 2 and body["ok"] is False and body["error"]["code"] == "usage" and err == ""


def test_json_stdout_is_only_the_object_even_for_errors(env):
    """Json stdout is only the object even for errors.

    Covers REQ-001-18.
    """
    code, out, err = call("--json", "doctor", "--set", "LLM_API_KEY=x", env=env)
    assert code == 1
    assert json.loads(out)["error"]["code"] == "config_invalid"
    assert "LLM_API_KEY" in json.loads(out)["error"]["message"]


def test_an_env_file_that_is_not_text_is_still_one_json_object(env, tmp_path):
    """A `.env` that isn't UTF-8 gives JSON and no traceback: `--version` ignores it, `doctor` reports it.

    Covers REQ-001-16.
    """
    (tmp_path / ".env").write_bytes(b"A=\xff\xfe\n")
    code, out, err = call("--version", "--json", env=env)
    assert code == 0 and json.loads(out)["ok"] is True and err == ""
    code, out, err = call("doctor", "platform-env", "--json", env=env)
    body = json.loads(out)
    assert code == 1 and body["checks"][0]["status"] == "FAIL"
    assert "Traceback" not in out + err and "position" not in out


def test_set_refusing_a_secret_in_text_mode(env):
    """Set refusing a secret in text mode.

    Covers REQ-003-10.
    """
    code, out, err = call("doctor", "--set", "AGENT_SECRET=hunter2hunter2", env=env)
    assert code == 1 and "set AGENT_SECRET in .env instead" in err and "hunter2" not in err + out


def test_k3d_target_is_refused(env):
    """`--target k3d` exits 1 with "not supported yet".

    Covers REQ-008-02.
    """
    code, _, err = call("doctor", "--target", "k3d", env=env)
    assert code == 1 and "k3d` is not supported yet" in err


def test_a_malformed_env_stops_every_command_but_doctor(env, tmp_path):
    """A malformed env stops every command but doctor.

    Covers REQ-001-16.
    """
    (tmp_path / ".env").write_text("AGENT_SECRET=ok\nsk-live-supersecretvalue\n")
    code, _, err = call("doctor", "--list", env=env)
    assert code == 0
    code, out, err = call("doctor", "platform-env", env=env)
    assert "line 2" in out and "supersecret" not in out
    stopped = {"code": 0}

    def fake(ctx, args):
        """Record that the action ran."""
        stopped["code"] = 99
        return 0

    cli_modules = [module("up", run=fake)]
    import platformctl.actions as actions_mod

    orig = actions_mod.discover
    actions_mod.discover = lambda: cli_modules
    try:
        code, _, err = call("up", env=env)
    finally:
        actions_mod.discover = orig
    assert code == 1 and stopped["code"] == 0
    assert "line 2" in err and "supersecret" not in err


def test_dispatch_runs_the_action_with_the_merged_args_and_extra(env, monkeypatch):
    """Dispatch runs the action with the merged args and extra."""
    seen = {}

    def run(ctx, args):
        """Record what the action was given."""
        seen.update(services=args.services, extra=args.extra, dry=ctx.dry_run, yes=ctx.yes, set=args.set)
        return 7

    monkeypatch.setattr(cli.actions, "discover", lambda: [module("up", run=run, aliases=["start"])])
    code, _, err = call(
        "--yes", "up", "backend", "--dry-run", "--set", "WAIT_TIMEOUT=5", "--", "--force-recreate", env=env
    )
    assert code == 7
    assert seen == {
        "services": ["backend"],
        "extra": ["--force-recreate"],
        "dry": True,
        "yes": True,
        "set": ["WAIT_TIMEOUT=5"],
    }
    assert err == ""


def test_a_deprecated_alias_still_works_and_says_so(env, monkeypatch):
    """A deprecated alias still works and says so.

    Covers REQ-001-13.
    """
    monkeypatch.setattr(cli.actions, "discover", lambda: [module("restart", aliases=["bounce"])])
    code, _, err = call("bounce", env=env)
    assert code == 0 and "`bounce` is deprecated; use `restart`." in err


def test_group_dispatch(env, monkeypatch):
    """A subcommand of a group is dispatched."""
    ran = []
    group = module(
        "config",
        "setup",
        subcommands=[
            types.SimpleNamespace(
                NAME="init",
                HELP="h",
                ALIASES=[],
                add_arguments=lambda p: None,
                run=lambda c, a: ran.append("init") or 0,
            )
        ],
    )
    monkeypatch.setattr(cli.actions, "discover", lambda: [group])
    assert call("config", "init", env=env)[0] == 0 and ran == ["init"]


def test_secrets_in_the_environment_are_scrubbed_from_every_message(env, monkeypatch):
    """Secrets in the environment are scrubbed from every message.

    Covers REQ-003-04.
    """

    def run(ctx, args):
        """Print an error that contains a secret."""
        ctx.output.error("failed with fake-secret-fake-secret")
        return 1

    monkeypatch.setattr(cli.actions, "discover", lambda: [module("up", run=run)])
    code, out, err = call("up", env={**env, "LLM_API_KEY": "fake-secret-fake-secret"})
    assert code == 1 and "fake-secret" not in out + err and "failed with ***" in err


@pytest.mark.parametrize(
    ("exc", "code_name"),
    [
        (UnsupportedError("not on this target"), "config_invalid"),
        (envfile.EnvFileError("line 3: expected KEY=value"), "config_invalid"),
        (RunnerError("can't run docker: not found"), "docker_unavailable"),
        (RuntimeError("boom hunter2hunter2"), "internal"),
    ],
)
def test_errors_become_json_with_a_fixed_code_and_text_with_a_hint(env, monkeypatch, exc, code_name):
    """Errors become json with a fixed code and text with a hint.

    Covers REQ-001-20.
    """

    def run(ctx, args):
        """Raise the error under test."""
        raise exc

    monkeypatch.setattr(cli.actions, "discover", lambda: [module("up", run=run)])
    code, out, _ = call("--json", "up", env={**env, "SECRET_TOKEN": "hunter2hunter2"})
    body = json.loads(out)
    assert code == 1 and body["error"]["code"] == code_name and body["ok"] is False
    assert "hunter2" not in out
    code, out, err = call("up", env=env)
    assert code == 1 and out == "" and err.startswith("error: ")


def test_unexpected_errors_show_a_traceback_only_with_debug(env, monkeypatch):
    """Unexpected errors show a traceback only with debug.

    Covers REQ-001-15.
    """

    def run(ctx, args):
        """Raise an unexpected error."""
        raise RuntimeError("boom")

    monkeypatch.setattr(cli.actions, "discover", lambda: [module("up", run=run)])
    _, _, quiet = call("up", env=env)
    _, _, debug = call("up", "--debug", env=env)
    assert "Traceback" not in quiet and "Run again with --debug" in quiet
    assert "Traceback" in debug and "RuntimeError: boom" in debug


def test_a_traceback_is_scrubbed(env, monkeypatch):
    """A secret in a traceback printed with `--debug` is scrubbed.

    Covers REQ-003-04.
    """

    def run(ctx, args):
        """Raise an error whose message and source line hold a secret."""
        secret = "fake-secret-fake-secret"  # noqa: F841 - appears in the traceback's source line
        raise RuntimeError("fake-secret-fake-secret")

    monkeypatch.setattr(cli.actions, "discover", lambda: [module("up", run=run)])
    _, _, err = call("up", "--debug", env={**env, "LLM_API_KEY": "fake-secret-fake-secret"})
    assert "fake-secret" not in err


def test_ctrl_c_exits_130(env, monkeypatch):
    """Ctrl-C exits with 130.

    Covers REQ-001-14.
    """

    def run(ctx, args):
        """Act like Ctrl-C."""
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.actions, "discover", lambda: [module("up", run=run)])
    assert call("up", env=env)[0] == jsonout.EXIT_INTERRUPTED == 130


def test_main_defaults_to_the_process_argv_env_and_streams(monkeypatch, capsys, env):
    """Main defaults to the process argv env and streams."""
    monkeypatch.setattr(cli.sys, "argv", ["platformctl", "--version"])
    assert cli.main() == 0
    assert capsys.readouterr().out.startswith("platformctl ")


def test_command_label_for_errors_skips_option_values():
    """Command label for errors skips option values."""
    assert cli._command(["--json", "--set", "A=1", "doctor"], MODULES) == "doctor"
    assert cli._command(["bounce"], MODULES) == "bounce"
    assert cli._command(["--json"], MODULES) == ""


def test_the_error_json_names_the_command(env):
    """The error json names the command.

    Covers REQ-001-19.
    """
    _, out, _ = call("--json", "--set", "AGENT_SECRET=x", "doctor", env=env)
    assert json.loads(out)["command"] == "doctor"
