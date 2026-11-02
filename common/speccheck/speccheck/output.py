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

"""Text output: problems on stderr as `path:line: message`, then one summary line.

Everything printed goes through `plain`, so text from a spec or a results file can't start a CI
log command. With `--json`, stdout is the one JSON object and nothing else is printed there.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TextIO

from speccheck.specs import Problem, plain


@dataclass
class Output:
    """Where and how much to print."""

    out: TextIO = field(default_factory=lambda: sys.stdout)
    """Normal output."""
    err: TextIO = field(default_factory=lambda: sys.stderr)
    """Problems, notices and errors."""
    quiet: bool = False
    """Only problems and errors (`--quiet`)."""
    verbose: bool = False
    """Also every requirement's status (`--verbose`)."""
    json_mode: bool = False
    """Print one JSON object on stdout instead (`--json`)."""

    def info(self, text: str = "") -> None:
        """A line of normal output, unless `--quiet` or `--json`."""
        if not (self.quiet or self.json_mode):
            self.out.write(plain(text) + "\n")

    def detail(self, text: str) -> None:
        """A line shown only with `--verbose`."""
        if self.verbose and not self.json_mode:
            self.out.write(plain(text) + "\n")

    def problems(self, problems: list[Problem]) -> None:
        """Each problem on stderr, unless `--json`, which carries them."""
        if self.json_mode:
            return
        for problem in problems:
            self.err.write(str(problem) + "\n")

    def summary(self, command: str, text: str, problems: int) -> None:
        """The last line: on stdout when clean, on stderr with the problem count otherwise."""
        if self.json_mode:
            return
        if problems:
            noun = "problem" if problems == 1 else "problems"
            self.err.write(plain(f"speccheck {command}: {text}; {problems} {noun}") + "\n")
        elif not self.quiet:
            self.out.write(plain(f"speccheck {command}: {text}") + "\n")

    def error(self, text: str) -> None:
        """A usage or config error on stderr."""
        self.err.write(plain(f"speccheck: error: {text}") + "\n")
