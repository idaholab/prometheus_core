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

"""`config`: show the settings, write values into `.env`, and (`config init`) create or complete it."""

from __future__ import annotations

import argparse

from platformctl import env_init, jsonout, llm_profiles
from platformctl.actions import Subcommand
from platformctl.config import REGISTRY, SETTINGS, ConfigError, check_value, is_name, is_safe, parse_set
from platformctl.context import Context
from platformctl.system import envfile, terminal

NAME = "config"
"""The command's name."""
HELP = "Show, set and initialize the settings in .env"
"""The command's one-line description in `--help`."""
SECTION = "setup"
"""The `--help` section the command is listed in."""
ORDER = 10
"""Where the command sits within its section; lower is listed first."""


# -- config init --------------------------------------------------------------------------------


def add_init_arguments(parser: argparse.ArgumentParser) -> None:
    """Add `config init`'s options: whether to build the SDK and run DeepLynx on this laptop."""
    parser.add_argument(
        "--local-sdk",
        action=argparse.BooleanOptionalAction,
        help="Build the prometheus_api base image on this laptop (no INL login), or not; sets LOCAL_SDK",
    )
    parser.add_argument(
        "--local-deeplynx",
        action=argparse.BooleanOptionalAction,
        help="Run DeepLynx on this laptop, or not; sets LOCAL_DEEPLYNX",
    )


def _save(ctx: Context, values: dict[str, str]) -> None:
    """Write values into `.env`, and have the scrubber hide the ones that are secret from now on."""
    env_init.write_env(ctx.paths.env, ctx.output, values)
    ctx.output.scrubber.add_all(value for key, value in values.items() if not is_safe(key))


def _error(ctx: Context, code: str, lines: list[str]) -> int:
    """Report an LLM-settings problem and return 1: the error block `init_env.py` printed on stderr, or with
    `--json` one error object whose message is the lines joined and whose `code` says which problem."""
    if ctx.json_mode:
        return _fail(ctx, "config init", code, " ".join(lines))
    ctx.output.write("\n[ERROR] " + "\n        ".join(lines) + "\n", err=True)
    return jsonout.EXIT_FAIL


def _save_from_environment(ctx: Context, current: dict[str, str], known: dict) -> dict[str, str]:
    """Take LLM_CONFIG_PROFILE and the key its profile needs from the environment, as CI sets them."""
    env = ctx.config.env
    if llm_profiles.missing_profile(current) and env.get("LLM_CONFIG_PROFILE"):
        _save(ctx, {"LLM_CONFIG_PROFILE": env["LLM_CONFIG_PROFILE"]})
        current = envfile.read(ctx.paths.env)
        ctx.output.info(f"Saved LLM_CONFIG_PROFILE from the environment in {ctx.paths.env.name}.")
    key = llm_profiles.missing_llm_key(current, known)
    if key and env.get(key):
        _save(ctx, {key: env[key]})
        current = envfile.read(ctx.paths.env)
        ctx.output.info(f"Saved {key} from the environment in {ctx.paths.env.name}.")
    return current


def _prompt_llm(ctx: Context, current: dict[str, str], known: dict) -> None:
    """Ask for the LLM profile and its API key on the terminal, and save them."""
    options = list(known)
    labels = [desc if key else f"{desc}  [no key]" for key, desc in known.values()]
    chosen = current.get("LLM_CONFIG_PROFILE", "")
    ctx.output.info("\nChoose an LLM profile (up/down, Enter):")
    profile = terminal.choose(options, labels, options.index(chosen) if chosen in options else 0)
    updates = {"LLM_CONFIG_PROFILE": profile}
    key, _ = known[profile]
    if key and not current.get(key):
        secret = terminal.read_secret(f"{key} for {profile} (input hidden): ")
        if secret:
            updates[key] = secret
    _save(ctx, updates)
    ctx.output.info(f"Saved LLM_CONFIG_PROFILE={profile} in {ctx.paths.env.name}.")


def _llm_problem(ctx: Context, current: dict[str, str], known: dict) -> int | None:
    """Print what is wrong with the LLM settings and return 1, or return None when they are fine."""
    path = ctx.paths.env
    if llm_profiles.missing_profile(current):
        return _error(
            ctx,
            "config_invalid",
            [
                f"LLM_CONFIG_PROFILE is empty in {path}.",
                f"Available profiles: {', '.join(known)}.",
                "Set it (or set LLM_CONFIG_FILE) and run ./platformctl config init again.",
            ],
        )
    if profile := llm_profiles.unknown_profile(current, known):
        reason = (
            "is not supported on this platform (it needs an LLM proxy at REGISTRY_URL)"
            if profile in llm_profiles.UNSUPPORTED_PROFILES
            else "is not an installed profile"
        )
        return _error(
            ctx,
            "config_invalid",
            [
                f"LLM_CONFIG_PROFILE={profile} in {path} {reason}.",
                f"Available profiles: {', '.join(known)}.",
                "Fix it (or set LLM_CONFIG_FILE) and run ./platformctl config init again.",
            ],
        )
    if key := llm_profiles.missing_llm_key(current, known):
        return _error(
            ctx,
            "config_invalid",
            [
                f"{key} is empty in {path}.",
                f"LLM_CONFIG_PROFILE={current['LLM_CONFIG_PROFILE']} needs it; set it (or pick another profile)",
                "and run ./platformctl config init again. See README.md, 'Choose an LLM profile'.",
            ],
        )
    return None


