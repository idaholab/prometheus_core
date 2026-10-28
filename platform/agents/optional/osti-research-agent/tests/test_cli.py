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

"""The local CLI (python -m research_agent): options, output, exit codes."""

import json

import pytest

from research_agent import cli
from research_agent.core.events import FinalResult, ProgressEvent


class _Runner:
    configs = []
    events = []

    def __init__(self, config):
        _Runner.configs.append(config)

    async def run(self, question, *, run_id):
        for event in _Runner.events:
            yield event


@pytest.fixture
def runner(monkeypatch):
    _Runner.configs, _Runner.events = [], []
    monkeypatch.setattr(cli, "ResearchRunner", _Runner)
    monkeypatch.setenv("REDIS_URL", "redis://r:6379")
    return _Runner


@pytest.mark.parametrize("status, code", [
    ("completed", 0), ("no_results", 0), ("error", 1), ("timeout_partial", 1),
])
def test_writes_the_result_and_exits_by_status(runner, tmp_path, capsys, status, code):
    runner.events = [ProgressEvent(message="Searching OSTI"),
                     FinalResult(status=status, question="q", answer="a")]

    assert cli.main(["q", "--workdir", str(tmp_path), "--run-id", "r1"]) == code

    out, err = capsys.readouterr()
    assert json.loads((tmp_path / "result.json").read_text())["status"] == status
    assert json.loads(out)["answer"] == "a"
    assert "Searching OSTI" in err and "Wrote" in err
    assert runner.configs[0].workdir == tmp_path


def test_no_redis_drops_the_redis_url(runner, tmp_path):
    runner.events = [FinalResult(status="completed", question="q")]

    cli.main(["q", "--no-redis", "--workdir", str(tmp_path)])

    assert runner.configs[0].redis_url is None


def test_default_workdir_is_out(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.events = [FinalResult(status="completed", question="q")]

    cli.main(["q"])

    assert (tmp_path / "out" / "result.json").exists()


def test_no_result_exits_1(runner, tmp_path, capsys):
    assert cli.main(["q", "--workdir", str(tmp_path)]) == 1
    assert "No result produced." in capsys.readouterr().err


def test_module_entry_point_runs_the_cli(monkeypatch):
    import runpy

    calls = []
    monkeypatch.setattr(cli, "main", lambda argv=None: calls.append(argv) or 0)
    monkeypatch.setattr("sys.argv", ["research_agent", "q"])

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("research_agent", run_name="__main__")

    assert exit_info.value.code == 0 and calls == [None]
