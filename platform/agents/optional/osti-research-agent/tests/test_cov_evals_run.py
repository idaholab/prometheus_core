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

"""Coverage for the evaluation runner: config loading, Redis isolation, argument
checks, progress capture, and Ctrl+C handling. Engine, Redis and LLM are faked."""

import asyncio
import json
import sys

import pytest

from evals import run as eval_run
from research_agent.core.config import AgentConfig
from research_agent.core.events import FinalResult, ProgressEvent


def _config(**overrides):
    return AgentConfig(litellm_base_url="http://unused", **overrides)


def _questions(tmp_path, text="questions:\n  - id: one\n    question: Test question?\n"):
    path = tmp_path / "questions.yaml"
    path.write_text(text)
    return path


# --- questions and config ------------------------------------------------


def test_an_empty_question_file_stops_the_run(tmp_path):
    with pytest.raises(SystemExit, match="no questions found in"):
        eval_run._load_questions(_questions(tmp_path, "questions: []\n"))


def test_a_bare_list_of_questions_is_accepted(tmp_path):
    path = _questions(tmp_path, "- id: a\n  question: Q?\n")

    assert eval_run._load_questions(path) == [{"id": "a", "question": "Q?"}]


def test_agent_config_comes_from_the_prometheus_llm_profile(monkeypatch):
    from prometheus_api.llm_client import LLMConfig

    sentinel_llm, sentinel_config = object(), _config()
    monkeypatch.setattr(LLMConfig, "from_env", staticmethod(lambda: sentinel_llm))
    seen = []

    def configured(llm):
        seen.append(llm)
        return sentinel_config

    monkeypatch.setattr(eval_run, "_configured_agent_config", configured)

    assert eval_run._load_agent_config() is sentinel_config
    assert seen == [sentinel_llm]


def test_agent_config_needs_the_prometheus_runtime(monkeypatch):
    monkeypatch.setitem(sys.modules, "prometheus_api.llm_client", None)

    with pytest.raises(RuntimeError, match="must run in the OSTI agent runtime"):
        eval_run._load_agent_config()


# --- Redis isolation ------------------------------------------------------


class _FakeRedis:
    def __init__(self, size):
        self.size, self.closed = size, False

    def dbsize(self):
        return self.size

    def close(self):
        self.closed = True


def _patch_redis(monkeypatch, size):
    clients, calls = [], []

    def from_url(url, **kwargs):
        calls.append((url, kwargs))
        clients.append(_FakeRedis(size))
        return clients[-1]

    monkeypatch.setattr(eval_run.redis.Redis, "from_url", staticmethod(from_url))
    return clients, calls


def test_an_empty_redis_database_is_accepted_and_the_client_closed(monkeypatch):
    clients, calls = _patch_redis(monkeypatch, 0)
    config = _config(redis_url="redis://r:6379/5", redis_password="pw")

    eval_run._require_empty_redis(config, "deepagent")

    assert calls == [("redis://r:6379/5", {"password": "pw", "decode_responses": True})]
    assert clients[0].closed is True


def test_a_redis_database_with_keys_is_refused(monkeypatch):
    clients, _ = _patch_redis(monkeypatch, 3)

    with pytest.raises(RuntimeError, match=r"deepagent is not empty \(3 keys\)"):
        eval_run._require_empty_redis(_config(redis_url="redis://r:6379"), "deepagent")
    assert clients[0].closed is True


# --- running one engine ---------------------------------------------------


class _Runner:
    configs = []

    def __init__(self, config):
        self.configs.append(config)

    async def run(self, question, *, run_id):
        yield ProgressEvent(message="Searching OSTI")
        yield ProgressEvent(message="Reading paper 1")
        yield FinalResult(status="completed", question=question, answer="done")


def test_run_one_logs_progress_and_forwards_it(monkeypatch):
    monkeypatch.setattr(eval_run, "ResearchRunner", _Runner)
    messages = []

    final, wall_s, log = asyncio.run(
        eval_run._run_one(_config(), "Q?", "run-1", on_progress=messages.append)
    )

    assert final.answer == "done" and wall_s >= 0
    assert messages == ["Searching OSTI", "Reading paper 1"]
    assert len(log) == 2 and log[0].startswith("+") and log[0].endswith("s Searching OSTI")


def test_run_one_without_a_progress_callback_still_logs(monkeypatch):
    monkeypatch.setattr(eval_run, "ResearchRunner", _Runner)

    _, _, log = asyncio.run(eval_run._run_one(_config(), "Q?", "run-1"))

    assert [line.split(" ", 1)[1] for line in log] == ["Searching OSTI", "Reading paper 1"]


def test_run_engine_uses_its_own_empty_redis_database(tmp_path, monkeypatch):
    _Runner.configs = []
    monkeypatch.setattr(eval_run, "ResearchRunner", _Runner)
    checked = []
    monkeypatch.setattr(
        eval_run, "_require_empty_redis", lambda config, engine: checked.append(
            (config.redis_url, engine)
        )
    )
    spec = {"id": "one", "question": "Q?"}

    records = asyncio.run(eval_run._run_engine(
        "deepagent", [spec], _config(redis_url="redis://r:6379/0"), tmp_path, 7
    ))

    assert checked == [("redis://r:6379/7", "deepagent")]
    assert _Runner.configs[0].redis_url == "redis://r:6379/7"
    assert records[0]["id"] == "one"
    saved = json.loads((tmp_path / "deepagent" / "one" / "result.json").read_text())
    assert saved["_engine"] == "deepagent" and saved["answer"] == "done"
    log = (tmp_path / "deepagent" / "one" / "progress.log").read_text()
    assert "Searching OSTI" in log


