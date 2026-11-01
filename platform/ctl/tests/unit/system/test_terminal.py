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

import builtins
import getpass
import io
import sys
import types
import warnings

import pytest

from platformctl.system import terminal

OPTIONS = ["alpha", "beta", "gamma"]
"""The menu options the tests choose between."""
LABELS = ["first", "second", "third"]
"""Their labels."""


class Tty(io.StringIO):
    """A stdin/stdout that says whether it is a terminal, and has a file descriptor."""

    def __init__(self, tty: bool) -> None:
        """Remember whether this is a terminal."""
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        """Whether it is a terminal."""
        return self.tty

    def fileno(self) -> int:
        """A made-up file descriptor, which the fake `termios` and `os.read` accept."""
        return 7


@pytest.mark.parametrize(
    ("stdin", "stdout", "expected"), [(True, True, True), (True, False, False), (False, True, False)]
)
def test_interactive_needs_both_streams_to_be_terminals(monkeypatch, stdin, stdout, expected):
    """A pipe on either side means no question is asked."""
    monkeypatch.setattr(sys, "stdin", Tty(stdin))
    monkeypatch.setattr(sys, "stdout", Tty(stdout))
    assert terminal.interactive() is expected


@pytest.fixture
def fake_tty(monkeypatch):
    """Fake `termios` and `tty` modules and an `os.read` fed from a list of keys; returns (keys, calls)."""
    keys: list[bytes] = []
    calls: list[str] = []
    fake_termios = types.SimpleNamespace(
        tcgetattr=lambda fd: calls.append("get") or "saved",
        tcsetattr=lambda fd, when, saved: calls.append(f"restore {saved}"),
        TCSADRAIN=1,
    )
    fake_tty_module = types.SimpleNamespace(setcbreak=lambda fd: calls.append("cbreak"))
    monkeypatch.setitem(sys.modules, "termios", fake_termios)
    monkeypatch.setitem(sys.modules, "tty", fake_tty_module)

    def read(fd, count):
        """The next key; an exception in the list is raised, like Ctrl-C."""
        key = keys.pop(0)
        if isinstance(key, BaseException):
            raise key
        return key

    monkeypatch.setattr(terminal.os, "read", read)
    monkeypatch.setattr(sys, "stdin", Tty(True))
    return keys, calls


def test_choose_moves_with_the_arrow_keys_and_wraps(fake_tty):
    """Down, down, down wraps to the top; up goes back to the end; Enter picks."""
    keys, calls = fake_tty
    keys += [b"\x1b[B", b"\x1b[B", b"\x1b[B", b"\x1b[A", b"\r"]
    assert terminal.choose(OPTIONS, LABELS, 0) == "gamma"
    assert calls == ["get", "cbreak", "restore saved"]


def test_choose_ignores_other_keys(fake_tty):
    """A key that is neither up nor down changes nothing."""
    keys, _ = fake_tty
    keys += [b"x", b"\x1b[C", b"\r"]
    assert terminal.choose(OPTIONS, LABELS, 1) == "beta"


def test_choose_takes_j_and_k_and_the_default(fake_tty):
    """`j`/`k` move like the arrows, and Enter straight away takes the default."""
    keys, _ = fake_tty
    keys += [b"j", b"k", b"k", b"\n"]
    assert terminal.choose(OPTIONS, LABELS, 1) == "alpha"
    keys += [b"\r"]
    assert terminal.choose(OPTIONS, LABELS, 2) == "gamma"


def test_choose_draws_every_option_with_its_label_and_marks_the_current_one(fake_tty, capsys):
    """Every line shows, the current one reversed, and the cursor is hidden then shown again."""
    keys, _ = fake_tty
    keys += [b"\r"]
    terminal.choose(OPTIONS, LABELS, 1)
    drawn = capsys.readouterr().out
    assert "\x1b[7m> beta   second" in drawn and "alpha  first" in drawn and "gamma  third" in drawn
    assert drawn.startswith("\x1b[?25l") and drawn.endswith("\x1b[?25h")


