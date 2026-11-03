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

"""Asking the person at the terminal: a menu, a yes/no question and a hidden value.

Ported from `scripts/init_env.py`. Nothing here is called without a terminal (`interactive()`).
"""

from __future__ import annotations

import getpass
import os
import sys
import warnings


class TerminalError(RuntimeError):
    """The terminal can't be used safely, for example when it would echo a secret."""


def _read_line(prompt: str) -> str:
    """`input()`, but a closed input (Ctrl-D, or no stdin) is a `TerminalError` and not an `EOFError`."""
    try:
        return input(prompt)
    except EOFError:
        raise TerminalError("the input was closed before the question was answered") from None


def interactive() -> bool:
    """Whether both stdin and stdout are a terminal, so a question can be asked."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def choose(options: list[str], labels: list[str], default: int) -> str:
    """An arrow-key menu on the terminal; a numbered prompt where `termios` is missing (Windows)."""
    width = max(map(len, options))
    lines = [f"{o:<{width}}  {label}" for o, label in zip(options, labels, strict=True)]
    try:
        import termios
        import tty
    except ImportError:
        for i, line in enumerate(lines, 1):
            print(f"  {i}. {line}")
        while True:
            answer = _read_line(f"Choice [{default + 1}]: ").strip()
            if not answer:
                return options[default]
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]
            print(f"Please enter a number from 1 to {len(options)}, or press Enter for {default + 1}.")

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    index = default

    def draw(first: bool) -> None:
        """Draw the menu, over the previous drawing unless it is the first."""
        if not first:
            sys.stdout.write(f"\x1b[{len(lines)}A")
        for i, line in enumerate(lines):
            marker = "\x1b[7m> " if i == index else "  "
            sys.stdout.write(f"\r\x1b[2K{marker}{line}\x1b[0m\n")
        sys.stdout.flush()

    sys.stdout.write("\x1b[?25l")  # hide the cursor
    try:
        tty.setcbreak(fd)
        draw(first=True)
        while True:
            key = os.read(fd, 3)
            if key in (b"\r", b"\n"):
                return options[index]
            if key in (b"\x1b[A", b"k"):
                index = (index - 1) % len(options)
            elif key in (b"\x1b[B", b"j"):
                index = (index + 1) % len(options)
            draw(first=False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def confirm(question: str, default: bool) -> bool:
    """Ask a yes/no question; Enter gives `default`, shown as the capital letter in `[Y/n]`.

    Anything that does not start with `y` or `n` says so and asks again, so a typo isn't taken as an answer.
    """
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        answer = _read_line(f"{question} {hint} ").strip().lower()
        if not answer:
            return default
        if answer[0] in "yn":
            return answer[0] == "y"
        print("Please answer y or n, or press Enter for the answer in capitals.")


def read_secret(prompt: str) -> str:
    """Read a value without echoing it. Stops, rather than echo, where the terminal can't hide it."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt).strip()
        except getpass.GetPassWarning:
            raise TerminalError("this terminal would echo the value as you type it, so it was not asked") from None
        except EOFError:
            raise TerminalError("the input was closed before the value was entered") from None
