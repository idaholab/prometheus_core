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

"""scripts/init_env.py in a real terminal: the questions and the LLM menu, with real keystrokes.

The other tests replace ``input`` and ``interactive``. These run the script in a pseudo-terminal,
so the terminal checks (``isatty``), ``termios`` raw mode, the arrow-key menu, the hidden key
prompt, and Ctrl-C are the real ones. A scratch copy of the script, ``.env.example`` and the
SDK's LLM profiles is used, so nothing outside ``tmp_path`` is touched.
"""

import os
import re
import select
import shutil
import signal
import sys
import time
from pathlib import Path

import pytest

pty = pytest.importorskip("pty", reason="needs a pseudo-terminal (not available on Windows)")

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs a pseudo-terminal")

TIMEOUT = 20.0
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")


@pytest.fixture
def platform(tmp_path: Path, project_root: Path) -> Path:
    """A platform folder with the real script, .env.example and the SDK's LLM profiles."""
    root = tmp_path / "platform"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(project_root / ".env.example", root)
    shutil.copy(project_root / "scripts" / "init_env.py", root / "scripts")
    shutil.copytree(
        project_root.parent / "sdk" / "prometheus_api" / "llm_configs",
        tmp_path / "sdk" / "prometheus_api" / "llm_configs",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return root


class Terminal:
    """init_env.py running with a pseudo-terminal as stdin and stdout."""

    def __init__(self, root: Path, **env: str):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "LLM_", "MAKE", "INIT_ENV"))}
        self.output = b""
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # child: stdin, stdout and stderr are the terminal
            os.chdir(root)
            os.execve(sys.executable, [sys.executable, "-I", "scripts/init_env.py"], {**clean, **env})
        self.status: int | None = None

    def read_until(self, text: str) -> None:
        """Read the terminal until ``text`` has been printed (escape codes removed)."""
        deadline = time.monotonic() + TIMEOUT
        while text.encode() not in ANSI.sub(b"", self.output):
            if time.monotonic() > deadline:
                self.kill()
                pytest.fail(f"never saw {text!r}; got:\n{ANSI.sub(b'', self.output).decode(errors='replace')}")
            if select.select([self.fd], [], [], 0.2)[0]:
                try:
                    chunk = os.read(self.fd, 4096)
                except OSError:  # the child closed the terminal
                    break
                if not chunk:
                    break
                self.output += chunk

    def read_until_any(self, *texts: str) -> str:
        """Read until one of ``texts`` has been printed; return the one that was."""
        deadline = time.monotonic() + TIMEOUT
        while True:
            seen = ANSI.sub(b"", self.output).decode(errors="replace")
            for text in texts:
                if text in seen:
                    return text
            if time.monotonic() > deadline:
                self.kill()
                pytest.fail(f"never saw any of {texts!r}; got:\n{seen}")
            if select.select([self.fd], [], [], 0.2)[0]:
                try:
                    chunk = os.read(self.fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    self.kill()
                    pytest.fail(f"the script ended before any of {texts!r}; got:\n{seen}")
                self.output += chunk

    def send(self, keys: bytes) -> None:
        os.write(self.fd, keys)

    def finish(self) -> int:
        """Wait for the script to exit; return its exit status."""
        deadline = time.monotonic() + TIMEOUT
        while True:
            try:
                if select.select([self.fd], [], [], 0.2)[0]:
                    chunk = os.read(self.fd, 4096)
                    if chunk:
                        self.output += chunk
            except OSError:
                pass
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                self.status = os.waitstatus_to_exitcode(status)
                return self.status
            if time.monotonic() > deadline:
                self.kill()
                pytest.fail("the script did not exit")

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass

    @property
    def text(self) -> str:
        return ANSI.sub(b"", self.output).decode(errors="replace")


def env_lines(root: Path) -> dict[str, str]:
    lines = (root / ".env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


def test_enter_twice_answers_yes_and_the_menu_picks_a_profile(platform):
    """A fresh clone in a terminal: Enter, Enter, then Enter on the (default) first profile."""
    term = Terminal(platform)
    term.read_until("(LOCAL_SDK)?")
    term.send(b"\r")
    term.read_until("(LOCAL_DEEPLYNX)?")
    term.send(b"\r")
    term.read_until("Choose an LLM profile")
    term.read_until("amsc")  # the menu is drawn
    term.send(b"\r")  # the highlighted (first) profile
    # A profile with a provider key asks for it with the input hidden; a keyless one does not
    if term.read_until_any("(input hidden)", "Saved LLM_CONFIG_PROFILE") == "(input hidden)":
        term.send(b"sk-test-not-echoed\r")

    assert term.finish() == 0, term.text
    written = env_lines(platform)
    assert written["LOCAL_SDK"] == "true" and written["LOCAL_DEEPLYNX"] == "true"
    assert written["LLM_CONFIG_PROFILE"]
    assert "sk-test-not-echoed" not in term.text, "the key was echoed to the terminal"
    assert oct((platform / ".env").stat().st_mode & 0o777) == "0o600"


def test_a_no_is_saved_and_a_typo_asks_again(platform):
    term = Terminal(platform, LLM_CONFIG_PROFILE="ollama")
    term.read_until("(LOCAL_SDK)?")
    term.send(b"nope\r")  # not y or n: asked again
    term.read_until("Please answer y or n")
    term.read_until("(LOCAL_SDK)?")
    term.send(b"n\r")
    term.read_until("(LOCAL_DEEPLYNX)?")
    term.send(b"\r")

    assert term.finish() == 0, term.text
    written = env_lines(platform)
    assert written["LOCAL_SDK"] == "false" and written["LOCAL_DEEPLYNX"] == "true"


def test_an_answered_env_asks_nothing_in_a_terminal(platform):
    first = Terminal(platform, LLM_CONFIG_PROFILE="ollama")
    for question in ("(LOCAL_SDK)?", "(LOCAL_DEEPLYNX)?"):
        first.read_until(question)
        first.send(b"\r")
    assert first.finish() == 0

    before = (platform / ".env").read_text()
    second = Terminal(platform)
    assert second.finish() == 0, second.text
    assert "LOCAL_SDK)?" not in second.text
    assert (platform / ".env").read_text() == before


def test_ctrl_c_at_the_second_question_keeps_the_first_answer(platform):
    """What the script's comment promises: an interrupt keeps what was answered, and says how to go on."""
    term = Terminal(platform, LLM_CONFIG_PROFILE="ollama")
    term.read_until("(LOCAL_SDK)?")
    term.send(b"\r")
    term.read_until("(LOCAL_DEEPLYNX)?")
    term.send(b"\x03")  # Ctrl-C: the terminal turns it into SIGINT for the script

    assert term.finish() == 130, term.text
    assert "Stopped. Run make again to continue" in term.text
    assert "Traceback" not in term.text
    written = env_lines(platform)
    assert written["LOCAL_SDK"] == "true"
    assert "LOCAL_DEEPLYNX" not in written
    assert written["AGENT_SECRET"], "the generated secrets are kept too"


def test_end_of_input_stops_cleanly_without_a_traceback(platform):
    term = Terminal(platform, LLM_CONFIG_PROFILE="ollama")
    term.read_until("(LOCAL_SDK)?")
    term.send(b"\x04")  # Ctrl-D: end of input at the prompt

    assert term.finish() == 130, term.text
    assert "Traceback" not in term.text
