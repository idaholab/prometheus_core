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

"""The secrets canary: no secret may reach stdout, stderr or a generated file.

Every secret key gets a unique sentinel value (multi-line, quoted, containing `$`, inside a
URL). Every command runs with --verbose, --dry-run, --json, --debug and forced failures,
against a fake `docker` whose output contains the sentinels, so a path that echoes child
output is caught. Extended in every later step (design.md, "Secrets").
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from platformctl import cli
from platformctl.system import host
from tests.unit.conftest import make_context

SENTINELS = {
    "plain": "CANARYPLAINVALUE0001",
    "dollar": "canary$dollar$value0002",
    "quoted": "canary quoted value 0003",
    "url_password": "CANARYURLPASSWORD0004",
    "pem1": "CANARYPEMLINEONE0005abcdef",
    "pem2": "CANARYPEMLINETWO0006ghijkl",
    "env_only": "CANARYENVIRONMENT0007",
    "argv": "CANARYARGVVALUE0008",
    "issued_one": "CANARYISSUEDIDENTIFIER0009",
    "issued_two": "CANARYISSUEDCREDENTIAL0010",
    "body": "CANARYRESPONSEBODY0011",
    "auth": "CANARYAGENTSECRETFORAUTH0012",
}
"""A unique value for each shape of secret: plain, with `$`, quoted, in a URL, multi-line, from the environment, from argv,
and the ones a server sends back (a new API key and secret, an error body) or is sent (the bearer token)."""

DOTENV = f"""LLM_CONFIG_PROFILE=anthropic
LLM_API_KEY={SENTINELS["plain"]}
AGENT_SECRET='{SENTINELS["dollar"]}'
ADMIN_DB_PASSWORD="{SENTINELS["quoted"]}"
REDIS_PASSWORD={SENTINELS["url_password"]}
REDIS_URL=redis://:${{REDIS_PASSWORD}}@redis:6379
USER_IDENTITY_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
{SENTINELS["pem1"]}
{SENTINELS["pem2"]}
-----END PRIVATE KEY-----"
PASTED_BY_MISTAKE={SENTINELS["argv"]}
BACKEND_JWT_SECRET=aaaaaaaaaaaaaaaaaaaa
ADMIN_DB_ENCRYPTION_KEY=bbbbbbbbbbbbbbbbbbbb
DEEPLYNX_SECRET=something-else-secret
"""
"""A `.env` holding the sentinels as secrets."""

FAKE_DOCKER = f"""#!/bin/sh
case "$1 $2" in
  "info --format")
    if [ -n "$CANARY_FAIL" ]; then
      echo "Cannot connect to the Docker daemon at tcp://u:{SENTINELS["url_password"]}@h; token={SENTINELS["plain"]}" >&2
      exit 1
    fi
    echo '{{"ServerVersion": "{SENTINELS["plain"]}", "OperatingSystem": "Docker Desktop", "Architecture": "aarch64",'
    echo ' "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]],'
    echo ' "ClientInfo": {{"Context": "redis://:{SENTINELS["url_password"]}@redis"}}}}'
    ;;
  "compose version")
    echo "v2.40.0"
    echo "invalid hostPort: notaport_{SENTINELS["dollar"]}" >&2
    ;;
  *)
    echo "{SENTINELS["pem1"]} {SENTINELS["quoted"]}"
    echo "{SENTINELS["pem2"]}" >&2
    exit 1
    ;;
