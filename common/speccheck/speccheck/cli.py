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

"""The parser, built from the action modules, and the top-level error handler. Only this module exits."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import NoReturn, TextIO

from speccheck import __version__, actions, jsonout
from speccheck.config import ConfigError
from speccheck.context import Context
from speccheck.output import Output

PROG = "speccheck"
"""The program name."""


class UsageError(Exception):
    """argparse's exit 2, caught so `--json` can report it."""


class Parser(argparse.ArgumentParser):
    """An argument parser that raises `UsageError` instead of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        """Raise `UsageError` with the message and the usage line."""
        raise UsageError(f"{message}\n{self.format_usage().strip()}")


def add_global_options(parser: argparse.ArgumentParser, *, on_command: bool) -> None:
    """The global options. On a command, they default to SUPPRESS so they don't overwrite the copy before it."""
    default = argparse.SUPPRESS if on_command else None
    flag_default = argparse.SUPPRESS if on_command else False
    group = parser.add_argument_group("Global options")
    group.add_argument("--config", default=default, metavar="PATH", help="speccheck.toml or a pyproject.toml")
    group.add_argument("--json", action="store_true", default=flag_default, help="Print one JSON object on stdout")
    group.add_argument("--quiet", action="store_true", default=flag_default, help="Only print problems")
    group.add_argument(
        "--verbose", action="store_true", default=flag_default, help="Also print every requirement's status"
    )


def sections_epilog(modules: list[ModuleType]) -> str:
    """The command listing, by section."""
    lines: list[str] = []
    for section, heading in actions.SECTIONS:
        members = [m for m in modules if m.SECTION == section]
        lines.append(f"{heading}:")
        lines += [f"  {m.NAME:<10}{m.HELP}" for m in members]
        lines.append("")
    lines.append("Run `speccheck <command> --help` for a command's options.")
    return "\n".join(lines)


def build_parser(modules: list[ModuleType]) -> argparse.ArgumentParser:
    """The parser, with the global options before and after each command."""
    parser = Parser(
        prog=PROG,
        description="Check SDD specs against the test runs that prove them.",
        epilog=sections_epilog(modules),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_global_options(parser, on_command=False)
    parser.add_argument("--version", action="store_true", help="Print the version and exit")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", help=argparse.SUPPRESS, parser_class=Parser)
    for module in modules:
        sub = subparsers.add_parser(module.NAME, help=module.HELP, description=module.HELP)
        module.add_arguments(sub)
        add_global_options(sub, on_command=True)
        sub.set_defaults(_run=module.run)
    return parser


def _replacing(stream: TextIO) -> TextIO:
    """A real console stream, set to write a character its encoding lacks as `?` instead of raising.

    The output uses symbols such as ✅ and ⏸, which a non-UTF-8 console (a Windows code page, an odd
    locale) can't encode.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    return stream


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Parse the arguments, run the action and return its exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if out is None:
        out = _replacing(sys.stdout)
    if err is None:
        err = _replacing(sys.stderr)
    modules = actions.discover()
    parser = build_parser(modules)
    wants_json = "--json" in argv
    command = next((a for a in argv if a in {m.NAME for m in modules}), "")
    output = Output(out=out, err=err, json_mode=wants_json)

    def fail(message: str) -> int:
        """Report a usage or config error and return exit code 2."""
        if wants_json:
            jsonout.emit(jsonout.error(command, message), out)
        else:
            output.error(message)
        return jsonout.EXIT_USAGE

    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            args = parser.parse_args(argv)
    except SystemExit as done:  # --help
        out.write(captured.getvalue())
        return int(done.code or 0)
    except UsageError as exc:
        return fail(str(exc))

    if args.version:
        if args.json:
            jsonout.emit(jsonout.envelope("version", True, [], version=__version__), out)
        else:
            out.write(f"speccheck {__version__}\n")
        return jsonout.EXIT_OK
    if not args.command:
        if args.json:
            return fail("no command given")
        parser.print_help(out)
        return jsonout.EXIT_USAGE

    output.quiet, output.verbose = args.quiet, args.verbose
    ctx = Context(
        cwd=cwd or Path.cwd(),
        output=output,
        env=dict(os.environ if env is None else env),
        config_path=args.config,
    )
    try:
        return args._run(ctx, args)
    except ConfigError as exc:
        return fail(str(exc))
    except OSError as exc:
        # An unwritable output path or an unreadable file: report it as the one JSON object, not a traceback
        return fail(str(exc))
