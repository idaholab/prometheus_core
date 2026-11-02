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

import io
import os
import stat
import sys
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
}
"""A unique value for each shape of secret: plain, with `$`, quoted, in a URL, multi-line, from the environment, from argv."""

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
]
"""Every command line to run, including forced failures that echo the user's argv."""


@pytest.fixture
def canary_env(tmp_path, monkeypatch):
    """A platform folder with the canary `.env`, a fake `docker` on PATH, and an environment holding more secrets."""
    platform = tmp_path / "platform"
    platform.mkdir()
    (platform / ".env").write_text(DOTENV)
    (platform / ".env").chmod(0o600)
    (platform / "docker-compose.yml").write_text("services: {}\n")
    (platform / "agents" / "client-agent").mkdir(parents=True)
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
    code = cli.main(argv, env={**env, **extra}, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


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
