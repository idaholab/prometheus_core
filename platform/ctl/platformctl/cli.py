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

"""The parser, built from the action registry, and the top-level error handler.

See plans/platformctl/design.md, "Help layout" and "Extending and changing commands".
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import traceback
from collections.abc import Sequence
from types import ModuleType
from typing import NoReturn

from platformctl import __version__, actions, jsonout
from platformctl.config import ConfigError, PlatformConfig, parse_set, platform_version
from platformctl.context import build
from platformctl.output import Output, Scrubber
from platformctl.paths import Paths
from platformctl.system import envfile
from platformctl.system.runner import Runner, RunnerError
from platformctl.targets.base import UnsupportedError

PROG = "platformctl"
SUB_PREFIX = "sub_"


class UsageError(Exception):
    """argparse's exit 2, caught so `--json` can report it."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{self.prog}: {message}\n\n{self.format_usage().strip()}")


def add_global_options(parser: argparse.ArgumentParser, prefix: str = "") -> None:
    """The global options, in their own group, listed last. `prefix` gives the copy on a subcommand its own dest."""
    group = parser.add_argument_group("Global options")
    group.add_argument(
        "--set",
        dest=f"{prefix}set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override one setting for this run (not secrets: set those in .env)",
    )
    group.add_argument(
        "--target",
        dest=f"{prefix}target",
        default=None,
        metavar="compose|k3d",
        help="Where the platform runs (only compose works for now)",
    )
    group.add_argument(
        "--dry-run", dest=f"{prefix}dry_run", action="store_true", help="Print the commands instead of running them"
    )
    group.add_argument(
        "--verbose",
        dest=f"{prefix}verbose",
        action="store_true",
        help="Print settings and the commands run (secrets scrubbed)",
    )
    group.add_argument("--quiet", dest=f"{prefix}quiet", action="store_true", help="Only print errors")
    group.add_argument(
        "--json", dest=f"{prefix}json", action="store_true", help="Machine-readable output where supported"
    )
    group.add_argument("--yes", dest=f"{prefix}yes", action="store_true", help="Answer yes to confirmations")
    group.add_argument(
        "--debug", dest=f"{prefix}debug", action="store_true", help="Show tracebacks (scrubbed) on an unexpected error"
    )


def merge_globals(args: argparse.Namespace) -> argparse.Namespace:
    """Combine the copy before the command with the copy after it: lists concatenate, flags OR."""

    def sub(name: str):
        return getattr(args, SUB_PREFIX + name, None)

    args.set = [*args.set, *(sub("set") or [])]
    args.target = sub("target") or args.target
    for flag in ("dry_run", "verbose", "quiet", "json", "yes", "debug"):
        setattr(args, flag, bool(getattr(args, flag) or sub(flag)))
    return args