esac
"""
"""A `docker` that prints the sentinels, on stdout and stderr, in the shapes Compose and Docker use."""

COMMANDS = [
    ["doctor"],
    ["doctor", "--json"],
    ["--verbose", "doctor"],
    ["doctor", "--debug", "--verbose"],
    ["--verbose", "--dry-run", "doctor"],
    ["--json", "--verbose", "--debug", "--dry-run", "doctor"],
    ["doctor", "--tag", "preflight", "--json"],
    ["doctor", "--list"],
    ["doctor", "--list", "--json"],
    ["--version"],
    ["--version", "--json"],
    ["--help"],
    ["doctor", "--help"],
    ["doctor", "docker", "platform-env", "env-file", "ports-free"],
    # Forced failures, some echoing the user's argv.
    ["doctor", "no-such-check"],
    ["doctor", f"--no-such-option={SENTINELS['argv']}"],
    ["--json", "doctor", f"--no-such-option={SENTINELS['argv']}"],
    ["not-a-command", SENTINELS["argv"]],
    ["doctor", "--set", f"LLM_API_KEY={SENTINELS['argv']}"],
    ["--json", "doctor", "--set", f"AGENT_SECRET={SENTINELS['argv']}"],
    ["doctor", "--set", f"BACKEND_PORT={SENTINELS['argv']}"],
    ["doctor", "--target", SENTINELS["argv"]],
    # The commands of step 2.
    ["config", "show"],
    ["config", "show", "--json"],
    ["--verbose", "--debug", "config", "show"],
    ["config", "init"],
    ["config", "init", "--json"],
    ["--verbose", "--dry-run", "config", "init"],
    ["config", "init", "--yes", "--local-sdk", "--local-deeplynx"],
    ["config", "set", "BACKEND_PORT=9100"],
    ["config", "set", "--from-env", "SOME_API_TOKEN", "PASTED_BY_MISTAKE"],
    ["--json", "config", "set", "--from-env", "SOME_API_TOKEN"],
    ["config", "set", "--from-env", "NOT_IN_THE_ENVIRONMENT"],
    ["config", "set", f"LLM_API_KEY={SENTINELS['argv']}"],
    ["--json", "config", "set", f"AGENT_SECRET={SENTINELS['argv']}"],
    ["config", "set", f"--no-such-option={SENTINELS['argv']}"],
    ["config", "set", "--from-env", f"KEY={SENTINELS['argv']}"],
    ["config", "set", "--from-env", SENTINELS["argv"]],
    ["--json", "config", "set", "--from-env", SENTINELS["argv"]],
    ["status"],
    ["status", "--json"],
    ["--verbose", "--debug", "status", "--wait", "--timeout", "0"],
    ["--json", "status", "--wait", "--timeout", "0"],
    ["deeplynx", "setup", "--no-start", "--timeout", "0"],
    ["--json", "--verbose", "deeplynx", "setup", "--no-start", "--timeout", "0"],
    ["--dry-run", "deeplynx", "setup"],
]
"""Every command line to run, including forced failures that echo the user's argv."""


class Responder(BaseHTTPRequestHandler):
    """A loopback server for DeepLynx and the platform that answers with sentinels, so a path that prints a response shows it.

    It sends a new API key and secret, puts a sentinel in every error body, and echoes the `Authorization`
    header it receives into an error body, so printing a response or a request header is caught.
    """

    def _send(self, code: int, body: object) -> None:
        """Answer with this status and JSON body."""
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def _route(self, method: str) -> None:
        """Answer the routes `deeplynx setup` and `status` call."""
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        path = self.path
        if path.endswith("/health") or path == "/healthz":
            return self._send(200, {"status": "healthy", "note": SENTINELS["body"]})
        if path.endswith("/projects") and method == "GET":
            return self._send(200, [{"id": 7, "name": "Prometheus", "isArchived": False, "note": SENTINELS["body"]}])
        if path.endswith("/oauth/keys"):
            return self._send(200, {"apiKey": SENTINELS["issued_one"], "apiSecret": SENTINELS["issued_two"]})
        if path == "/v1/agents":
            # A 500 whose body echoes the credentials it was sent: nothing may print it.
            return self._send(500, {"error": SENTINELS["body"], "authorization": self.headers.get("Authorization", "")})
        return self._send(500, {"error": SENTINELS["body"], "authorization": self.headers.get("Authorization", "")})

    def do_GET(self):  # noqa: N802
        """Handle a GET."""
        self._route("GET")

    def do_POST(self):  # noqa: N802
        """Handle a POST."""
        self._route("POST")

    def log_message(self, *args):
        """Keep request logs out of the test output."""


