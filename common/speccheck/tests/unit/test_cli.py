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

"""The parser and `main`, with fake action modules standing in for the real ones."""

from __future__ import annotations

import io
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from speccheck import __version__, cli
from speccheck.config import ConfigError


def fake_module(name: str, section: str = "check", *, result=0, seen: list | None = None) -> SimpleNamespace:
    """An action module whose `run` records its arguments and returns `result` (or raises it)."""

    def add_arguments(parser):
        """One positional, like the real actions' inputs."""
        parser.add_argument("inputs", nargs="*")

    def run(ctx, args):
        """Note the call, then return or raise."""
        if seen is not None:
            seen.append((ctx, args))
        if isinstance(result, Exception):
            raise result
        return result

    return SimpleNamespace(
        NAME=name, HELP=f"{name} help", SECTION=section, ORDER=0, add_arguments=add_arguments, run=run
    )


@pytest.fixture
def modules(monkeypatch: pytest.MonkeyPatch) -> list:
    """`main` finds these instead of the real actions; tests may append to them."""
    found = [fake_module("one"), fake_module("two", "ci")]
    monkeypatch.setattr(cli.actions, "discover", lambda: found)
    return found


def main(*argv: str, **kwargs) -> tuple[int, str, str]:
    """Run `main` on string streams; the code, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), out=out, err=err, env=kwargs.pop("env", {}), cwd=kwargs.pop("cwd", Path("/x")))
    return code, out.getvalue(), err.getvalue()


def test_sections_epilog():
    """Each section's heading and its commands, then the pointer to a command's help."""
    text = cli.sections_epilog([fake_module("one"), fake_module("two", "ci"), fake_module("three")])
    assert text.splitlines() == [
        "Check specs and evidence:",
        "  one       one help",
        "  three     three help",
        "",
        "In CI:",
        "  two       two help",
        "",
        "Run `speccheck <command> --help` for a command's options.",
    ]


class TestParser:
    """Global options before or after the command, and usage errors raised, not printed."""

    def test_global_options_in_either_place(self):
        """After the command they don't reset what was given before it."""
        parser = cli.build_parser([fake_module("one")])
        before = parser.parse_args(["--config", "c.toml", "--json", "one", "a"])
        after = parser.parse_args(["one", "a", "--config", "c.toml", "--json"])
        for args in (before, after):
            assert (args.config, args.json, args.quiet, args.verbose, args.inputs) == (
                "c.toml",
                True,
                False,
                False,
                ["a"],
            )
        assert parser.parse_args(["one"]).config is None

    def test_a_usage_error_is_raised_with_the_usage(self):
        """So `main` can report it as JSON."""
        with pytest.raises(cli.UsageError, match=r"invalid choice: 'nope'(.|\n)*usage: speccheck"):
            cli.build_parser([fake_module("one")]).parse_args(["nope"])


class TestMain:
    """Running an action, and every way `main` exits."""

    def test_the_action_gets_a_context(self, modules):
        """The cwd, the environment, `--config`, and output flags from the arguments."""
        seen: list = []
        modules.append(fake_module("three", result=1, seen=seen))
        code, _, _ = main("three", "a", "--quiet", "--config", "c.toml", env={"X": "1"}, cwd=Path("/w"))
        assert code == 1
        ctx, args = seen[0]
        assert (ctx.cwd, ctx.env, ctx.config_path, args.inputs) == (Path("/w"), {"X": "1"}, "c.toml", ["a"])
        assert (ctx.output.quiet, ctx.output.verbose, ctx.output.json_mode) == (True, False, False)

    def test_help(self, modules):
        """0, both sections on stdout; a command's own help too."""
        code, out, _ = main("--help")
        assert code == 0 and "Check specs and evidence:\n  one       one help" in out and "In CI:\n  two" in out
        assert main("one", "--help")[1].startswith("usage: speccheck one")

    def test_version(self, modules):
        """Text and JSON."""
        assert main("--version")[:2] == (0, f"speccheck {__version__}\n")
        body = json.loads(main("--version", "--json")[1])
        assert (body["command"], body["version"]) == ("version", __version__)

    def test_no_command(self, modules):
        """The help, and 2."""
        code, out, _ = main()
        assert code == 2 and out.startswith("usage: speccheck")

    def test_usage_error(self, modules):
        """2, on stderr; with `--json`, one object on stdout."""
        code, out, err = main("nope")
        assert (code, out) == (2, "") and err.startswith("speccheck: error: argument <command>: invalid choice")
        code, out, err = main("nope", "--json")
        body = json.loads(out)
        assert (code, err, body["command"], body["ok"], body["error"]["code"]) == (2, "", "", False, "usage")

    def test_config_error(self, modules):
        """An action's ConfigError is 2; with `--json` the object names the command."""
        modules.append(fake_module("three", result=ConfigError("no config; pass --config PATH")))
        assert main("three") == (2, "", "speccheck: error: no config; pass --config PATH\n")
        code, out, _ = main("three", "--json")
        body = json.loads(out)
        assert (code, body["command"], body["error"]["message"]) == (2, "three", "no config; pass --config PATH")

    def test_defaults(self, modules, monkeypatch: pytest.MonkeyPatch):
        """With nothing given, main reads sys.argv, the real streams, os.environ and the cwd."""
        seen: list = []
        modules.append(fake_module("three", seen=seen))
        monkeypatch.setattr(sys, "argv", ["speccheck", "three"])
        monkeypatch.setenv("SPECCHECK_LEG", "x")
        assert cli.main() == 0
        ctx, _ = seen[0]
        assert ctx.cwd == Path.cwd() and ctx.env["SPECCHECK_LEG"] == "x"
        assert ctx.output.out is sys.stdout and ctx.output.err is sys.stderr


def test_python_m_speccheck(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """`python -m speccheck` runs main and exits with its code."""
    monkeypatch.setattr(sys, "argv", ["speccheck", "--version"])
    with pytest.raises(SystemExit) as done:
        runpy.run_module("speccheck", run_name="__main__")
    assert done.value.code == 0 and capsys.readouterr().out == f"speccheck {__version__}\n"
