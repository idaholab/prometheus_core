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

"""The question's topic: one model call per run names the subject and the
asked quantity, and read_top_candidates reads papers that name them first,
skipping papers that never name the subject."""

import asyncio
import json

from research_agent import llm_steps
from research_agent.core.config import AgentConfig
from research_agent.rerank import QuestionTopic
from research_agent.tools import RunContext, batch

QUESTION = "How does irradiation affect the fatigue life of Inconel 718?"
TOPIC_REPLY = json.dumps(
    {
        "subject": ["Inconel 718", "Alloy 718", "IN718", "718"],
        "quantity": ["fatigue life", "fatigue", ""],
    }
)


def _complete(reply=TOPIC_REPLY, calls=None, exc=None):
    async def complete(prompt, *, max_tokens):
        if calls is not None:
            calls.append(prompt)
        if exc is not None:
            raise exc
        return reply

    return complete


# --- llm_steps.question_topic ----------------------------------------------


def test_topic_is_read_from_the_reply_without_unusable_names():
    calls = []

    topic = asyncio.run(llm_steps.question_topic(QUESTION, _complete(calls=calls)))

    assert topic == QuestionTopic(
        subject=("Inconel 718", "Alloy 718", "IN718"), quantity=("fatigue life", "fatigue")
    )
    assert QUESTION in calls[0]


def test_topic_reply_in_a_code_block_is_read():
    reply = f"```json\n{TOPIC_REPLY}\n```"

    topic = asyncio.run(llm_steps.question_topic(QUESTION, _complete(reply)))

    assert topic.subject[0] == "Inconel 718"


def test_topic_keeps_at_most_ten_names():
    reply = json.dumps({"subject": [f"Alloy {i}" for i in range(20)], "quantity": "fatigue"})

    topic = asyncio.run(llm_steps.question_topic(QUESTION, _complete(reply)))

    assert len(topic.subject) == 10
    assert topic.quantity == ()  # not a list


def test_no_topic_when_the_call_fails_or_the_reply_has_no_json(caplog):
    failed = asyncio.run(llm_steps.question_topic(QUESTION, _complete(exc=RuntimeError("404"))))
    prose = asyncio.run(llm_steps.question_topic(QUESTION, _complete("It is about Inconel.")))

    assert failed is None and prose is None
    assert "Question topic unavailable: 404" in caplog.text
    assert "no JSON object" in caplog.text


def test_no_topic_when_the_call_takes_too_long(monkeypatch, caplog):
    monkeypatch.setattr(llm_steps, "TOPIC_TIMEOUT_S", 0.01)

    async def slow(prompt, *, max_tokens):
        await asyncio.sleep(1)

    assert asyncio.run(llm_steps.question_topic(QUESTION, slow)) is None
    assert "no reply in" in caplog.text


# --- RunContext: one lookup per run -----------------------------------------


def _ctx(complete):
    ctx = RunContext(
        config=AgentConfig(litellm_base_url="http://unused"), complete=complete, question=QUESTION
    )
    ctx.search_hits = {
        "1": {"title": "Fatigue of irradiated Alloy 718", "description": "x", "origin": "osti"},
        "2": {"title": "Tensile properties of Inconel 718", "description": "x", "origin": "osti"},
        "3": {"title": "Fatigue life of type 316 stainless steel after irradiation",
              "description": "fatigue fatigue irradiation", "origin": "osti"},
    }
    return ctx


def test_the_topic_is_looked_up_once_and_orders_the_candidates():
    calls = []
    ctx = _ctx(_complete(calls=calls))

    first, skipped = asyncio.run(ctx.candidates_to_read())
    asyncio.run(ctx.candidates_to_read())

    assert len(calls) == 1
    # The 316 paper ranks high on BM25 but never names Inconel 718.
    assert [sid for sid, _, _ in first] == ["1", "2"] and skipped == 1


def test_without_a_topic_papers_sharing_a_word_are_kept():
    ctx = _ctx(_complete(exc=RuntimeError("down")))

    order, skipped = asyncio.run(ctx.candidates_to_read())

    assert ctx.question_topic is None
    assert {sid for sid, _, _ in order} == {"1", "2", "3"} and skipped == 0


def test_nothing_unread_needs_no_lookup():
    calls = []
    ctx = _ctx(_complete(calls=calls))
    ctx.search_hits = {}

    assert asyncio.run(ctx.candidates_to_read()) == ([], 0)
    assert calls == []


# --- read_top_candidates -----------------------------------------------------


class _Steps:
    def __init__(self, ctx):
        self.ctx, self.order = ctx, []

    async def download(self, args):
        self.order.append(args["source_id"])
        return json.dumps({"ok": True})

    async def parse(self, args):
        self.ctx.papers_attempted += 1
        return json.dumps({"source_id": args["source_id"]})

    async def analyze(self, args):
        result = {"answered": False, "reason": "no data"}
        self.ctx.paper_analysis_results[args["source_id"]] = result
        return json.dumps(result)


def test_a_batch_skips_papers_that_never_name_the_subject():
    ctx = _ctx(_complete())
    steps = _Steps(ctx)

    out = asyncio.run(batch.read_top_candidates(ctx, steps.download, steps.parse, steps.analyze))

    assert steps.order == ["1", "2"] and out["skipped_unrelated"] == 1


def test_when_no_paper_names_the_subject_the_run_is_told_to_search_again():
    ctx = _ctx(_complete())
    ctx.search_hits = {"3": ctx.search_hits["3"]}

    out = asyncio.run(batch.read_top_candidates(ctx, None, None, None))

    assert out["read"] == [] and out["stop"] is False
    assert out["reason"] == (
        "none of the 1 unread search result(s) names Inconel 718 or Alloy 718 or IN718 "
        "in its title or abstract"
    )
    assert "Search again" in out["instruction"] and out["skipped_unrelated"] == 1


def test_parallel_batches_share_one_topic_lookup():
    calls = []
    ctx = _ctx(_complete(calls=calls))

    async def both():
        return await asyncio.gather(ctx.candidates_to_read(), ctx.candidates_to_read())

    first, second = asyncio.run(both())

    assert len(calls) == 1
    assert first == second and first[1] == 1  # both used the topic