def _asks(ctx: Context) -> bool:
    """Whether a question may be asked: on a terminal, and not while printing JSON."""
    return terminal.interactive() and not ctx.json_mode


def _decide(
    ctx: Context, *, key: str, flag: bool | None, decided: bool, label: str, ask, first_run: bool
) -> str | None:
    """Settle one yes/no setting (`LOCAL_SDK`, `LOCAL_DEEPLYNX`) and say what it is; return the line to print.

    A flag always wins. Otherwise a value `.env` already decides is never changed. Otherwise the
    question is asked on a terminal (`--yes` takes the recommended answer), and with no terminal
    nothing is asked and today's default (off) stays. The note naming the flag is for the run that creates
    `.env`, when the person is learning the flags; every later run without a terminal (CI, an assistant, each
    `make up`) stays quiet about it.
    """
    if flag is not None:
        _save(ctx, {key: "true" if flag else "false"})
        return f"{label}: {'yes' if flag else 'no'}"
    if decided:
        return None
    if ctx.yes or _asks(ctx):
        try:
            answer = ask()
        except terminal.TerminalError as exc:
            raise ConfigError(str(exc)) from None
        _save(ctx, {key: "true" if answer else "false"})
        return f"{label}: {'yes' if answer else 'no'}"
    if not first_run:
        return None
    name = "--" + label.lower().replace(" ", "-")
    return f"{label}: no (not asked without a terminal; use {name} to turn it on)"


def _ask_local_sdk(ctx: Context) -> bool:
    """Ask whether to build everything on this laptop; the recommendation comes from a test of the registry."""
    repo, tag = ctx.config.base_image()
    if not ctx.yes:
        # Off the VPN this waits up to the timeout; say so, or it looks like a hang.
        ctx.output.info("Checking whether you can pull from the INL registry (up to 15 s) ...")
    recommended = not ctx.docker.registry_reachable(f"{repo}:{tag}")
    if ctx.yes:
        return recommended
    question = f"Build everything on this laptop (no INL login needed)? (recommended: {'yes' if recommended else 'no'})"
    return terminal.confirm(question, recommended)


def _ask_local_deeplynx(ctx: Context) -> bool:
    """Ask whether to run DeepLynx on this laptop; yes is recommended."""
    if ctx.yes:
        return True
    return terminal.confirm("Run DeepLynx (file storage) on this laptop? (recommended: yes)", True)


def _decided(ctx: Context, key: str) -> bool:
    """Whether something other than a default already sets the key: `.env`, the environment or `make X=y`."""
    return key in ctx.config.dotenv or key in ctx.config.env or key in ctx.config.make


def _stale_for_make(ctx: Context, current: dict[str, str], before: dict[str, bool]) -> list[str]:
    """The settings this run changed that `make` has already read, so it is still using the old value.

    Make reads `.env` when it starts, to choose the base image and the DeepLynx targets. An answer
    given during `make up` therefore only takes effect on the next run. Only applies under Make.
    """
    if ctx.config.env.get("PLATFORMCTL_VIA_MAKE") != "1":
        return []
    # A key `.env` still lacks keeps the value it had (from the environment, which make also read, or the
    # default): comparing that with an absent `.env` key would call every exported LOCAL_SDK=true a change.
    return [key for key, was in before.items() if key in current and _is_true(current[key]) != was]


def _is_true(value: str | None) -> bool:
    """Whether a `.env` value counts as true."""
    return (value or "").strip().lower() == "true"