# --- argument checks ------------------------------------------------------


def _main(tmp_path, monkeypatch, *extra, config=None):
    monkeypatch.setattr(
        eval_run, "_load_agent_config",
        lambda: config or _config(redis_url="redis://r:6379"),
    )
    calls = []

    async def fake_run_engine(engine, specs, base, workdir, redis_db, **kwargs):
        calls.append((engine, redis_db, base.redis_url))
        return []

    monkeypatch.setattr(eval_run, "_run_engine", fake_run_engine)
    result = asyncio.run(eval_run._main([
        "--questions", str(_questions(tmp_path)), "--report", str(tmp_path / "report.json"),
        "--workdir", str(tmp_path / "out"), "--no-judge", *extra,
    ]))
    return result, calls


@pytest.mark.parametrize(
    "extra, config, message",
    [
        (("--no-redis", "--redis-db-base", "3"), None,
         "--no-redis and --redis-db-base cannot be used together"),
        (("--redis-db-base", "3"), _config(redis_url=None), "--redis-db-base requires REDIS_URL"),
        (("--engines", "deepagent", "deepagent"), None,
         "--redis-db-base is required for multi-engine runs"),
        (("--redis-db-base", "-1"), None, "--redis-db-base must be non-negative"),
    ],
)
def test_conflicting_redis_options_are_rejected(
    tmp_path, monkeypatch, capsys, extra, config, message
):
    with pytest.raises(SystemExit) as stopped:
        _main(tmp_path, monkeypatch, *extra, config=config)

    assert stopped.value.code == 2
    assert message in capsys.readouterr().err


def test_no_redis_clears_the_redis_url(tmp_path, monkeypatch):
    result, calls = _main(tmp_path, monkeypatch, "--no-redis")

    assert result == 0 and calls == [("deepagent", None, None)]


def test_multi_engine_runs_get_one_database_each(tmp_path, monkeypatch):
    result, calls = _main(
        tmp_path, monkeypatch, "--engines", "deepagent", "deepagent", "--redis-db-base", "4"
    )

    assert result == 0
    assert [(engine, db) for engine, db, _ in calls] == [("deepagent", 4), ("deepagent", 5)]


# --- interruption ---------------------------------------------------------


def _interrupted(tmp_path, monkeypatch, exc, records):
    monkeypatch.setattr(eval_run, "_load_agent_config", lambda: _config())

    async def interrupted(engine, specs, base, workdir, redis_db, on_record=None, **kwargs):
        for _ in range(records):
            on_record({"id": "one", "engine": engine, "status": "completed",
                       "status_match": True, "provenance_ok": True,
                       "citation_link_rate": 1.0, "source_hit_rate": 1.0,
                       "fact_match": 1.0, "wall_s": 3.0})
        raise exc

    monkeypatch.setattr(eval_run, "_run_engine", interrupted)
    report_path = tmp_path / "r" / "report.json"
    result = asyncio.run(eval_run._main([
        "--questions", str(_questions(tmp_path)), "--report", str(report_path),
        "--workdir", str(tmp_path / "out"), "--no-judge", "--no-redis",
    ]))
    return result, report_path


def test_ctrl_c_keeps_the_finished_questions_as_a_partial_report(
    tmp_path, monkeypatch, capsys
):
    result, report_path = _interrupted(tmp_path, monkeypatch, KeyboardInterrupt(), 1)

    assert result == eval_run.INTERRUPTED_EXIT == 130
    report = json.loads(report_path.read_text())
    assert report["complete"] is False and len(report["records"]) == 1
    captured = capsys.readouterr()
    assert "Interrupted after 1 of 1 question(s)." in captured.err
    assert f"Partial report: {report_path}" in captured.err
    assert "OSTI evaluation  1/1 passed" in captured.out and "partial run" in captured.out


def test_a_cancelled_run_with_nothing_finished_prints_no_summary(
    tmp_path, monkeypatch, capsys
):
    result, report_path = _interrupted(tmp_path, monkeypatch, asyncio.CancelledError(), 0)

    assert result == 130
    assert json.loads(report_path.read_text())["records"] == []
    captured = capsys.readouterr()
    assert "Interrupted after 0 of 1 question(s)." in captured.err
    assert "OSTI evaluation" not in captured.out


def test_main_runs_with_sys_argv_by_default(monkeypatch):
    seen = []

    async def fake_main(argv):
        seen.append(argv)
        return 0

    monkeypatch.setattr(eval_run, "_main", fake_main)
    monkeypatch.setattr(sys, "argv", ["evals.run", "--limit", "1"])

    assert eval_run.main() == 0
    assert eval_run.main(["--no-judge"]) == 0
    assert seen == [["--limit", "1"], ["--no-judge"]]


def test_a_second_ctrl_c_exits_quietly(monkeypatch, capsys):
    async def fake_main(argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(eval_run, "_main", fake_main)

    assert eval_run.main([]) == eval_run.INTERRUPTED_EXIT
    assert "Interrupted." in capsys.readouterr().err