@pytest.fixture
def responder():
    """A running `Responder`; yields its port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Responder)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.fixture
def canary_env(tmp_path, monkeypatch):
    """A platform folder with the canary `.env`, a fake `docker` on PATH, and an environment holding more secrets."""
    platform = tmp_path / "platform"
    platform.mkdir()
    (platform / ".env").write_text(DOTENV)
    (platform / ".env").chmod(0o600)
    (platform / "docker-compose.yml").write_text("services: {}\n")
    # What `config init` reads: the example (with a generator that prints a sentinel) and the profiles.
    (platform / ".env.example").write_text(
        'LLM_CONFIG_PROFILE=\nLLM_API_KEY=\nLLM_CONFIG_FILE=\n# gen\n#   python3 -c "print(1)"\nGENERATED_SECRET=\nNEW_KEY=\n'
    )
    profiles = tmp_path / "sdk" / "prometheus_api" / "llm_configs"
    profiles.mkdir(parents=True)
    (profiles / "anthropic.yaml").write_text("# Anthropic. x\nk: os.environ/LLM_API_KEY\n")
    (platform / "agents" / "client-agent").mkdir(parents=True)
    (platform / "agents" / "client-agent" / "agent_card.json").write_text('{"name": "Client Agent"}')
    (platform / "agents" / "client-agent" / "docker-compose.yml").write_text("services: {}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(cli.Paths, "default", classmethod(lambda cls, agent=None: cli.Paths(platform)))
    monkeypatch.setattr(host, "port_free", lambda port: True)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SOME_API_TOKEN": SENTINELS["env_only"],
        "DOCKER_HOST": f"tcp://user:{SENTINELS['env_only']}@host:2375",
    }
    return platform, env


def run(argv, env, **extra):
    """Run `cli.main` and return the exit code, stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    # A bare `print()` skips `Output` and its scrubber, so the real streams are captured too and added to the result.
    stray_out, stray_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stray_out), contextlib.redirect_stderr(stray_err):
        code = cli.main(argv, env={**env, **extra}, out=out, err=err)
    return code, out.getvalue() + stray_out.getvalue(), err.getvalue() + stray_err.getvalue()


def assert_clean(text: str, where: str) -> None:
    """Fail if any sentinel, or any line of one, appears in the text."""
    for name, sentinel in SENTINELS.items():
        assert sentinel not in text, f"sentinel {name} leaked in {where}"
        for line in sentinel.splitlines():
            assert line not in text, f"sentinel {name} leaked in {where}"
    # Encoded forms.
    assert "CANARYPEMLINEONE0005abcdef\\n" not in text, f"JSON-escaped PEM leaked in {where}"


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a)[:60])
@pytest.mark.parametrize("fail", [False, True], ids=["docker-ok", "docker-fails"])
def test_no_sentinel_in_stdout_or_stderr(canary_env, argv, fail):
    """No sentinel in stdout or stderr."""
    _, env = canary_env
    _, out, err = run(argv, env, **({"CANARY_FAIL": "1"} if fail else {}))
    assert_clean(out, f"stdout of {argv}")
    assert_clean(err, f"stderr of {argv}")


RESPONDING = [
    ["status"],
    ["--json", "status"],
    ["--verbose", "--debug", "status", "--wait", "--timeout", "0"],
    ["--json", "--verbose", "--debug", "status", "--wait", "--timeout", "0"],
    ["deeplynx", "setup", "--no-start", "--timeout", "2"],
    ["--json", "--verbose", "--debug", "deeplynx", "setup", "--no-start", "--timeout", "2"],
]
"""Commands that talk to a server, run against a `Responder` that answers with sentinels."""


@pytest.mark.parametrize("argv", RESPONDING, ids=lambda a: " ".join(a)[:60])
def test_no_sentinel_a_server_sends_or_is_sent_reaches_the_output_or_env(canary_env, responder, argv):
    """A new DeepLynx key and secret, an error body and the bearer token a request carries stay out of the output.

    The earlier canary only reached "connection refused", so a change that printed a response body or a header
    would have passed. The generated key and secret are saved in `.env` (that is their job) but never printed.
    """
    platform, env = canary_env
    (platform / ".env").write_text(
        (platform / ".env").read_text().replace("AGENT_SECRET=", "OLD_AGENT_SECRET=")
        + f"AGENT_SECRET={SENTINELS['auth']}\nLOCAL_DEEPLYNX=true\n"
    )
    ports = {
        "BACKEND_PORT": str(responder),
        "DEEPLYNX_SERVER_PORT": str(responder),
        "PROFILE": "",
    }
    _, out, err = run(argv, env, **ports)
    for name in ("issued_one", "issued_two", "body", "auth"):
        assert SENTINELS[name] not in out + err, f"sentinel {name} leaked in {argv}"
    assert_clean(out, f"stdout of {argv}")
    assert_clean(err, f"stderr of {argv}")


