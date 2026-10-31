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

import os
import signal
import sys

import pytest

from platformctl.system import runner as runmod
from platformctl.system.runner import Runner, RunnerError, exit_code

PY = sys.executable
"""The Python that runs the child commands."""


def test_exit_code_maps_signals_to_128_plus_n():
    """Exit code maps signals to 128 plus n."""
    assert exit_code(0) == 0
    assert exit_code(3) == 3
    assert exit_code(-signal.SIGINT) == 128 + signal.SIGINT


def test_capture_returns_scrubbed_output():
    """Captured stdout and stderr are scrubbed, and the exit code is kept."""
    runner = Runner(scrub=lambda text: text.replace("secretvalue", "***"))
    done = runner.run(
        [PY, "-c", "import sys; print('a secretvalue'); print('b secretvalue', file=sys.stderr); sys.exit(4)"]
    )
    assert (done.returncode, done.stdout.strip(), done.stderr.strip()) == (4, "a ***", "b ***")
    assert not done.ok


def test_echo_gets_the_argv():
    """The echo function is given each argv before it runs."""
    seen = []
    Runner(echo=seen.append).run([PY, "-c", "pass"])
    assert seen == [[PY, "-c", "pass"]]


def test_make_variables_are_dropped_and_values_pass_through_env():
    """Make variables are dropped and values pass through env."""
    env = {**os.environ, "MAKEFLAGS": "x", "MFLAGS": "x", "MAKELEVEL": "1", "MAKEOVERRIDES": "x", "WANTED": "yes"}
    code = "import os; print(sorted(k for k in os.environ if k.startswith(('MAKE', 'MFLAGS'))), os.environ['WANTED'])"
    done = Runner().run([PY, "-c", code], env=env)
    assert done.stdout.strip() == "[] yes"


def test_default_env_is_ours(monkeypatch):
    """Without an `env`, the child gets our environment minus Make's variables."""
    monkeypatch.setenv("MAKEFLAGS", "x")
    done = Runner().run([PY, "-c", "import os; print('MAKEFLAGS' in os.environ)"])
    assert done.stdout.strip() == "False"


def test_stdin_and_cwd(tmp_path):
    """Input is passed on stdin and the command runs in `cwd`."""
    done = Runner().run([PY, "-c", "import os, sys; print(os.getcwd(), sys.stdin.read())"], cwd=tmp_path, stdin="hi")
    assert done.stdout.split()[-1] == "hi"
    assert os.path.realpath(done.stdout.split()[0]) == os.path.realpath(tmp_path)


def test_timeout_is_reported_as_124():
    """Timeout is reported as 124."""
    done = Runner().run([PY, "-c", "import time; time.sleep(5)"], timeout=0.2)
    assert (done.returncode, done.stderr) == (124, "timed out")


def test_a_missing_command_is_a_runner_error():
    """A missing command is a runner error."""
    with pytest.raises(RunnerError, match="can't run"):
        Runner().run(["/nonexistent/definitely-not-here"])
    with pytest.raises(RunnerError):
        Runner().run(["/nonexistent/definitely-not-here"], capture=False)


def test_streamed_output_is_scrubbed_and_printed(capsys):
    """Streamed output is scrubbed and printed."""
    runner = Runner(scrub=lambda text: text.replace("secretvalue", "***"))
    done = runner.run([PY, "-c", "print('line secretvalue'); print('two')"], capture=False)
    assert capsys.readouterr().out == "line ***\ntwo\n"
    assert done.stdout == "line ***\ntwo"
    assert done.ok


def test_sigint_is_ignored_only_while_waiting_and_then_restored():
    """Sigint is ignored only while waiting and then restored."""
    before = signal.getsignal(signal.SIGINT)
    Runner().run([PY, "-c", "pass"], capture=False)
    assert signal.getsignal(signal.SIGINT) is before
    Runner().run([PY, "-c", "pass"], interactive=True)
    assert signal.getsignal(signal.SIGINT) is before


def test_child_does_not_inherit_ignored_sigint():
    """Child does not inherit ignored sigint."""
    code = "import signal; print(signal.getsignal(signal.SIGINT) is signal.default_int_handler)"
    done = Runner().run([PY, "-c", code], capture=False)
    assert done.stdout.strip() == "True"


def test_interactive_returns_the_exit_code():
    """Interactive returns the exit code."""
    done = Runner().run([PY, "-c", "import sys; sys.exit(7)"], interactive=True)
    assert done.returncode == 7


def test_execvp_replaces_the_process_with_a_clean_env(monkeypatch):
    """Execvp replaces the process with a clean env."""
    calls = []
    monkeypatch.setattr(runmod.os, "execvpe", lambda *args: calls.append(args))
    seen = []
    runner = Runner(echo=seen.append)
    runner.execvp(["docker", "compose", "ps"], env={"A": "1", "MAKEFLAGS": "x"})
    assert calls == [("docker", ["docker", "compose", "ps"], {"A": "1"})]
    assert seen == [["docker", "compose", "ps"]]
    Runner().execvp(["docker"], env={})
    assert len(calls) == 2