def init(ctx: Context, args: argparse.Namespace) -> int:
    """Create or complete `.env`: fill blank secrets, get the LLM profile and key, ask the two local questions.

    It never changes a value that is already set unless a flag asks. Without a terminal it asks
    nothing and exits 1 only where `scripts/init_env.py` did: no LLM profile or no key.
    """
    paths, out = ctx.paths, ctx.output
    if ctx.dry_run:
        out.info(f"Would create or complete {paths.env.name} from {paths.env_example.name}.")
        return _done(ctx, "config init", dry_run=True)
    created = False
    try:
        known = llm_profiles.profiles(paths.llm_configs)
        example = paths.env_example.read_text(encoding="utf-8")
        if created := env_init.create(paths.env_example, paths.env):
            out.info(f"Created {paths.env.name} from {paths.env_example.name}.")
        current = envfile.read(paths.env)
        filled = env_init.fill_secrets(ctx.runner, example, current)
    except (llm_profiles.ProfilesError, env_init.GenerateError) as exc:
        return _fail(ctx, "config init", "config_invalid", str(exc))
    if filled:
        _save(ctx, filled)
        out.info(f"Generated in {paths.env.name}: {', '.join(filled)}")
        current = envfile.read(paths.env)

    current = _save_from_environment(ctx, current, known)
    if (
        llm_profiles.missing_profile(current)
        or llm_profiles.unknown_profile(current, known)
        or llm_profiles.missing_llm_key(current, known)
    ) and _asks(ctx):
        try:
            _prompt_llm(ctx, current, known)
        except terminal.TerminalError as exc:
            return _fail(ctx, "config init", "needs_terminal", str(exc))
        current = envfile.read(paths.env)

    before = {key: ctx.config.flag(key) for key in ("LOCAL_SDK", "LOCAL_DEEPLYNX")}
    try:
        notes = [
            _decide(
                ctx,
                key="LOCAL_SDK",
                flag=args.local_sdk,
                decided=_decided(ctx, "LOCAL_SDK"),
                label="Local SDK",
                ask=lambda: _ask_local_sdk(ctx),
                first_run=created,
            ),
            _decide(
                ctx,
                key="LOCAL_DEEPLYNX",
                flag=args.local_deeplynx,
                decided=_decided(ctx, "LOCAL_DEEPLYNX") or bool(current.get("DEEPLYNX_KEY")),
                label="Local DeepLynx",
                ask=lambda: _ask_local_deeplynx(ctx),
                first_run=created,
            ),
        ]
    except ConfigError as exc:  # the terminal closed under a question
        return _fail(ctx, "config init", "needs_terminal", str(exc))
    current = envfile.read(paths.env)
    for note in notes:
        if note:
            out.info(note)
    if (problem := _llm_problem(ctx, current, known)) is not None:
        return problem
    out.info(f"LLM profile: {current.get('LLM_CONFIG_PROFILE') or 'custom file'}, key set")
    if stale := _stale_for_make(ctx, current, before):
        # Make chose the base image and the DeepLynx targets from the old `.env` before this ran, so going
        # on would build the wrong way (a registry pull the person just said they can't do). Stop; it's saved.
        return _fail(
            ctx,
            "config init",
            "config_invalid",
            f"Saved your answers ({', '.join(stale)}) in {paths.env.name}. make read {paths.env.name} before "
            "they were set, so it can't use them in this run.",
            "Run the same make command again.",
        )
    if missing := envfile.missing_keys(example, current):
        out.info(f"Keys in {paths.env_example.name} that {paths.env.name} lacks: {', '.join(missing)}")
        out.info(f"  Add them to {paths.env.name} (copy the lines from {paths.env_example.name}).")
    local_deeplynx = _is_true(current.get("LOCAL_DEEPLYNX"))
    if ctx.config.env.get("PLATFORMCTL_VIA_MAKE") != "1":
        # Under make the next step is already running (`make up` sets DeepLynx up itself).
        out.info("\nNext: make up" + (", then ./platformctl deeplynx setup" if local_deeplynx else ""))
    return _done(
        ctx,
        "config init",
        created=created,
        generated=list(filled),
        llm_profile=current.get("LLM_CONFIG_PROFILE", ""),
        local_sdk=_is_true(current.get("LOCAL_SDK")),
        local_deeplynx=local_deeplynx,
        missing_keys=missing,
    )


# -- config set ---------------------------------------------------------------------------------


def add_set_arguments(parser: argparse.ArgumentParser) -> None:
    """Add `config set`'s arguments: `KEY=value` pairs, or with `--from-env`, bare key names."""
    parser.add_argument("items", nargs="+", metavar="KEY=value", help="Settings to write into .env")
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="Copy each KEY's value from the environment instead (for secrets: the value never appears in argv)",
    )