def test_a_new_deeplynx_key_is_saved_in_env_but_not_printed(canary_env, responder):
    """`deeplynx setup` writes the key it was given to `.env` (mode kept) and says nothing of its value."""
    platform, env = canary_env
    (platform / ".env").write_text((platform / ".env").read_text() + "LOCAL_DEEPLYNX=true\n")
    code, out, err = run(
        ["deeplynx", "setup", "--no-start", "--timeout", "2"], env, DEEPLYNX_SERVER_PORT=str(responder), PROFILE=""
    )
    saved = (platform / ".env").read_text()
    assert code == 0 and SENTINELS["issued_one"] in saved and SENTINELS["issued_two"] in saved
    assert SENTINELS["issued_one"] not in out + err and SENTINELS["issued_two"] not in out + err
    assert stat.S_IMODE(os.stat(platform / ".env").st_mode) == 0o600


def test_the_canary_would_notice_a_leak(canary_env):
    """A canary that can't fail proves nothing: without the scrubber, the sentinels do show."""
    platform, env = canary_env
    out, err = io.StringIO(), io.StringIO()
    from platformctl.config import PlatformConfig
    from platformctl.output import Output, Scrubber
    from platformctl.paths import Paths
    from platformctl.system.runner import Runner

    output = Output(Scrubber(), out=out, err=err, env={})
    runner = Runner()  # no scrubber
    from platformctl.context import build

    ctx = build(Paths(platform), PlatformConfig(platform, env), output, runner)
    info = ctx.docker.info()
    assert SENTINELS["plain"] in info.server_version  # the fake docker really prints the sentinel


def test_child_output_is_scrubbed_before_anyone_sees_it(canary_env):
    """Child output is scrubbed before anyone sees it."""
    platform, env = canary_env
    from platformctl.config import PlatformConfig
    from platformctl.output import Scrubber
    from platformctl.system.runner import Runner

    config = PlatformConfig(platform, env)
    scrubber = Scrubber()
    scrubber.add_all(config.secret_values())
    done = Runner(scrub=scrubber.scrub).run(["docker", "x"], env=env)
    assert_clean(done.stdout + done.stderr, "captured child output")
    assert "***" in done.stdout


def test_doctor_json_is_valid_and_clean(canary_env):
    """Doctor json is valid and clean."""
    import json

    _, env = canary_env
    code, out, _ = run(["doctor", "--json"], env)
    body = json.loads(out)  # still valid JSON after scrubbing
    assert body["ok"] and code in (0, 1)
    assert_clean(out, "doctor --json")


def test_generated_files_have_no_sentinel(canary_env):
    """Generated files have no sentinel."""
    platform, env = canary_env
    ctx, _, _ = make_context(platform, __import__("platformctl.system.runner", fromlist=["Runner"]).Runner(), env)
    ctx.target.generate()
    generated = [
        p
        for p in platform.iterdir()
        if p.name in ("docker-compose.platform.yml", ".platform.env", "docker-compose.agents.yml")
    ]
    assert len(generated) == 3
    for path in generated:
        assert_clean(path.read_text(), path.name)


def test_platform_env_has_only_registered_safe_keys(canary_env):
    """Platform env has only registered safe keys."""
    from platformctl import config as cfg
    from platformctl.system import envfile

    platform, env = canary_env
    ctx, _, _ = make_context(platform, __import__("platformctl.system.runner", fromlist=["Runner"]).Runner(), env)
    ctx.target.generate()
    keys = envfile.read(platform / ".platform.env")
    assert keys and all(cfg.is_safe(k) for k in keys)


def test_the_env_file_itself_is_untouched_by_doctor(canary_env):
    """The env file itself is untouched by doctor."""
    platform, env = canary_env
    before = (platform / ".env").read_text()
    run(["doctor"], env)
    assert (platform / ".env").read_text() == before
    assert stat.S_IMODE(os.stat(platform / ".env").st_mode) == 0o600


def test_this_test_runs_the_real_python_not_a_stub():
    """This test runs the real python not a stub."""
    assert sys.version_info >= (3, 10) and Path(cli.__file__).exists()
