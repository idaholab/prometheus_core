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

"""Everything the tool prints goes through here, and through the secret scrubber.

See plans/platformctl/design.md, "Output" and "Secrets".
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterable
from typing import TextIO

MASK = "***"
"""What a secret is replaced with."""
MIN_SECRET_LENGTH = 8
"""Shorter values are not scrubbed: too many ordinary words would be hidden."""
_TRIVIAL = {"true", "false", "none", "null", "yes", "no"}
"""Values too common to scrub."""


def _is_trivial(value: str) -> bool:
    """Short values, booleans and plain numbers aren't worth scrubbing."""
    stripped = value.strip()
    return len(stripped) < MIN_SECRET_LENGTH or stripped.lower() in _TRIVIAL or stripped.isdigit()


def _forms(value: str) -> set[str]:
    """The value as it may appear in output: as is, JSON-escaped, repr'd, line by line."""
    forms = {value, json.dumps(value)[1:-1], repr(value)[1:-1]}
    forms.update(line.strip() for line in value.splitlines())
    return {f for f in forms if not _is_trivial(f)}


class Scrubber:
    """Replaces the values of secret keys with `***` in any text."""

    def __init__(self) -> None:
        """Start with no secrets registered."""
        self._forms: list[str] = []

    def add(self, value: str | None) -> None:
        """Register one secret value (and its encoded forms)."""
        if not value or _is_trivial(value):
            return
        known = set(self._forms) | _forms(value)
        # Longest first, so a form that contains another is replaced whole.
        self._forms = sorted(known, key=len, reverse=True)

    def add_all(self, values: Iterable[str | None]) -> None:
        """Register several secret values."""
        for value in values:
            self.add(value)

    def scrub(self, text: str) -> str:
        """Replace every registered secret in the text with `***`."""
        for form in self._forms:
            if form in text:
                text = text.replace(form, MASK)
        return text


def plain_mode(stream: TextIO, env: dict[str, str] | None = None) -> bool:
    """No colours or `\\r` progress: not a terminal, NO_COLOR, or TERM=dumb."""
    env = os.environ if env is None else env
    return not stream.isatty() or "NO_COLOR" in env or env.get("TERM") == "dumb"


def in_ci(env: dict[str, str] | None = None) -> bool:
    """Whether the run is in CI (`CI` or `GITHUB_ACTIONS` is set)."""
    env = os.environ if env is None else env
    return bool(env.get("CI") or env.get("GITHUB_ACTIONS"))


_ANSI = {"green": "32", "yellow": "33", "red": "31", "dim": "2", "bold": "1"}
"""The ANSI colour codes the output uses."""


class Output:
    """Steps, summaries, errors and notices, scrubbed, to stdout and stderr.

    With `json_mode`, stdout is reserved for the one JSON object, so progress
    and notices go to stderr.
    """

    def __init__(
        self,
        scrubber: Scrubber | None = None,
        *,
        out: TextIO | None = None,
        err: TextIO | None = None,
        quiet: bool = False,
        verbose: bool = False,
        json_mode: bool = False,
        env: dict[str, str] | None = None,
    ) -> None:
        """Choose the streams and modes: quiet, verbose (always in CI), JSON and plain."""
        self.scrubber = scrubber or Scrubber()
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.quiet = quiet
        self.json_mode = json_mode
        self.ci = in_ci(env)
        # CI keeps Compose's full output, so failure logs are complete.
        self.verbose = verbose or self.ci
        self.plain = plain_mode(self.out, env)
        self._step = 0
        self._steps = 0

    # -- low level -----------------------------------------------------

    def _stream(self) -> TextIO:
        """The stream for normal messages: stderr in JSON mode, since stdout is the JSON object."""
        return self.err if self.json_mode else self.out

    def _color(self, text: str, color: str) -> str:
        """Colour the text, unless the output is plain."""
        if self.plain:
            return text
        return f"\x1b[{_ANSI[color]}m{text}\x1b[0m"

    def write(self, text: str = "", *, err: bool = False) -> None:
        """Print one scrubbed line."""
        stream = self.err if err else self._stream()
        stream.write(self.scrubber.scrub(text) + "\n")
        stream.flush()

    # -- the kinds of message ------------------------------------------

    def info(self, text: str = "") -> None:
        """Print a message, unless `--quiet`."""
        if not self.quiet:
            self.write(text)

    def debug(self, text: str) -> None:
        """Shown only with --verbose (and always in CI)."""
        if self.verbose and not self.quiet:
            self.write(self._color(text, "dim"), err=True)

    def warn(self, text: str) -> None:
        """Print a warning on stderr, unless `--quiet`."""
        if not self.quiet:
            self.write(self._color("warning: ", "yellow") + text, err=True)

    def error(self, text: str, hint: str | None = None) -> None:
        """An error and the one line on what to do about it."""
        self.write(self._color("error: ", "red") + text, err=True)
        if hint:
            self.write(hint, err=True)

    def command(self, argv: Iterable[str]) -> None:
        """Echo a command the tool runs (--verbose and --dry-run)."""
        self.debug("$ " + " ".join(_quote(a) for a in argv))

    # -- steps and summaries -------------------------------------------

    def begin(self, total: int) -> None:
        """Start a numbered sequence of steps."""
        self._step, self._steps = 0, total

    def step(self, title: str) -> _Step:
        """Start the next numbered step."""
        self._step += 1
        return _Step(self, f"[{self._step}/{self._steps}] {title}")

    def summary(self, title: str, rows: Iterable[tuple[str, str]], next_line: str | None = None) -> None:
        """The block that ends `up`, `restart` and `status`."""
        if self.quiet:
            return
        rows = list(rows)
        self.write()
        self.write(self._color(title, "bold"))
        if rows:
            self.write()
            width = max(len(k) for k, _ in rows)
            for key, value in rows:
                self.write(f"  {key.ljust(width)}  {value}")
        if next_line:
            self.write()
            self.write(f"Next: {next_line}")


def _quote(arg: str) -> str:
    """Quote an argument for display, the way a shell would need it."""
    return arg if re.fullmatch(r"[\w@%+=:,./-]+", arg) else "'" + arg.replace("'", "'\\''") + "'"


class _Step:
    """One `[n/N] title ..... result` line, with `::group::` in CI."""

    WIDTH = 44
    """The column the step's result is aligned to."""

    def __init__(self, output: Output, title: str) -> None:
        """Start a step, opening a `::group::` in CI."""
        self.output = output
        self.title = title
        if output.ci:
            output.write(f"::group::{title}", err=True)

    def done(self, result: str = "ok") -> None:
        """Finish the step with a result, closing the CI group."""
        dots = "." * max(3, self.WIDTH - len(self.title))
        self.output.info(f"{self.title} {dots} {result}")
        if self.output.ci:
            self.output.write("::endgroup::", err=True)

    def __enter__(self) -> _Step:
        """Enter the step as a context manager."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Mark the step failed if it exits with an exception."""
        if exc_type is not None:
            self.done("failed")