def _from_environment(ctx: Context, keys: list[str]) -> dict[str, str]:
    """The environment's value of each key, or a `ConfigError` naming every key that is not set there."""
    bad = [key for key in keys if not is_name(key)]
    if bad:
        raise ConfigError("--from-env expects key names, not KEY=value: the value is read from the environment")
    env = ctx.config.env
    unset = [key for key in keys if not env.get(key)]
    if unset:
        # A bare token pasted by mistake (`--from-env "$SECRET"`) looks like a name, and the scrubber
        # doesn't know a value that is in neither `.env` nor a secret-named variable: name only keys we know.
        known = [key for key in unset if key in REGISTRY or key in ctx.config.dotenv]
        others = len(unset) - len(known)
        parts = ([", ".join(known)] if known else []) + ([f"{others} other name(s)"] if others else [])
        raise ConfigError("not set in the environment: " + "; ".join(parts))
    return {key: env[key] for key in keys}


def set_values(ctx: Context, args: argparse.Namespace) -> int:
    """Write values into `.env` in place; a secret goes only through `--from-env`."""
    try:
        if args.from_env:
            values = _from_environment(ctx, args.items)
        else:
            values = parse_set(
                args.items,
                what="config set",
                instead="use `config set --from-env {key}` with the value in the environment",
            )
        for key, value in values.items():
            check_value(key, value)
        if not ctx.paths.env.exists():
            raise ConfigError(".env does not exist; run ./platformctl config init first")
    except ConfigError as exc:
        return _fail(ctx, "config set", "config_invalid", str(exc))
    if ctx.dry_run:
        ctx.output.info("Would set " + ", ".join(values) + f" in {ctx.paths.env.name}.")
        return _done(ctx, "config set", dry_run=True, keys=list(values))
    env_init.write_env(ctx.paths.env, ctx.output, values)
    ctx.output.info(f"Set {', '.join(values)} in {ctx.paths.env.name}.")
    return _done(ctx, "config set", keys=list(values))


# -- config show --------------------------------------------------------------------------------


def add_show_arguments(parser: argparse.ArgumentParser) -> None:
    """`config show` takes no arguments of its own."""


def _shown(value: str, safe: bool) -> str:
    """A value as `config show` prints it: as is when safe, else `set` or `blank`."""
    if safe:
        return value
    return "set" if value else "blank"


def _rows(ctx: Context) -> list[dict[str, str]]:
    """Every registered setting, then every other key in `.env`, with its value (secrets as set/blank) and source."""
    rows = []
    for setting in SETTINGS:
        resolved = ctx.config.resolve(setting.name)
        rows.append(
            {
                "name": setting.name,
                "value": _shown(resolved.value, setting.safe),
                "source": resolved.source,
                "description": setting.description,
            }
        )
    known = {setting.name for setting in SETTINGS}
    for name in sorted(ctx.config.dotenv):
        if name not in known:
            resolved = ctx.config.resolve(name)
            rows.append(
                {
                    "name": name,
                    "value": _shown(resolved.value, is_safe(name)),
                    "source": resolved.source,
                    "description": "",
                }
            )
    return rows


def show(ctx: Context, args: argparse.Namespace) -> int:
    """Print each setting, its value (secrets as `set`/`blank`) and where it came from."""
    rows = _rows(ctx)
    out = ctx.output
    if ctx.json_mode:
        jsonout.emit(jsonout.result("config show", ctx.platform_info(), settings=rows), out.out, out.scrubber.scrub)
        return jsonout.EXIT_OK
    width = max(len(row["name"]) for row in rows)
    value_width = max(len(row["value"]) for row in rows)
    out.info(f"{'SETTING':<{width}}  {'VALUE':<{value_width}}  SOURCE")
    for row in rows:
        out.info(f"{row['name']:<{width}}  {row['value']:<{value_width}}  {row['source']}".rstrip())
    return jsonout.EXIT_OK


# -- shared -------------------------------------------------------------------------------------


def _fail(ctx: Context, command: str, code: str, message: str, hint: str = "") -> int:
    """Report a failure as JSON (naming `command`, such as `config set`) or as an error line; the exit code is 1."""
    out = ctx.output
    if ctx.json_mode:
        jsonout.emit(
            jsonout.error_object(command, ctx.platform_info(), code, message, hint), out.out, out.scrubber.scrub
        )
    else:
        out.error(message, hint or None)
    return jsonout.EXIT_FAIL


def _done(ctx: Context, command: str, **fields) -> int:
    """With `--json`, print the one result object for a command that succeeded; return 0."""
    if ctx.json_mode:
        out = ctx.output
        jsonout.emit(jsonout.result(command, ctx.platform_info(), **fields), out.out, out.scrubber.scrub)
    return jsonout.EXIT_OK


SUBCOMMANDS = [
    Subcommand(
        "init", "Create or complete .env: generate secrets, choose the LLM profile and key", add_init_arguments, init
    ),
    Subcommand("set", "Write settings into .env", add_set_arguments, set_values),
    Subcommand("show", "Show each setting, its value and where it came from", add_show_arguments, show),
]
"""The subcommands of `config`."""