def test_choose_restores_the_terminal_when_interrupted(fake_tty):
    """Ctrl-C mid-menu still puts the terminal back."""
    keys, calls = fake_tty
    keys.append(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        terminal.choose(OPTIONS, LABELS, 0)
    assert calls[-1] == "restore saved"


@pytest.fixture
def no_termios(monkeypatch):
    """Make `import termios` fail, as on Windows."""
    monkeypatch.setitem(sys.modules, "termios", None)


@pytest.mark.parametrize(("answers", "expected"), [(["2"], "beta"), ([""], "gamma"), (["9", "x", "1"], "alpha")])
def test_choose_falls_back_to_numbers_without_termios(no_termios, monkeypatch, capsys, answers, expected):
    """A numbered list; Enter takes the default, and a number out of range or a non-number asks again."""
    given = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt: next(given))
    assert terminal.choose(OPTIONS, LABELS, 2) == expected
    out = capsys.readouterr().out
    assert "  1. alpha  first" in out
    assert out.count("Please enter a number from 1 to 3") == len(answers) - 1


def test_choose_without_termios_stops_when_the_input_closes(no_termios, monkeypatch):
    """Ctrl-D at the numbered prompt is a `TerminalError`, which `config init` reports as `needs_terminal`."""

    def closed(prompt):
        """`input()` on a closed stdin."""
        raise EOFError

    monkeypatch.setattr(builtins, "input", closed)
    with pytest.raises(terminal.TerminalError, match="input was closed"):
        terminal.choose(OPTIONS, LABELS, 0)


def test_confirm_stops_when_the_input_closes(monkeypatch):
    """A closed stdin (Ctrl-D, or `< /dev/null`) is a `TerminalError`, not an `EOFError` that ends as `internal`."""

    def closed(prompt):
        """`input()` on a closed stdin."""
        raise EOFError

    monkeypatch.setattr(builtins, "input", closed)
    with pytest.raises(terminal.TerminalError, match="input was closed"):
        terminal.confirm("Build it?", True)


def test_confirm_says_what_it_wants_after_a_wrong_answer(monkeypatch, capsys):
    """`maybe` is not silently asked again: the person is told to answer y or n."""
    given = iter(["maybe", "n"])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(given))
    assert terminal.confirm("Build it?", True) is False
    assert "Please answer y or n" in capsys.readouterr().out


def test_read_secret_stops_when_the_input_closes(monkeypatch):
    """Ctrl-D at the hidden prompt is a `TerminalError` too."""

    def closed(prompt):
        """`getpass` on a closed stdin."""
        raise EOFError

    monkeypatch.setattr(getpass, "getpass", closed)
    with pytest.raises(terminal.TerminalError, match="input was closed"):
        terminal.read_secret("key: ")


@pytest.mark.parametrize(
    ("answers", "default", "expected"),
    [
        ([""], True, True),
        ([""], False, False),
        (["n"], True, False),
        (["Yes"], False, True),
        (["maybe", "huh", "y"], False, True),
    ],
)
def test_confirm(monkeypatch, capsys, answers, default, expected):
    """Enter takes the default, `y`/`n` answer, and anything else asks again."""
    given = iter(answers)
    prompts = []
    monkeypatch.setattr(builtins, "input", lambda prompt: prompts.append(prompt) or next(given))
    assert terminal.confirm("Build it?", default) is expected
    assert prompts[0] == f"Build it? {'[Y/n]' if default else '[y/N]'} "
    assert len(prompts) == len(answers)


def test_read_secret_strips_and_returns_the_value(monkeypatch):
    """The value is read with `getpass` and trimmed."""
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "  sk-secret \n")
    assert terminal.read_secret("key: ") == "sk-secret"


def test_read_secret_stops_rather_than_echo(monkeypatch):
    """A `GetPassWarning` (the terminal would echo) becomes an error, and the value is never read."""

    def echoing(prompt):
        """`getpass` on a terminal that can't hide input: it warns and echoes."""
        warnings.warn("Can not control echo on the terminal.", getpass.GetPassWarning, stacklevel=1)
        return "would-be-echoed"

    monkeypatch.setattr(getpass, "getpass", echoing)
    with pytest.raises(terminal.TerminalError, match="would echo"):
        terminal.read_secret("key: ")