def split_double_dash(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Everything after the first `--` belongs to the action (for example `compose --`)."""
    argv = list(argv)
    if "--" in argv:
        at = argv.index("--")
        return argv[:at], argv[at + 1 :]
    return argv, []


def _group_leaves(module: ModuleType) -> list[ModuleType]:
    return list(getattr(module, "SUBCOMMANDS", []))


def sections_epilog(modules: list[ModuleType]) -> str:
    """The command listing, by section, most used first."""
    lines: list[str] = []
    for section, heading in actions.SECTIONS:
        members = [m for m in modules if m.SECTION == section]
        if not members:
            continue
        lines.append(f"{heading}:")
        lines += [f"  {m.NAME:<12}{m.HELP}" for m in members]
        lines.append("")
    lines.append("Run `./platformctl <command> --help` for a command's options.")
    return "\n".join(lines)


def aliases_of(modules: list[ModuleType]) -> dict[str, str]:
    """Deprecated alias -> the command's real name."""
    return {alias: m.NAME for m in modules for alias in getattr(m, "ALIASES", [])}


def build_parser(modules: list[ModuleType] | None = None) -> argparse.ArgumentParser:
    modules = actions.discover() if modules is None else modules
    parser = Parser(
        prog="./platformctl",
        description="Run and diagnose the Prometheus platform.",
        epilog=sections_epilog(modules),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_global_options(parser)
    parser.add_argument("--version", action="store_true", help="Show the tool and platform version")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", help=argparse.SUPPRESS, parser_class=Parser)
    for module in modules:
        sub = subparsers.add_parser(
            module.NAME, aliases=list(getattr(module, "ALIASES", [])), help=module.HELP, description=module.HELP
        )
        leaves = _group_leaves(module)
        if leaves:
            nested = sub.add_subparsers(dest="subcommand", metavar="<subcommand>", required=True, parser_class=Parser)
            for leaf in leaves:
                leaf_parser = nested.add_parser(
                    leaf.NAME, aliases=list(getattr(leaf, "ALIASES", [])), help=leaf.HELP, description=leaf.HELP
                )
                leaf.add_arguments(leaf_parser)
                add_global_options(leaf_parser, SUB_PREFIX)
                leaf_parser.set_defaults(_run=leaf.run)
        else:
            module.add_arguments(sub)
            add_global_options(sub, SUB_PREFIX)
            sub.set_defaults(_run=module.run)
    return parser


def _wants_json(argv: Sequence[str]) -> bool:
    return "--json" in split_double_dash(argv)[0]


def _version_info(paths: Paths, config: PlatformConfig, runner: Runner, modules: list[ModuleType]) -> dict:
    return {
        "version": __version__,
        "platform_version": platform_version(paths.root, runner),
        "commands": [m.NAME for m in modules],
        "features": list(jsonout.FEATURES),
    }


def main(argv: Sequence[str] | None = None, *, env: dict[str, str] | None = None, out=None, err=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ if env is None else env)
    out = out or sys.stdout
    err = err or sys.stderr
    modules = actions.discover()
    parser = build_parser(modules)
    own_args, extra = split_double_dash(argv)
    paths = Paths.default()
    runner = Runner()
    scrubber = Scrubber()
    output = Output(scrubber, out=out, err=err, env=env)
    wants_json = _wants_json(argv)
    # Before parsing: a usage error echoes the user's argv, and nothing may leak through it.
    scrubber.add_all(PlatformConfig(paths.root, env).secret_values())

    def fail(command: str, code: str, message: str, hint: str = "", exit_code: int = jsonout.EXIT_FAIL) -> int:
        if wants_json:
            platform = {
                "root": str(paths.root),
                "project": env.get("COMPOSE_PROJECT_NAME", "prometheus_platform"),
                "version": "unknown",
            }
            jsonout.emit(jsonout.error_object(command, platform, code, message, hint), out, scrubber.scrub)
        else:
            output.error(message, hint or None)
        return exit_code

    try:
        try:
            # argparse prints --help to sys.stdout and exits; capture it so it goes through
            # the scrubber and the stream we were given.
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    args = parser.parse_args(own_args)
            except SystemExit as done:
                out.write(scrubber.scrub(captured.getvalue()))
                return int(done.code or 0)
        except UsageError as exc:
            return fail("", "usage", str(exc), exit_code=jsonout.EXIT_USAGE)
        merge_globals(args)
        output.quiet, output.verbose, output.json_mode = args.quiet, args.verbose or output.ci, args.json

        config = PlatformConfig(paths.root, env, parse_set(args.set))
        scrubber.add_all(config.secret_values())
        runner = Runner(scrub=scrubber.scrub, echo=output.command)

        if args.version:
            info = _version_info(paths, config, runner, modules)
            if args.json:
                platform = {"root": str(paths.root), "project": config.project, "version": info["platform_version"]}
                jsonout.emit(jsonout.result("version", platform, **info), out, scrubber.scrub)
            else:
                output.write(f"platformctl {info['version']} (platform {info['platform_version']})")
            return jsonout.EXIT_OK
        if not args.command:
            parser.print_help(out)
            return jsonout.EXIT_OK

        name = aliases_of(modules).get(args.command, args.command)
        if name != "doctor":  # doctor reports a malformed .env; everything else stops on it
            config.require_valid_dotenv()
        if name != args.command:
            output.warn(f"`{args.command}` is deprecated; use `{name}`.")
        ctx = build(
            paths,
            config,
            output,
            runner,
            target=args.target,
            dry_run=args.dry_run,
            yes=args.yes,
            json_mode=args.json,
            debug=args.debug,
        )
        args.extra = extra
        return args._run(ctx, args)
    except (ConfigError, UnsupportedError) as exc:
        return fail(_command(own_args, modules), "config_invalid", str(exc))
    except envfile.EnvFileError as exc:
        return fail(_command(own_args, modules), "config_invalid", f".env: {exc}", "Fix that line in .env.")
    except RunnerError as exc:
        return fail(_command(own_args, modules), "docker_unavailable", str(exc))
    except KeyboardInterrupt:
        return jsonout.EXIT_INTERRUPTED
    except Exception as exc:  # the top-level handler: nothing escapes unscrubbed
        message = f"unexpected error: {type(exc).__name__}: {exc}"
        if "--debug" in own_args:
            message += "\n" + traceback.format_exc()
        return fail(_command(own_args, modules), "internal", message, "Run again with --debug for details.")


def _command(argv: Sequence[str], modules: list[ModuleType]) -> str:
    """The command word (not an option's value), to label an error."""
    names = {m.NAME for m in modules} | set(aliases_of(modules))
    return next((a for a in argv if a in names), "")
