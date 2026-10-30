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

"""The only module that starts subprocesses.

Values go to children through the environment, never as argv. Make's own
variables are dropped from every child's environment. Child output passes
through the secret scrubber.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

# Make's own variables never reach a child process.
MAKE_VARIABLES = ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES")


@dataclass
class Result:
    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class RunnerError(RuntimeError):
    """The command couldn't start (not found, not executable)."""


Scrub = Callable[[str], str]


def _clean_env(env: Mapping[str, str] | None) -> dict[str, str]:
    base = dict(os.environ if env is None else env)
    for name in MAKE_VARIABLES:
        base.pop(name, None)
    return base


def exit_code(returncode: int) -> int:
    """A signal death (negative return code) becomes 128+n, like a shell."""
    return 128 - returncode if returncode < 0 else returncode


class Runner:
    def __init__(self, scrub: Scrub | None = None, echo: Callable[[Sequence[str]], None] | None = None) -> None:
        self.scrub = scrub or (lambda text: text)
        self.echo = echo

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        capture: bool = True,
        interactive: bool = False,
        timeout: float | None = None,
        stdin: str | None = None,
    ) -> Result:
        """Run a command and wait.

        `capture=True` returns scrubbed stdout/stderr. `capture=False` streams each child line
        through the scrubber to our own stdout. `interactive=True` gives the child the terminal;
        the parent ignores SIGINT while it waits (Ctrl-C reaches the child), set only after
        `Popen` returns so the child doesn't inherit `SIG_IGN`.
        """
        argv = list(argv)
        if self.echo:
            self.echo(argv)
        child_env = _clean_env(env)
        try:
            if interactive:
                return self._interactive(argv, child_env, cwd)
            if capture:
                done = subprocess.run(
                    argv,
                    env=child_env,
                    cwd=cwd,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=timeout,
                    check=False,
                )
                return Result(argv, exit_code(done.returncode), self.scrub(done.stdout), self.scrub(done.stderr))
            return self._streamed(argv, child_env, cwd)
        except subprocess.TimeoutExpired:
            return Result(argv, 124, "", "timed out")
        except OSError as exc:
            raise RunnerError(f"can't run {argv[0]}: {exc.strerror or exc}") from None

    def _interactive(self, argv: list[str], env: dict[str, str], cwd: str | os.PathLike[str] | None) -> Result:
        proc = subprocess.Popen(argv, env=env, cwd=cwd)  # noqa: S603
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            code = proc.wait()
        finally:
            signal.signal(signal.SIGINT, previous)
        return Result(argv, exit_code(code))

    def _streamed(self, argv: list[str], env: dict[str, str], cwd: str | os.PathLike[str] | None) -> Result:
        proc = subprocess.Popen(  # noqa: S603
            argv,
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        lines: list[str] = []
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                clean = self.scrub(line.rstrip("\n"))
                lines.append(clean)
                print(clean, flush=True)
            code = proc.wait()
        finally:
            signal.signal(signal.SIGINT, previous)
        return Result(argv, exit_code(code), "\n".join(lines))

    def execvp(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> None:
        """Replace this process (pure passthroughs: `compose --`, following `logs`)."""
        if self.echo:
            self.echo(list(argv))
        os.execvpe(argv[0], list(argv), _clean_env(env))
