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

import pytest

from platformctl.output import MASK, Output, Scrubber, in_ci, plain_mode

PEM = "-----BEGIN KEY-----\nabcdefghij\nklmnopqrst\n-----END KEY-----"
"""A multi-line secret shaped like a private key."""


def test_scrubber_masks_value_and_encoded_forms():
    """Scrubber masks value and encoded forms."""
    scrubber = Scrubber()
    scrubber.add(PEM)
    assert scrubber.scrub(f"x {PEM} y") == f"x {MASK} y"
    assert scrubber.scrub(json.dumps({"k": PEM})) == f'{{"k": "{MASK}"}}'
    assert scrubber.scrub(repr(PEM)) == f"'{MASK}'"
    assert scrubber.scrub("line abcdefghij here") == f"line {MASK} here"


def test_scrubber_masks_inside_a_url():
    """Scrubber masks inside a url."""
    scrubber = Scrubber()
    scrubber.add("hunter2hunter2")
    assert scrubber.scrub("https://u:hunter2hunter2@host/x") == f"https://u:{MASK}@host/x"


@pytest.mark.parametrize("value", ["short", "true", "False", "12345678901", "        ", "", None])
def test_scrubber_ignores_trivial_values(value):
    """Short values, booleans and plain numbers are not scrubbed."""
    scrubber = Scrubber()
    scrubber.add(value)
    assert scrubber.scrub("short true False 12345678901") == "short true False 12345678901"


def test_scrubber_longest_form_first():
    """When one secret contains another, the longer is masked whole."""
    scrubber = Scrubber()
    scrubber.add_all(["abcdefgh", "abcdefghijkl"])
    assert scrubber.scrub("abcdefghijkl") == MASK


class Tty(io.StringIO):
    """A stream that says it is a terminal."""

    def isatty(self):
        """Say yes."""
        return True


def test_plain_mode():
    """No colours without a terminal, with `NO_COLOR` or with `TERM=dumb`."""
    assert plain_mode(io.StringIO(), {})
    assert not plain_mode(Tty(), {})
    assert plain_mode(Tty(), {"NO_COLOR": "1"})
    assert plain_mode(Tty(), {"TERM": "dumb"})


def test_plain_mode_and_ci_read_the_process_environment_by_default(monkeypatch):
    """Plain mode and ci read the process environment by default."""
    monkeypatch.setenv("NO_COLOR", "1")
    assert plain_mode(Tty())
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert not in_ci()
    monkeypatch.setenv("CI", "true")
    assert in_ci()


def test_in_ci():
    """`CI` or `GITHUB_ACTIONS` means CI."""
    assert in_ci({"CI": "true"})
    assert in_ci({"GITHUB_ACTIONS": "true"})
    assert not in_ci({})


def make(**kw) -> tuple[Output, io.StringIO, io.StringIO]:
    """An `Output` writing to two in-memory streams, returned with them."""
    out, err = io.StringIO(), io.StringIO()
    kw.setdefault("env", {})
    scrubber = kw.pop("scrubber", None)
    return Output(scrubber, out=out, err=err, **kw), out, err


def test_info_warn_error_are_scrubbed():
    """Info warn error are scrubbed."""
    scrubber = Scrubber()
    scrubber.add("supersecretvalue")
    output, out, err = make(scrubber=scrubber)
    output.info("a supersecretvalue")
    output.warn("b supersecretvalue")
    output.error("c supersecretvalue", hint="d supersecretvalue")
    assert "supersecretvalue" not in out.getvalue() + err.getvalue()
    assert out.getvalue() == f"a {MASK}\n"
    assert err.getvalue().splitlines() == [f"warning: b {MASK}", f"error: c {MASK}", f"d {MASK}"]


def test_quiet_keeps_only_errors():
    """`--quiet` hides everything but errors."""
    output, out, err = make(quiet=True)
    output.info("x")
    output.warn("y")
    output.debug("z")
    output.summary("t", [("a", "b")])
    output.error("e")
    assert out.getvalue() == ""
    assert err.getvalue() == "error: e\n"


def test_json_mode_moves_info_to_stderr():
    """Json mode moves info to stderr."""
    output, out, err = make(json_mode=True)
    output.info("progress")
    assert out.getvalue() == ""
    assert err.getvalue() == "progress\n"


def test_debug_only_when_verbose_or_ci():
    """Debug only when verbose or ci."""
    quiet, _, err = make()
    quiet.debug("hidden")
    assert err.getvalue() == ""
    verbose, _, err = make(verbose=True)
    verbose.debug("shown")
    assert err.getvalue() == "shown\n"
    ci, _, err = make(env={"CI": "1"})
    assert ci.verbose
    ci.debug("shown")
    assert err.getvalue() == "shown\n"


def test_command_echo_quotes_arguments():
    """The echoed command quotes arguments the way a shell needs."""
    output, _, err = make(verbose=True)
    output.command(["docker", "compose", "-f", "a b.yml", "it's"])
    assert err.getvalue() == "$ docker compose -f 'a b.yml' 'it'\\''s'\n"


def test_steps_and_colour():
    """Steps print `[n/N] title ... result`, and colour is used on a terminal."""
    out = Tty()
    output = Output(out=out, err=io.StringIO(), env={})
    output.begin(2)
    output.step("One").done()
    with output.step("Two") as step:
        step.done("3 agents")
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("[1/2] One ") and lines[0].endswith(" ok")
    assert lines[1].startswith("[2/2] Two ") and lines[1].endswith(" 3 agents")
    assert output._color("x", "red") == "\x1b[31mx\x1b[0m"


def test_failed_step_is_marked():
    """A step that exits with an exception is marked failed."""
    output, out, _ = make()
    output.begin(1)
    with pytest.raises(RuntimeError), output.step("Boom"):
        raise RuntimeError("x")
    assert out.getvalue().rstrip().endswith("failed")


def test_steps_in_ci_are_grouped():
    """Steps in ci are grouped."""
    output, _, err = make(env={"CI": "1"})
    output.begin(1)
    output.step("One").done()
    assert err.getvalue().splitlines() == ["::group::[1/1] One", "::endgroup::"]


def test_summary_block():
    """The summary has a title, aligned rows and a Next line."""
    output, out, _ = make()
    output.summary(
        "Prometheus is running", [("Chat UI", "http://localhost:5150"), ("Backend", "x")], "open the chat UI"
    )
    text = out.getvalue()
    assert "Prometheus is running" in text
    assert "  Chat UI  http://localhost:5150" in text
    assert "  Backend  x" in text
    assert text.rstrip().endswith("Next: open the chat UI")


def test_summary_without_rows_or_next():
    """Summary without rows or next."""
    output, out, _ = make()
    output.summary("Done", [])
    assert out.getvalue().strip() == "Done"
